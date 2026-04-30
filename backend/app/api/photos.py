"""사진 라이브러리 API.

GET /api/photos              — 필터/정렬/페이지네이션 목록
GET /api/photos/{id}         — 단일 사진 + 평가 이력
GET /api/photos/{id}/thumb   — 썸네일 (생성·캐싱)
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session, aliased

from ..auth.dependencies import require_auth
from ..config import settings
from ..storage.db import get_session
from ..storage.models import Evaluation, Photo, PhotoPath

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/photos",
    tags=["photos"],
    dependencies=[Depends(require_auth)],
)

THUMB_SIZES = {200, 400, 800}
DEFAULT_THUMB_SIZE = 400

_SORT_OPTIONS = {"-taken_at", "taken_at", "-score", "score", "-id", "id"}


@router.get("")
def list_photos(
    session: Session = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    min_score: float | None = Query(4.0),
    max_score: float | None = Query(None),
    camera: str | None = None,
    sort: str = "-taken_at",
) -> dict:
    if sort not in _SORT_OPTIONS:
        sort = "-taken_at"

    sub = (
        select(Evaluation.photo_id, func.max(Evaluation.id).label("eval_id"))
        .group_by(Evaluation.photo_id)
        .subquery()
    )
    e = aliased(Evaluation)

    base = (
        select(
            Photo.id,
            Photo.sha256,
            Photo.taken_at,
            Photo.camera_make,
            Photo.camera_model,
            Photo.lens_model,
            Photo.iso,
            Photo.aperture,
            Photo.shutter,
            Photo.focal_mm,
            Photo.gps_lat,
            Photo.gps_lon,
            Photo.width,
            Photo.height,
            Photo.size_bytes,
            e.ai_score,
            e.raw_score,
            e.model_id.label("eval_model_id"),
        )
        .outerjoin(sub, sub.c.photo_id == Photo.id)
        .outerjoin(e, e.id == sub.c.eval_id)
        .where(Photo.state == "active")
    )

    if min_score is not None:
        base = base.where(e.ai_score >= min_score)
    if max_score is not None:
        base = base.where(e.ai_score <= max_score)
    if camera:
        base = base.where(Photo.camera_model == camera)

    sort_col = {
        "-taken_at": desc(Photo.taken_at),
        "taken_at": asc(Photo.taken_at),
        "-score": desc(e.ai_score),
        "score": asc(e.ai_score),
        "-id": desc(Photo.id),
        "id": asc(Photo.id),
    }[sort]
    paged = base.order_by(sort_col).offset(offset).limit(limit)

    total = session.execute(select(func.count()).select_from(base.subquery())).scalar() or 0
    rows = session.execute(paged).all()

    items = [
        {
            "id": r.id,
            "sha256": r.sha256,
            "taken_at": r.taken_at.isoformat() if r.taken_at else None,
            "camera_make": r.camera_make,
            "camera_model": r.camera_model,
            "lens_model": r.lens_model,
            "iso": r.iso,
            "aperture": r.aperture,
            "shutter": r.shutter,
            "focal_mm": r.focal_mm,
            "gps_lat": r.gps_lat,
            "gps_lon": r.gps_lon,
            "width": r.width,
            "height": r.height,
            "size_bytes": r.size_bytes,
            "score": r.ai_score,
            "raw_score": r.raw_score,
            "eval_model_id": r.eval_model_id,
            "thumb_url": f"/api/photos/{r.id}/thumb",
        }
        for r in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{photo_id}")
def get_photo(photo_id: int, session: Session = Depends(get_session)) -> dict:
    photo = session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo not found")

    evals = (
        session.execute(
            select(Evaluation)
            .where(Evaluation.photo_id == photo_id)
            .order_by(Evaluation.created_at.desc())
        )
        .scalars()
        .all()
    )
    paths = (
        session.execute(
            select(PhotoPath.path, PhotoPath.nas_id, PhotoPath.last_seen_at)
            .where(PhotoPath.photo_id == photo_id)
        ).all()
    )

    return {
        "id": photo.id,
        "sha256": photo.sha256,
        "phash": photo.phash,
        "size_bytes": photo.size_bytes,
        "width": photo.width,
        "height": photo.height,
        "mime_type": photo.mime_type,
        "taken_at": photo.taken_at.isoformat() if photo.taken_at else None,
        "camera_make": photo.camera_make,
        "camera_model": photo.camera_model,
        "lens_model": photo.lens_model,
        "iso": photo.iso,
        "aperture": photo.aperture,
        "shutter": photo.shutter,
        "focal_mm": photo.focal_mm,
        "gps_lat": photo.gps_lat,
        "gps_lon": photo.gps_lon,
        "state": photo.state,
        "first_seen_at": photo.first_seen_at.isoformat() if photo.first_seen_at else None,
        "last_seen_at": photo.last_seen_at.isoformat() if photo.last_seen_at else None,
        "paths": [
            {"nas_id": p.nas_id, "path": p.path, "last_seen_at": p.last_seen_at.isoformat()}
            for p in paths
        ],
        "evaluations": [
            {
                "id": ev.id,
                "model_id": ev.model_id,
                "model_version": ev.model_version,
                "ai_score": ev.ai_score,
                "raw_score": ev.raw_score,
                "confidence": ev.confidence,
                "caption": ev.caption,
                "created_at": ev.created_at.isoformat(),
            }
            for ev in evals
        ],
        "thumb_url": f"/api/photos/{photo.id}/thumb",
    }


@router.get("/{photo_id}/thumb")
def get_thumb(
    photo_id: int,
    size: int = Query(DEFAULT_THUMB_SIZE),
    session: Session = Depends(get_session),
) -> FileResponse:
    if size not in THUMB_SIZES:
        size = DEFAULT_THUMB_SIZE

    cache_path = settings.thumb_dir / f"{photo_id}_{size}.jpg"
    if not cache_path.exists():
        pp = session.execute(
            select(PhotoPath).where(PhotoPath.photo_id == photo_id).limit(1)
        ).scalar_one_or_none()
        if pp is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "photo path not found")
        src = Path(pp.path)
        if not src.exists():
            raise HTTPException(status.HTTP_410_GONE, "source file missing")
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(src) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                img.thumbnail((size, size), Image.LANCZOS)
                img.save(cache_path, "JPEG", quality=82, optimize=True)
        except (UnidentifiedImageError, OSError) as exc:
            log.warning("thumb generation failed for %d: %s", photo_id, exc)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "thumb generation failed") from exc
    return FileResponse(cache_path, media_type="image/jpeg")
