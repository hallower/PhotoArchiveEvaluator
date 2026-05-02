"""고급 평가 (외부 비전 API) API.

POST /api/photos/{id}/advanced-review            — Claude vision 호출 + 결과 저장
GET  /api/photos/{id}/advanced-reviews           — 이력 조회 (최신순)
DELETE /api/advanced-reviews/{review_id}         — 단건 삭제
GET  /api/advanced/cost-preview?model=...        — 비용 추정 (이미지 픽셀 기준)

흐름
- consent (external.allow_send) 확인 → 미승인이면 409
- 사진 콘텐츠 로드 (로컬/DSM)
- strip_exif=true면 메타데이터 제거 → 외부 전송
- 모델 호출 → advanced_reviews 저장 + api_costs 기록
"""

from __future__ import annotations

import base64
import logging
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.exif_strip import strip_exif_jpeg
from ..ai.remote import keys as api_keys
from ..ai.remote.claude import PRICING, ClaudeVisionReview
from ..auth.dependencies import require_auth
from ..nas.session import open_dsm_client
from ..settings_store import (
    DEFAULT_ADVANCED_PROMPT,
    get_external_allow_send,
    get_external_default_model,
    get_external_strip_exif,
)
from ..storage.db import get_session
from ..storage.models import AdvancedReview, ApiCost, Photo, PhotoPath

log = logging.getLogger(__name__)

router = APIRouter(
    tags=["advanced"],
    dependencies=[Depends(require_auth)],
)


class _ReviewIn(BaseModel):
    prompt: str | None = None  # None이면 default
    model: str | None = None  # None이면 settings의 default


class _CostPreviewIn(BaseModel):
    photo_id: int
    model: str | None = None


def _read_image(session: Session, pp: PhotoPath) -> bytes:
    if pp.nas_id == "local":
        path = Path(pp.path)
        if not path.exists():
            raise FileNotFoundError(str(path))
        return path.read_bytes()
    if pp.nas_id.startswith("dsm:"):
        with open_dsm_client(session) as client:
            return client.download(pp.path)
    raise FileNotFoundError(f"unsupported nas_id: {pp.nas_id}")


@router.post("/api/photos/{photo_id}/advanced-review")
def advanced_review(
    photo_id: int,
    body: _ReviewIn,
    session: Session = Depends(get_session),
) -> dict:
    if not get_external_allow_send(session):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "external API send is disabled — enable in Settings → 외부 전송 동의",
        )

    api_key = api_keys.get("anthropic")
    if not api_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Anthropic API key not set — Settings → 외부 API 키",
        )

    photo = session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo not found")
    pp = session.execute(
        select(PhotoPath).where(PhotoPath.photo_id == photo_id).limit(1)
    ).scalar_one_or_none()
    if pp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo path not found")

    try:
        content = _read_image(session, pp)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_410_GONE, "source missing") from exc

    if get_external_strip_exif(session):
        content = strip_exif_jpeg(content)

    prompt = (body.prompt or DEFAULT_ADVANCED_PROMPT).strip() or DEFAULT_ADVANCED_PROMPT
    model = body.model or get_external_default_model(session)
    if model not in PRICING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unsupported model: {model}")

    try:
        client = ClaudeVisionReview(api_key=api_key, model=model)
        result = client.review(content, prompt)
    except Exception as exc:  # noqa: BLE001
        log.exception("claude review failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"API call failed: {exc}") from exc

    # 저장
    rev = AdvancedReview(
        photo_id=photo_id,
        model_id=result.model_id,
        prompt=prompt,
        response=result.response,
        cost_usd=result.cost_usd,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
    )
    session.add(rev)
    if result.cost_usd is not None:
        session.add(
            ApiCost(
                model_id=result.model_id,
                photo_id=photo_id,
                cost_usd=result.cost_usd,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
            )
        )
    session.commit()
    session.refresh(rev)

    return {
        "id": rev.id,
        "model_id": rev.model_id,
        "response": rev.response,
        "cost_usd": rev.cost_usd,
        "tokens_in": rev.tokens_in,
        "tokens_out": rev.tokens_out,
        "created_at": rev.created_at.isoformat(),
    }


@router.get("/api/photos/{photo_id}/advanced-reviews")
def list_reviews(photo_id: int, session: Session = Depends(get_session)) -> list[dict]:
    rows = (
        session.execute(
            select(AdvancedReview)
            .where(AdvancedReview.photo_id == photo_id)
            .order_by(AdvancedReview.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "model_id": r.model_id,
            "prompt": r.prompt,
            "response": r.response,
            "cost_usd": r.cost_usd,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "user_note": r.user_note,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.delete("/api/advanced-reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_review(review_id: int, session: Session = Depends(get_session)) -> None:
    n = session.execute(
        AdvancedReview.__table__.delete().where(AdvancedReview.id == review_id)
    ).rowcount
    session.commit()
    if not n:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "review not found")


@router.get("/api/advanced/cost-preview")
def cost_preview(
    photo_id: int,
    model: str | None = Query(None),
    session: Session = Depends(get_session),
) -> dict:
    """이미지 픽셀 기준 추정. 실제 호출 없음."""
    photo = session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo not found")

    chosen_model = model or get_external_default_model(session)
    if chosen_model not in PRICING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unsupported model: {chosen_model}")

    width = photo.width or 1024
    height = photo.height or 768
    # api_key 없이 dummy 인스턴스로 추정만
    dummy = ClaudeVisionReview.__new__(ClaudeVisionReview)
    dummy._model = chosen_model
    dummy._client = None  # type: ignore[assignment]
    dummy.model_id = f"claude:{chosen_model}"
    cost = dummy.estimate_cost(width, height)
    return {
        "model": chosen_model,
        "cost_usd_estimate": round(cost, 5),
        "image_width": width,
        "image_height": height,
    }


@router.get("/api/advanced/models")
def list_models() -> dict:
    return {
        "models": [
            {"id": m, "input_price_per_million": p[0], "output_price_per_million": p[1]}
            for m, p in PRICING.items()
        ],
    }
