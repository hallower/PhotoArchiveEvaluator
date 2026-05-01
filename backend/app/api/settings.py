"""앱 설정 API.

GET  /api/settings — 모든 사용자 조정 가능 설정 조회 (DB의 settings 테이블 + 기본값)
PUT  /api/settings — 부분 갱신
POST /api/settings/scan-saved — 저장된 로컬+NAS 경로 모두 스캔
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.dependencies import require_auth
from ..evaluator.rescore import rescore_prompt
from ..nas.credentials import load_config, load_device_id, load_password
from ..scanner.dsm import DSMScanner
from ..scanner.local import LocalScanner
from ..settings_store import (
    DEFAULT_EVAL_PROMPT,
    DEFAULT_MAX_WORKERS,
    DEFAULT_MIN_SCORE,
    EVAL_PROMPT,
    MAX_ALLOWED_WORKERS,
    SCAN_DSM_PATHS,
    SCAN_LOCAL_PATHS,
    get_eval_prompt,
    get_max_workers,
    get_min_score,
    get_paths_list,
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

    # prompt가 바뀌었으면 백그라운드 재평가 큐
    if prompt_changed:
        threading.Thread(
            target=rescore_prompt,
            args=(SessionLocal,),
            daemon=True,
            name="prompt-rescore",
        ).start()

    return {"ok": True, "prompt_rescored": prompt_changed}


@router.post("/scan-saved", status_code=status.HTTP_202_ACCEPTED)
def scan_saved(session: Session = Depends(get_session)) -> dict:
    local_paths = get_paths_list(session, SCAN_LOCAL_PATHS)
    dsm_paths = get_paths_list(session, SCAN_DSM_PATHS)

    if not local_paths and not dsm_paths:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "no scan paths saved"
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
