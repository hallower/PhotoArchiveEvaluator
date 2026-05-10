"""앱 설정 API.

GET  /api/settings — 모든 사용자 조정 가능 설정 조회 (DB의 settings 테이블 + 기본값)
PUT  /api/settings — 부분 갱신
POST /api/settings/scan-saved — 저장된 로컬+NAS 경로 모두 스캔
"""

from __future__ import annotations

import os
import posixpath
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..config import settings as app_settings
from ..storage.models import Photo, PhotoPath

from ..auth.dependencies import require_auth
from ..evaluator.rescore import rescore_prompt
from ..nas.credentials import load_config, load_device_id, load_password
from ..scanner.dsm import DSMScanner
from ..scanner.local import LocalScanner
from ..ai.remote import keys as api_keys
from ..settings_store import (
    DEFAULT_ADVANCED_PROMPT,
    DEFAULT_EVAL_PROMPT,
    DEFAULT_EXTERNAL_MODEL,
    DEFAULT_MAX_WORKERS,
    DEFAULT_MIN_SCORE,
    EVAL_PROMPT,
    MAX_ALLOWED_WORKERS,
    SCAN_DSM_PATHS,
    SCAN_LOCAL_PATHS,
    get_eval_prompt,
    get_external_allow_send,
    get_external_default_model,
    get_external_strip_exif,
    get_max_workers,
    get_min_score,
    get_paths_list,
    set_external_allow_send,
    set_external_default_model,
    set_external_strip_exif,
    set_max_workers,
    set_min_score,
    set_paths_list,
    set_value,
)
from ..storage.db import SessionLocal, get_session

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_auth)],
)


class _SettingsUpdate(BaseModel):
    eval_prompt: str | None = None
    library_min_score: float | None = Field(default=None, ge=0.0, le=100.0)
    scan_local_paths: list[str] | None = None
    scan_dsm_paths: list[str] | None = None
    eval_max_workers: int | None = Field(default=None, ge=1, le=MAX_ALLOWED_WORKERS)
    external_allow_send: bool | None = None
    external_strip_exif: bool | None = None
    external_default_model: str | None = None


class _ApiKeyIn(BaseModel):
    provider: str  # 'anthropic' | 'openai' | 'google'
    api_key: str


@router.get("")
def get_settings(session: Session = Depends(get_session)) -> dict:
    return {
        "eval_prompt": get_eval_prompt(session),
        "default_eval_prompt": DEFAULT_EVAL_PROMPT,
        "library_min_score": get_min_score(session),
        "default_library_min_score": DEFAULT_MIN_SCORE,
        "scan_local_paths": get_paths_list(session, SCAN_LOCAL_PATHS),
        "scan_dsm_paths": get_paths_list(session, SCAN_DSM_PATHS),
        "eval_max_workers": get_max_workers(session),
        "default_eval_max_workers": DEFAULT_MAX_WORKERS,
        "max_allowed_workers": MAX_ALLOWED_WORKERS,
        "external_allow_send": get_external_allow_send(session),
        "external_strip_exif": get_external_strip_exif(session),
        "external_default_model": get_external_default_model(session),
        "default_external_model": DEFAULT_EXTERNAL_MODEL,
        "default_advanced_prompt": DEFAULT_ADVANCED_PROMPT,
        "configured_api_providers": api_keys.configured_providers(),
    }


@router.put("")
def put_settings(
    body: _SettingsUpdate,
    session: Session = Depends(get_session),
) -> dict:
    prompt_changed = False
    if body.eval_prompt is not None:
        text = body.eval_prompt.strip() or DEFAULT_EVAL_PROMPT
        if text != get_eval_prompt(session):
            set_value(session, EVAL_PROMPT, text)
            prompt_changed = True

    if body.library_min_score is not None:
        set_min_score(session, body.library_min_score)

    if body.scan_local_paths is not None:
        set_paths_list(session, SCAN_LOCAL_PATHS, body.scan_local_paths)

    if body.scan_dsm_paths is not None:
        set_paths_list(session, SCAN_DSM_PATHS, body.scan_dsm_paths)

    if body.eval_max_workers is not None:
        set_max_workers(session, body.eval_max_workers)

    if body.external_allow_send is not None:
        set_external_allow_send(session, body.external_allow_send)

    if body.external_strip_exif is not None:
        set_external_strip_exif(session, body.external_strip_exif)

    if body.external_default_model is not None:
        set_external_default_model(session, body.external_default_model)

    # prompt가 바뀌었으면 백그라운드 재평가 큐
    if prompt_changed:
        threading.Thread(
            target=rescore_prompt,
            args=(SessionLocal,),
            daemon=True,
            name="prompt-rescore",
        ).start()

    return {"ok": True, "prompt_rescored": prompt_changed}


