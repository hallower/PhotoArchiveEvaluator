"""포트폴리오 그룹 API.

GET    /api/portfolios                 — 목록 (사진 수·미리보기 썸네일 id 포함)
POST   /api/portfolios                 — 생성 (이름, 설명, optional photo_ids[])
GET    /api/portfolios/{id}            — 상세 + 사진 목록
PUT    /api/portfolios/{id}            — 메타 갱신 (name, description)
DELETE /api/portfolios/{id}            — 삭제 (cascade로 items 정리)
POST   /api/portfolios/{id}/items      — 사진 다중 추가 (photo_ids[])
DELETE /api/portfolios/{id}/items      — 사진 다중 제거 (photo_ids[])
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.dependencies import require_auth
from ..storage.db import get_session
from ..storage.models import Photo, Portfolio, PortfolioItem

router = APIRouter(
    prefix="/api/portfolios",
    tags=["portfolios"],
    dependencies=[Depends(require_auth)],
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class _CreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    photo_ids: list[int] = Field(default_factory=list)


class _UpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class _ItemsIn(BaseModel):
    photo_ids: list[int] = Field(default_factory=list)


@router.get("")
def list_portfolios(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.execute(
        select(
            Portfolio.id,
            Portfolio.name,
            Portfolio.description,
            Portfolio.created_at,
            Portfolio.updated_at,
            func.count(PortfolioItem.photo_id).label("count"),
        )
        .outerjoin(PortfolioItem, PortfolioItem.portfolio_id == Portfolio.id)
        .group_by(Portfolio.id)
        .order_by(Portfolio.updated_at.desc())
    ).all()

    out: list[dict] = []
    for r in rows:
        # 미리보기로 첫 사진 1장 id
        preview_id = session.execute(
            select(PortfolioItem.photo_id)
            .where(PortfolioItem.portfolio_id == r.id)
            .order_by(PortfolioItem.added_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        out.append(
            {
                "id": r.id,
                "name": r.name,
                "description": r.description,
                "count": int(r.count),
                "preview_photo_id": preview_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
        )
    return out


@router.post("", status_code=status.HTTP_201_CREATED)
def create_portfolio(body: _CreateIn, session: Session = Depends(get_session)) -> dict:
    p = Portfolio(name=body.name.strip(), description=body.description)
    session.add(p)
    session.flush()
    portfolio_id = p.id

    if body.photo_ids:
        _add_items(session, portfolio_id, body.photo_ids)
    session.commit()
    return {"id": portfolio_id}


@router.get("/{portfolio_id}")
def get_portfolio(portfolio_id: int, session: Session = Depends(get_session)) -> dict:
    p = session.get(Portfolio, portfolio_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "portfolio not found")

    items = session.execute(
        select(
            PortfolioItem.photo_id,
            PortfolioItem.added_at,
            PortfolioItem.note,
            Photo.taken_at,
            Photo.camera_model,
        )
        .join(Photo, Photo.id == PortfolioItem.photo_id)
        .where(PortfolioItem.portfolio_id == portfolio_id)
        .order_by(PortfolioItem.added_at.desc())
    ).all()

    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "items": [
            {
                "photo_id": it.photo_id,
                "taken_at": it.taken_at.isoformat() if it.taken_at else None,
                "camera_model": it.camera_model,
                "added_at": it.added_at.isoformat() if it.added_at else None,
                "note": it.note,
                "thumb_url": f"/api/photos/{it.photo_id}/thumb",
            }
            for it in items
        ],
    }


@router.put("/{portfolio_id}")
def update_portfolio(
    portfolio_id: int, body: _UpdateIn, session: Session = Depends(get_session)
) -> dict:
    p = session.get(Portfolio, portfolio_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "portfolio not found")
    if body.name is not None:
        p.name = body.name.strip()
    if body.description is not None:
        p.description = body.description
    session.commit()
    return {"id": p.id}


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portfolio(portfolio_id: int, session: Session = Depends(get_session)) -> None:
    p = session.get(Portfolio, portfolio_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "portfolio not found")
    session.delete(p)
    session.commit()


@router.post("/{portfolio_id}/items")
def add_items(
    portfolio_id: int, body: _ItemsIn, session: Session = Depends(get_session)
) -> dict:
    p = session.get(Portfolio, portfolio_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "portfolio not found")
    added = _add_items(session, portfolio_id, body.photo_ids)
    p.updated_at = _utc_now()
    session.commit()
    return {"added": added}


@router.delete("/{portfolio_id}/items")
def remove_items(
    portfolio_id: int, body: _ItemsIn, session: Session = Depends(get_session)
) -> dict:
    if not body.photo_ids:
        return {"removed": 0}
    n = session.execute(
        PortfolioItem.__table__.delete().where(
            PortfolioItem.portfolio_id == portfolio_id,
            PortfolioItem.photo_id.in_(body.photo_ids),
        )
    ).rowcount or 0
    p = session.get(Portfolio, portfolio_id)
    if p:
        p.updated_at = _utc_now()
    session.commit()
    return {"removed": int(n)}


def _add_items(session: Session, portfolio_id: int, photo_ids: list[int]) -> int:
    if not photo_ids:
        return 0
    # 기존 항목 제외
    existing = set(
        r[0]
        for r in session.execute(
            select(PortfolioItem.photo_id).where(
                PortfolioItem.portfolio_id == portfolio_id,
                PortfolioItem.photo_id.in_(photo_ids),
            )
        )
    )
    # 유효 photo_id만 (중복·존재하지 않는 id 차단)
    valid_ids = set(
        r[0]
        for r in session.execute(select(Photo.id).where(Photo.id.in_(photo_ids)))
    )
    to_add = [pid for pid in photo_ids if pid in valid_ids and pid not in existing]
    for pid in to_add:
        session.add(
            PortfolioItem(
                portfolio_id=portfolio_id,
                photo_id=pid,
                source="manual",
                confirmed=1,
            )
        )
    return len(to_add)
