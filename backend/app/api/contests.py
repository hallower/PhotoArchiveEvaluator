"""공모전 분석기 API.

흐름
1. 사용자 → POST /api/contests/analyze {info_text} → AI(Claude)가 5–10개 테마 추출
2. 사용자 → POST /api/contests {name, info_text, themes} → DB 저장
3. 사용자 → GET /api/contests/{id}/matches → 테마별 CLIP 매칭 사진 (top N)
4. 사용자 → POST /api/contests/{id}/portfolio {photo_ids[]} → 새 포트폴리오 생성

GET    /api/contests
POST   /api/contests
GET    /api/contests/{id}
PUT    /api/contests/{id}
DELETE /api/contests/{id}
GET    /api/contests/{id}/matches
POST   /api/contests/{id}/portfolio
POST   /api/contests/analyze (외부 API consent + key 필요)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.remote import keys as api_keys
from ..auth.dependencies import require_auth
from ..settings_store import (
    get_external_allow_send,
    get_external_default_model,
)
from ..storage.db import get_session
from ..storage.models import Contest, Embedding, Photo, Portfolio, PortfolioItem

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/contests",
    tags=["contests"],
    dependencies=[Depends(require_auth)],
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _CreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    info_text: str | None = None
    themes: list[str] = Field(default_factory=list)


class _UpdateIn(BaseModel):
    name: str | None = None
    info_text: str | None = None
    themes: list[str] | None = None


class _AnalyzeIn(BaseModel):
    info_text: str = Field(min_length=10)


class _PortfolioFromMatchesIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    photo_ids: list[int] = Field(default_factory=list)


def _serialize(c: Contest) -> dict:
    try:
        themes = json.loads(c.themes or "[]")
    except json.JSONDecodeError:
        themes = []
    return {
        "id": c.id,
        "name": c.name,
        "info_text": c.info_text,
        "themes": themes,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


@router.get("")
def list_contests(session: Session = Depends(get_session)) -> list[dict]:
    rows = (
        session.execute(select(Contest).order_by(Contest.updated_at.desc()))
        .scalars()
        .all()
    )
    return [_serialize(c) for c in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_contest(body: _CreateIn, session: Session = Depends(get_session)) -> dict:
    c = Contest(
        name=body.name.strip(),
        info_text=body.info_text,
        themes=json.dumps(body.themes, ensure_ascii=False),
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    return _serialize(c)


@router.get("/{contest_id}")
def get_contest(contest_id: int, session: Session = Depends(get_session)) -> dict:
    c = session.get(Contest, contest_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contest not found")
    return _serialize(c)


@router.put("/{contest_id}")
def update_contest(
    contest_id: int, body: _UpdateIn, session: Session = Depends(get_session)
) -> dict:
    c = session.get(Contest, contest_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contest not found")
    if body.name is not None:
        c.name = body.name.strip()
    if body.info_text is not None:
        c.info_text = body.info_text
    if body.themes is not None:
        c.themes = json.dumps(body.themes, ensure_ascii=False)
    session.commit()
    session.refresh(c)
    return _serialize(c)


@router.delete("/{contest_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contest(contest_id: int, session: Session = Depends(get_session)) -> None:
    n = session.execute(
        Contest.__table__.delete().where(Contest.id == contest_id)
    ).rowcount
    session.commit()
    if not n:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contest not found")


@router.get("/{contest_id}/matches")
def get_matches(
    contest_id: int,
    top_n: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> dict:
    """테마별 CLIP cosine similarity로 사진 매칭. 저장된 임베딩만 사용."""
    c = session.get(Contest, contest_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contest not found")
    try:
        themes: list[str] = json.loads(c.themes or "[]")
    except json.JSONDecodeError:
        themes = []
    if not themes:
        return {"contest": _serialize(c), "matches": [], "note": "no themes"}

    rows = session.execute(
        select(Embedding.photo_id, Embedding.vector).where(
            Embedding.model_id == "clip", Embedding.model_version == "vit-l-14"
        )
    ).all()
    if not rows:
        return {"contest": _serialize(c), "matches": [], "note": "no embeddings"}

    photo_ids = np.array([r[0] for r in rows])
    matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])

    from ..evaluator.worker import default_embed_model

    embed = default_embed_model()
    matches_by_theme: list[dict] = []
    for theme in themes:
        theme_str = theme.strip()
        if not theme_str:
            continue
        text_vec = np.frombuffer(embed.embed_text(theme_str).vector, dtype=np.float32)
        sims = matrix @ text_vec
        top_idx = np.argsort(-sims)[:top_n]
        # photo 메타 hydrate
        ids = [int(photo_ids[i]) for i in top_idx]
        sim_vals = [float(sims[i]) for i in top_idx]
        photos_by_id = {
            p.id: p
            for p in session.execute(select(Photo).where(Photo.id.in_(ids))).scalars().all()
        }
        matches_by_theme.append(
            {
                "theme": theme_str,
                "photos": [
                    {
                        "photo_id": pid,
                        "similarity": sv,
                        "taken_at": photos_by_id[pid].taken_at.isoformat()
                        if pid in photos_by_id and photos_by_id[pid].taken_at
                        else None,
                        "camera_model": photos_by_id[pid].camera_model
                        if pid in photos_by_id
                        else None,
                        "thumb_url": f"/api/photos/{pid}/thumb",
                    }
                    for pid, sv in zip(ids, sim_vals, strict=True)
                    if pid in photos_by_id
                ],
            }
        )

    return {"contest": _serialize(c), "matches": matches_by_theme}


@router.post("/analyze")
def analyze(body: _AnalyzeIn, session: Session = Depends(get_session)) -> dict:
    """info_text → Claude로 5–10개 테마 추출."""
    if not get_external_allow_send(session):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "external API send is disabled — enable in Settings",
        )
    api_key = api_keys.get("anthropic")
    if not api_key:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Anthropic API key not set"
        )

    from anthropic import Anthropic

    model = get_external_default_model(session)
    client = Anthropic(api_key=api_key)
    prompt = (
        "From the following photography contest information, extract 5–10 "
        "distinct photographic themes as short ENGLISH phrases (3–8 words each), "
        "one per line. These will be used for CLIP semantic search across a "
        "photo library, so favor visually concrete themes (subjects, moods, "
        "scenes) over abstract concepts. Output ONLY the themes, no preamble, "
        "no numbering, no markdown bullets.\n\n"
        f"Contest information:\n{body.info_text}"
    )
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("contest analyze failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"AI call failed: {exc}"
        ) from exc

    text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
    themes: list[str] = []
    for line in text.splitlines():
        s = line.strip().lstrip("-*•·").strip()
        if 2 <= len(s.split()) <= 12 and len(s) <= 200:
            themes.append(s)
    themes = themes[:12]
    return {
        "themes": themes,
        "model": f"claude:{model}",
        "tokens_in": getattr(msg.usage, "input_tokens", None),
        "tokens_out": getattr(msg.usage, "output_tokens", None),
    }


@router.post("/{contest_id}/portfolio", status_code=status.HTTP_201_CREATED)
def make_portfolio(
    contest_id: int,
    body: _PortfolioFromMatchesIn,
    session: Session = Depends(get_session),
) -> dict:
    """선택한 매칭 사진들을 새 포트폴리오로 묶어 저장."""
    c = session.get(Contest, contest_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contest not found")

    p = Portfolio(name=body.name.strip(), description=f"공모전: {c.name}")
    session.add(p)
    session.flush()

    if body.photo_ids:
        valid = set(
            r[0]
            for r in session.execute(
                select(Photo.id).where(Photo.id.in_(body.photo_ids))
            )
        )
        for pid in body.photo_ids:
            if pid in valid:
                session.add(
                    PortfolioItem(
                        portfolio_id=p.id,
                        photo_id=pid,
                        source="ai_suggested",
                        confirmed=1,
                    )
                )
    session.commit()
    session.refresh(p)
    return {"portfolio_id": p.id, "name": p.name}
