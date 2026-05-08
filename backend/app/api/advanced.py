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
from ..ai.remote.registry import MODELS, TEXT_DEFAULTS, get_provider, make_adapter
from ..ai.remote.text import call_text_llm
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

    model = body.model or get_external_default_model(session)
    if model not in MODELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unsupported model: {model}")

    provider = get_provider(model) or "anthropic"
    api_key = api_keys.get(provider)
    if not api_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{provider} API key not set — Settings → 외부 API 키",
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

    try:
        client = make_adapter(model, api_key)
        result = client.review(content, prompt)
    except Exception as exc:  # noqa: BLE001
        log.exception("advanced review failed (%s)", model)
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
    if chosen_model not in MODELS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unsupported model: {chosen_model}")

    width = photo.width or 1024
    height = photo.height or 768
    # registry로 provider별 어댑터를 받아 estimate_cost만 사용 (네트워크 호출 없음).
    # API key 없이도 estimate_cost가 동작해야 하므로 어댑터를 직접 구성하는 대신
    # provider별 정적 추정 사용.
    cost = _estimate_cost_no_call(chosen_model, width, height)
    return {
        "model": chosen_model,
        "cost_usd_estimate": round(cost, 5),
        "image_width": width,
        "image_height": height,
    }


def _estimate_cost_no_call(model: str, width: int, height: int, max_out: int = 1024) -> float:
    """API 키 없이 가격만 사용한 정적 추정. 어댑터별 estimate_cost 로직을 모방."""
    from ..ai.remote.registry import get_price

    in_p, out_p = get_price(model)
    if model.startswith("claude"):
        image_tokens = max(1, (width * height) // 750)
    elif model.startswith("gpt"):
        image_tokens = max(85, (width * height) // 1500)
    elif model.startswith("gemini"):
        tiles_w = max(1, width // 768) + 1
        tiles_h = max(1, height // 768) + 1
        image_tokens = tiles_w * tiles_h * 258
    else:
        image_tokens = max(1, (width * height) // 750)
    in_tokens = image_tokens + 100
    return (in_tokens * in_p + max_out * out_p) / 1_000_000


@router.get("/api/advanced/models")
def list_models() -> dict:
    return {
        "models": [
            {
                "id": m,
                "provider": info.provider,
                "input_price_per_million": info.input_price,
                "output_price_per_million": info.output_price,
            }
            for m, info in MODELS.items()
        ],
    }


class _TranslateIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    target_lang: str = Field(default="Korean", max_length=40)
    review_id: int | None = None  # 비용 추적용 (선택)


@router.post("/api/advanced/translate")
def translate_text(body: _TranslateIn, session: Session = Depends(get_session)) -> dict:
    """고급 평가 결과 등 텍스트를 지정 언어로 번역. 텍스트-only LLM 사용 (저렴한 모델 자동 선택).

    provider 선택 순서:
      1) 기본 모델의 provider에 키가 있으면 그 provider의 텍스트-기본 모델 사용
      2) 없으면 TEXT_DEFAULTS에 등록된 다른 provider 중 키가 있는 것 사용
      3) 어느 provider도 키가 없으면 409
    """
    from ..settings_store import get_external_allow_send, get_external_default_model

    if not get_external_allow_send(session):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "external API send is disabled — enable in Settings",
        )

    default_model = get_external_default_model(session)
    preferred_provider = get_provider(default_model)
    # 후보 provider 순서: 선호 provider 먼저, 그 다음 TEXT_DEFAULTS에 등록된 나머지
    candidates: list[str] = []
    if preferred_provider:
        candidates.append(preferred_provider)
    for p in TEXT_DEFAULTS:
        if p not in candidates:
            candidates.append(p)

    provider: str | None = None
    api_key: str | None = None
    for p in candidates:
        k = api_keys.get(p)
        if k:
            provider = p
            api_key = k
            break

    if provider is None or api_key is None:
        configured = [p for p in TEXT_DEFAULTS if api_keys.get(p)]
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"no API key registered — configure one in Settings (tried: {', '.join(candidates)}; configured: {configured or 'none'})",
        )

    text_model = TEXT_DEFAULTS.get(provider, default_model)

    prompt = (
        f"Translate the following text into {body.target_lang}. "
        "Preserve formatting (line breaks, bullets, headings). "
        "Do not add any preamble, explanation, or quotation marks — output the translation only.\n\n"
        f"---\n{body.text}\n---"
    )

    try:
        translated, t_in, t_out = call_text_llm(
            provider, text_model, api_key, prompt, max_tokens=2048
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("translate failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"translate failed: {exc}"
        ) from exc

    # 비용 기록 (선택)
    from ..ai.remote.registry import get_price

    in_p, out_p = get_price(text_model)
    cost = ((t_in or 0) * in_p + (t_out or 0) * out_p) / 1_000_000
    if cost > 0:
        session.add(
            ApiCost(
                model_id=f"{provider}:{text_model}",
                photo_id=None,
                cost_usd=cost,
                tokens_in=t_in,
                tokens_out=t_out,
            )
        )
        session.commit()

    return {
        "translated": translated.strip(),
        "model": f"{provider}:{text_model}",
        "tokens_in": t_in,
        "tokens_out": t_out,
        "cost_usd": cost,
    }
