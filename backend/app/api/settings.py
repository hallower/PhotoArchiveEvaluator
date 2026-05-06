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
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..storage.models import PhotoPath

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
    library_min_score: float | None = Field(default=None, ge=0.0, le=5.0)
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
    local_counts: dict[str, int] = {}
    dsm_counts: dict[str, int] = {}
    for nas_id, path in rows:
        parent = _parent_dir(nas_id, path)
        if not parent:
            continue
        if nas_id == "local":
            local_counts[parent] = local_counts.get(parent, 0) + 1
        elif nas_id.startswith("dsm:"):
            dsm_counts[parent] = dsm_counts.get(parent, 0) + 1
    return {
        "local": sorted(
            [{"path": p, "photo_count": c} for p, c in local_counts.items()],
            key=lambda x: x["path"],
        ),
        "dsm": sorted(
            [{"path": p, "photo_count": c} for p, c in dsm_counts.items()],
            key=lambda x: x["path"],
        ),
    }


def _parent_dir(nas_id: str, path: str) -> str:
    """경로의 부모 디렉터리. local은 OS-aware, DSM은 POSIX."""
    if nas_id == "local":
        return os.path.dirname(path) or path
    return posixpath.dirname(path) or path


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
    rows = session.execute(select(PhotoPath.nas_id, PhotoPath.path)).all()
    local_set: set[str] = set()
    dsm_set: set[str] = set()
    for nas_id, path in rows:
        parent = _parent_dir(nas_id, path)
        if not parent:
            continue
        if nas_id == "local":
            local_set.add(parent)
        elif nas_id.startswith("dsm:"):
            dsm_set.add(parent)

    local_paths = _topmost(local_set, ("\\", "/"))
    dsm_paths = _topmost(dsm_set, ("/",))

    if not local_paths and not dsm_paths:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "no scanned photos in DB — start with NAS/local 스캔 button"
        )

    # 로컬 스캐너는 경로별 스레드 1개. NAS는 동일 세션 내 순차 처리(부하 보호).
    started = {"local": 0, "dsm": 0}

    for raw in local_paths:
        p = Path(raw).resolve()
        if not p.is_dir():
            continue
        scanner = LocalScanner(SessionLocal)
        threading.Thread(
            target=scanner.scan,
            args=(p,),
            daemon=True,
            name="scan-local-saved",
        ).start()
        started["local"] += 1

    if dsm_paths:
        config = load_config(session)
        password = load_password(config.username) if config else None
        if config and password:
            device_id = load_device_id(config.username)

            def _run_dsm_chain(paths: list[str]) -> None:
                # 단일 세션으로 모든 NAS 폴더 순차 스캔 — 매 폴더마다 새 로그인하지 않게
                scanner = DSMScanner(SessionLocal, config, password, device_id=device_id)
                for path in paths:
                    try:
                        scanner.scan(path)
                    except Exception:  # noqa: BLE001
                        pass

            threading.Thread(
                target=_run_dsm_chain,
                args=(dsm_paths,),
                daemon=True,
                name="scan-dsm-saved",
            ).start()
            started["dsm"] = len(dsm_paths)

    return {"queued": True, "started": started}