@router.get("/scanned-paths")
def get_scanned_paths(session: Session = Depends(get_session)) -> dict:
    """스캔된 사진의 부모 폴더 목록 (DB photo_paths에서 자동 도출).

    사용자가 입력한 폴더가 아닌, **실제로 사진이 등록된** 모든 부모 폴더를 보여준다.
    예: /photo/A/B/x.jpg, /photo/A/C/y.jpg → ["/photo/A/B", "/photo/A/C"]
    """
    rows = session.execute(select(PhotoPath.nas_id, PhotoPath.path)).all()
    local_counts: dict[tuple[str, str], int] = {}
    dsm_counts: dict[tuple[str, str], int] = {}
    for nas_id, path in rows:
        parent = _parent_dir(nas_id, path)
        if not parent:
            continue
        key = (nas_id, parent)
        if nas_id == "local":
            local_counts[key] = local_counts.get(key, 0) + 1
        elif nas_id.startswith("dsm:"):
            dsm_counts[key] = dsm_counts.get(key, 0) + 1
    return {
        "local": sorted(
            [
                {"nas_id": nid, "path": p, "photo_count": c}
                for (nid, p), c in local_counts.items()
            ],
            key=lambda x: x["path"],
        ),
        "dsm": sorted(
            [
                {"nas_id": nid, "path": p, "photo_count": c}
                for (nid, p), c in dsm_counts.items()
            ],
            key=lambda x: x["path"],
        ),
    }


def _parent_dir(nas_id: str, path: str) -> str:
    """경로의 부모 디렉터리. local은 OS-aware, DSM은 POSIX."""
    if nas_id == "local":
        return os.path.dirname(path) or path
    return posixpath.dirname(path) or path


class _DeleteScannedFolderIn(BaseModel):
    nas_id: str
    path: str


@router.delete("/scanned-paths")
def delete_scanned_folder(
    body: _DeleteScannedFolderIn,
    session: Session = Depends(get_session),
) -> dict:
    """스캔된 폴더의 사진을 라이브러리에서 일괄 제거.

    - photo_paths 행 중 nas_id가 일치하고 경로가 폴더의 직속 자손인 행을 모두 삭제.
    - 결과적으로 모든 path를 잃은 photo는 함께 삭제(평가/임베딩/태그/포트폴리오 cascade).
    - **원본 파일(로컬·NAS)은 보존**한다 — 사용자 정책.
    """
    folder = body.path.rstrip("/").rstrip("\\")
    if not folder:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty folder path")

    seps: tuple[str, ...] = ("\\", "/") if body.nas_id == "local" else ("/",)
    like_filters = [PhotoPath.path.like(folder + sep + "%") for sep in seps]

    target_photo_ids = [
        pid
        for (pid,) in session.execute(
            select(PhotoPath.photo_id).where(
                PhotoPath.nas_id == body.nas_id,
                or_(*like_filters),
            )
        ).all()
    ]

    deleted_paths = (
        session.execute(
            delete(PhotoPath).where(
                PhotoPath.nas_id == body.nas_id,
                or_(*like_filters),
            )
        ).rowcount
        or 0
    )

    orphan_ids: list[int] = []
    if target_photo_ids:
        orphan_ids = [
            pid
            for (pid,) in session.execute(
                select(Photo.id)
                .outerjoin(PhotoPath, PhotoPath.photo_id == Photo.id)
                .where(Photo.id.in_(set(target_photo_ids)))
                .group_by(Photo.id)
                .having(func.count(PhotoPath.id) == 0)
            ).all()
        ]

    if orphan_ids:
        session.execute(Photo.__table__.delete().where(Photo.id.in_(orphan_ids)))
    session.commit()

    # 썸네일 캐시 정리 (best-effort)
    for pid in orphan_ids:
        for size in (200, 400, 800):
            cache = app_settings.thumb_dir / f"{pid}_{size}.jpg"
            if cache.exists():
                try:
                    cache.unlink()
                except OSError:
                    pass

    return {
        "deleted_paths": int(deleted_paths),
        "deleted_photos": len(orphan_ids),
        "folder": folder,
        "nas_id": body.nas_id,
    }


def _topmost(paths: set[str], sep_chars: tuple[str, ...]) -> list[str]:
    """다른 path의 조상이 되는 path만 남김 (descendant 제거)."""
    sorted_paths = sorted(paths)
    out: list[str] = []
    for p in sorted_paths:
        is_descendant = any(
            p.startswith(r + s) for r in out for s in sep_chars
        )
        if not is_descendant:
            out.append(p)
    return out


@router.put("/api-keys", status_code=status.HTTP_204_NO_CONTENT)
def put_api_key(body: _ApiKeyIn) -> None:
    if body.provider not in api_keys.KNOWN_PROVIDERS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"unknown provider; expected one of {api_keys.KNOWN_PROVIDERS}",
        )
    if not body.api_key.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty key")
    api_keys.set_key(body.provider, body.api_key.strip())


@router.delete("/api-keys/{provider}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_key(provider: str) -> None:
    api_keys.delete(provider)


@router.post("/scan-saved", status_code=status.HTTP_202_ACCEPTED)
def scan_saved(session: Session = Depends(get_session)) -> dict:
    """스캔된 사진의 부모 폴더(DB)를 모두 재스캔. topmost만 walk해 중복 회피."""
    from ..scanner.dispatch import scan_saved_paths

    result = scan_saved_paths(SessionLocal)
    if not result["local_paths"] and not result["dsm_paths"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "no scanned photos in DB — start with NAS/local 스캔 button",
        )
    return {"queued": True, "started": result["started"]}
