"""사진 라이브러리 API.

GET /api/photos              — 필터/정렬/페이지네이션 목록
GET /api/photos/{id}         — 단일 사진 + 평가 이력
GET /api/photos/{id}/thumb   — 썸네일 (생성·캐싱)
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import Session, aliased

from pydantic import BaseModel, Field

from ..auth.dependencies import require_auth
from ..config import settings
from ..nas.session import open_dsm_client
from ..storage.db import get_session
from ..storage.models import Embedding, Evaluation, Photo, PhotoPath, PhotoTag, Tag, UserScore

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/photos",
    tags=["photos"],
    dependencies=[Depends(require_auth)],
)

THUMB_SIZES = {200, 400, 800}
DEFAULT_THUMB_SIZE = 400

_SORT_OPTIONS = {
    "-taken_at",
    "taken_at",
    "-score",
    "score",
    "-final",
    "final",
    "-prompt",
    "prompt",
    "-id",
    "id",
}


@router.get("")
def list_photos(
    session: Session = Depends(get_session),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    min_score: float | None = Query(4.0),
    max_score: float | None = Query(None),
    camera: str | None = None,
    q: str | None = Query(None, description="키워드: camera/lens/path 부분 일치"),
    sort: str = "-taken_at",
) -> dict:
    if sort not in _SORT_OPTIONS:
        sort = "-taken_at"

    # 미학(aesthetic) 점수: model_id != 'clip-prompt' 의 최신 1행
    aest_sub = (
        select(Evaluation.photo_id, func.max(Evaluation.id).label("eval_id"))
        .where(Evaluation.model_id != "clip-prompt")
        .group_by(Evaluation.photo_id)
        .subquery()
    )
    e = aliased(Evaluation)

    # prompt 점수: model_id == 'clip-prompt' 의 최신 1행
    prompt_sub = (
        select(Evaluation.photo_id, func.max(Evaluation.id).label("eval_id"))
        .where(Evaluation.model_id == "clip-prompt")
        .group_by(Evaluation.photo_id)
        .subquery()
    )
    pe = aliased(Evaluation)

    final_score = func.coalesce(UserScore.score, e.ai_score)

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
            pe.ai_score.label("prompt_score"),
            pe.raw_score.label("prompt_raw"),
            UserScore.score.label("user_score"),
            final_score.label("final_score"),
        )
        .outerjoin(aest_sub, aest_sub.c.photo_id == Photo.id)
        .outerjoin(e, e.id == aest_sub.c.eval_id)
        .outerjoin(prompt_sub, prompt_sub.c.photo_id == Photo.id)
        .outerjoin(pe, pe.id == prompt_sub.c.eval_id)
        .outerjoin(UserScore, UserScore.photo_id == Photo.id)
        .where(Photo.state == "active")
    )

    if min_score is not None:
        # 사용자 점수가 있으면 그것을 임계값 비교에 사용
        base = base.where(final_score >= min_score)
    if max_score is not None:
        base = base.where(final_score <= max_score)
    if camera:
        base = base.where(Photo.camera_model == camera)
    if q:
        # 키워드: camera_model / lens_model / 사진 경로(photo_paths) 부분 일치 (OR)
        like = f"%{q}%"
        path_subq = select(PhotoPath.photo_id).where(PhotoPath.path.like(like))
        base = base.where(
            (Photo.camera_model.like(like))
            | (Photo.lens_model.like(like))
            | (Photo.id.in_(path_subq))
        )

    sort_col = {
        "-taken_at": desc(Photo.taken_at),
        "taken_at": asc(Photo.taken_at),
        "-score": desc(e.ai_score),
        "score": asc(e.ai_score),
        "-final": desc(final_score),
        "final": asc(final_score),
        "-prompt": desc(pe.ai_score),
        "prompt": asc(pe.ai_score),
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
            "prompt_score": r.prompt_score,
            "prompt_raw": r.prompt_raw,
            "user_score": r.user_score,
            "final_score": r.final_score,
            "thumb_url": f"/api/photos/{r.id}/thumb",
        }
        for r in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/search")
def semantic_search(
    q: str,
    limit: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> dict:
    """텍스트 쿼리 → CLIP 텍스트 임베딩 → 저장된 이미지 임베딩과 cosine similarity.

    저장된 임베딩을 메모리에 로드해 단일 matmul로 점수 계산. 137장 ~1ms,
    1만 장 ~80ms. 100K+에서는 sqlite-vec / Chroma 등 ANN 인덱스 검토.
    """
    query = q.strip()
    if not query:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty query")

    rows = session.execute(
        select(Embedding.photo_id, Embedding.vector).where(
            Embedding.model_id == "clip",
            Embedding.model_version == "vit-l-14",
        )
    ).all()
    if not rows:
        return {"items": [], "total": 0, "query": query}

    # 텍스트 임베딩 (CLIP — default_embed_model 캐시 1회 로드)
    from ..evaluator.worker import default_embed_model
    text_vec = np.frombuffer(default_embed_model().embed_text(query).vector, dtype=np.float32)

    photo_ids = np.array([r[0] for r in rows])
    matrix = np.stack(
        [np.frombuffer(r[1], dtype=np.float32) for r in rows]
    )  # (N, 768)
    sims = matrix @ text_vec  # (N,)
    top_idx = np.argsort(-sims)[:limit]

    top_ids = [int(photo_ids[i]) for i in top_idx]
    top_sims = [float(sims[i]) for i in top_idx]

    # 사진 정보 hydrate (id 순 보존)
    photos = session.execute(select(Photo).where(Photo.id.in_(top_ids))).scalars().all()
    by_id = {p.id: p for p in photos}

    items: list[dict] = []
    for pid, sim in zip(top_ids, top_sims, strict=True):
        p = by_id.get(pid)
        if p is None:
            continue
        items.append(
            {
                "id": p.id,
                "similarity": sim,
                "taken_at": p.taken_at.isoformat() if p.taken_at else None,
                "camera_model": p.camera_model,
                "width": p.width,
                "height": p.height,
                "thumb_url": f"/api/photos/{p.id}/thumb",
            }
        )

    return {"items": items, "total": len(items), "query": query}


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
            select(PhotoPath.id, PhotoPath.path, PhotoPath.nas_id, PhotoPath.last_seen_at, PhotoPath.size_bytes)
            .where(PhotoPath.photo_id == photo_id)
            .order_by(PhotoPath.id)
        ).all()
    )

    user_score = session.execute(
        select(UserScore).where(UserScore.photo_id == photo_id)
    ).scalar_one_or_none()

    tag_rows = session.execute(
        select(Tag.name, PhotoTag.confidence)
        .join(PhotoTag, PhotoTag.tag_id == Tag.id)
        .where(PhotoTag.photo_id == photo_id)
        .order_by(PhotoTag.confidence.desc())
    ).all()

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
            {
                "id": p.id,
                "nas_id": p.nas_id,
                "path": p.path,
                "size_bytes": p.size_bytes,
                "last_seen_at": p.last_seen_at.isoformat(),
            }
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
        "user_score": user_score.score if user_score else None,
        "user_note": user_score.note if user_score else None,
        "tags": [{"name": n, "confidence": c} for n, c in tag_rows],
        "thumb_url": f"/api/photos/{photo.id}/thumb",
    }


class _UserScoreIn(BaseModel):
    score: float = Field(ge=1.0, le=5.0)
    note: str | None = None


class _BulkDeleteIn(BaseModel):
    ids: list[int] = Field(default_factory=list)
    delete_local_files: bool = False  # 로컬 파일 실제 삭제 여부 (NAS는 무시)


@router.delete("", status_code=status.HTTP_200_OK)
def bulk_delete(body: _BulkDeleteIn, session: Session = Depends(get_session)) -> dict:
    """photos를 다중 삭제. 기본은 DB 레코드만 (cascade로 paths/eval/embedding 동반).

    delete_local_files=True면 로컬 디스크 원본도 삭제 (DSM 경로는 안전상 항상 무시).
    """
    if not body.ids:
        return {"deleted": 0, "files_deleted": 0}

    files_deleted = 0
    files_failed = 0
    if body.delete_local_files:
        rows = session.execute(
            select(PhotoPath.path)
            .where(
                PhotoPath.photo_id.in_(body.ids),
                PhotoPath.nas_id == "local",
            )
        ).all()
        for (path_str,) in rows:
            try:
                p = Path(path_str)
                if p.is_file():
                    p.unlink()
                    files_deleted += 1
            except OSError as exc:
                log.warning("file delete failed %s: %s", path_str, exc)
                files_failed += 1

    deleted = session.execute(
        Photo.__table__.delete().where(Photo.id.in_(body.ids))
    ).rowcount or 0
    session.commit()

    # 썸네일 캐시도 정리 (best-effort)
    for pid in body.ids:
        for size in (200, 400, 800):
            cache = settings.thumb_dir / f"{pid}_{size}.jpg"
            if cache.exists():
                try:
                    cache.unlink()
                except OSError:
                    pass

    return {
        "deleted": int(deleted),
        "files_deleted": files_deleted,
        "files_failed": files_failed,
    }


class _PathDeleteIn(BaseModel):
    path_ids: list[int] = Field(default_factory=list)
    delete_local_files: bool = False


@router.delete("/{photo_id}/paths", status_code=status.HTTP_200_OK)
def delete_paths(
    photo_id: int,
    body: _PathDeleteIn,
    session: Session = Depends(get_session),
) -> dict:
    """특정 photo_paths 행을 삭제. delete_local_files=True면 로컬 파일도 삭제.

    photo의 모든 path가 사라지면 photo.state='missing'으로 표시.
    """
    if not body.path_ids:
        return {"deleted": 0, "files_deleted": 0}

    rows = session.execute(
        select(PhotoPath)
        .where(PhotoPath.photo_id == photo_id, PhotoPath.id.in_(body.path_ids))
    ).scalars().all()

    files_deleted = 0
    if body.delete_local_files:
        for pp in rows:
            if pp.nas_id != "local":
                continue
            try:
                p = Path(pp.path)
                if p.is_file():
                    p.unlink()
                    files_deleted += 1
            except OSError as exc:
                log.warning("file delete failed %s: %s", pp.path, exc)

    for pp in rows:
        session.delete(pp)
    session.commit()

    # photo의 남은 path 수 확인
    remaining = session.execute(
        select(func.count(PhotoPath.id)).where(PhotoPath.photo_id == photo_id)
    ).scalar() or 0
    if remaining == 0:
        photo = session.get(Photo, photo_id)
        if photo:
            photo.state = "missing"
            session.commit()

    return {
        "deleted": len(rows),
        "files_deleted": files_deleted,
        "remaining_paths": int(remaining),
    }


@router.put("/{photo_id}/score", status_code=status.HTTP_204_NO_CONTENT)
def set_user_score(
    photo_id: int,
    body: _UserScoreIn,
    session: Session = Depends(get_session),
) -> None:
    photo = session.get(Photo, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo not found")
    existing = session.execute(
        select(UserScore).where(UserScore.photo_id == photo_id)
    ).scalar_one_or_none()
    if existing:
        existing.score = body.score
        existing.note = body.note
    else:
        session.add(UserScore(photo_id=photo_id, score=body.score, note=body.note))
    session.commit()


@router.delete("/{photo_id}/score", status_code=status.HTTP_204_NO_CONTENT)
def clear_user_score(photo_id: int, session: Session = Depends(get_session)) -> None:
    session.execute(
        UserScore.__table__.delete().where(UserScore.photo_id == photo_id)
    )
    session.commit()


@router.get("/{photo_id}/similar")
def find_similar(
    photo_id: int,
    limit: int = Query(20, ge=1, le=100),
    max_distance: int = Query(12, ge=1, le=32, description="Hamming 거리 상한 (0=동일, 64=완전 다름)"),
    session: Session = Depends(get_session),
) -> dict:
    """pHash 기반 유사 사진 (Hamming distance 오름차순)."""
    target = session.get(Photo, photo_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "photo not found")
    if not target.phash:
        return {"items": [], "total": 0, "note": "no phash for this photo"}

    target_int = int(target.phash, 16)
    rows = session.execute(
        select(Photo.id, Photo.phash, Photo.taken_at, Photo.camera_model)
        .where(Photo.phash.is_not(None), Photo.id != photo_id)
    ).all()
    scored: list[tuple[int, int, str | None, str | None]] = []
    for pid, phash, taken_at, camera in rows:
        try:
            dist = bin(int(phash, 16) ^ target_int).count("1")
        except (TypeError, ValueError):
            continue
        if dist <= max_distance:
            scored.append((pid, dist, taken_at, camera))
    scored.sort(key=lambda x: x[1])
    items = [
        {
            "id": pid,
            "hamming": dist,
            "taken_at": ta.isoformat() if ta else None,
            "camera_model": cam,
            "thumb_url": f"/api/photos/{pid}/thumb",
        }
        for pid, dist, ta, cam in scored[:limit]
    ]
    return {"items": items, "total": len(items), "max_distance": max_distance}


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
        try:
            src = _open_source_image(session, pp)
        except FileNotFoundError as exc:
            raise HTTPException(status.HTTP_410_GONE, "source file missing") from exc
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with src as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                img.thumbnail((size, size), Image.LANCZOS)
                img.save(cache_path, "JPEG", quality=82, optimize=True)
        except (UnidentifiedImageError, OSError) as exc:
            log.warning("thumb generation failed for %d: %s", photo_id, exc)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "thumb generation failed") from exc
    return FileResponse(cache_path, media_type="image/jpeg")


def _open_source_image(session: Session, pp: PhotoPath):
    """원본 사진 바이트를 PIL Image로 연다 (로컬 / DSM 자동 분기)."""
    if pp.nas_id == "local":
        path = Path(pp.path)
        if not path.exists():
            raise FileNotFoundError(str(path))
        return Image.open(path)
    if pp.nas_id.startswith("dsm:"):
        with open_dsm_client(session) as client:
            data = client.download(pp.path)
        return Image.open(io.BytesIO(data))
    raise FileNotFoundError(f"unsupported nas_id: {pp.nas_id}")
