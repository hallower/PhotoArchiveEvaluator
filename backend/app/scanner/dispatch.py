"""스캔 시작 디스패처.

scan_jobs.folders JSON 또는 raw 경로 목록을 받아 적절한 스캐너(local/dsm)를 백그라운드로 시작.
재시도 로직과 자동 스케줄러에서 공통으로 사용한다.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable
from pathlib import Path

from sqlalchemy.orm import Session

from ..nas.credentials import load_config, load_device_id, load_password
from .dsm import DSMScanner
from .local import LocalScanner

log = logging.getLogger(__name__)

_WIN_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def parse_folders(folders_json: str) -> list[dict]:
    """scan_jobs.folders 파싱. 구버전(list[str])과 신버전(list[dict]) 모두 호환."""
    try:
        data = json.loads(folders_json)
    except json.JSONDecodeError:
        return []

    out: list[dict] = []
    if isinstance(data, list):
        for it in data:
            if isinstance(it, str):
                out.append({"kind": _guess_kind(it), "path": it})
            elif isinstance(it, dict) and "path" in it:
                out.append({"kind": it.get("kind") or _guess_kind(it["path"]), "path": it["path"]})
    return out


def _guess_kind(path: str) -> str:
    """경로 문자열만으로 local/dsm 추정.

    규칙:
    1) Windows 드라이브 문자(C:\\, D:\\) → local
    2) 로컬에 실제 존재하는 절대경로 → local
    3) 그 외 (DSM 일반 경로 또는 leading / 빠진 잔재) → dsm
    """
    if _WIN_DRIVE.match(path):
        return "local"
    try:
        p = Path(path)
        if p.is_absolute() and p.is_dir():
            return "local"
    except OSError:
        pass
    return "dsm"


def start_scan(
    session_factory: Callable[[], Session],
    item: dict,
) -> bool:
    """단일 폴더에 대한 스캔을 백그라운드 스레드로 시작. 시작 가능하면 True."""
    kind = item.get("kind") or _guess_kind(item["path"])
    path = item["path"]

    if kind == "local":
        p = Path(path).resolve()
        if not p.is_dir():
            log.warning("skip local scan — not a directory: %s", path)
            return False
        scanner = LocalScanner(session_factory)
        threading.Thread(
            target=scanner.scan, args=(p,), daemon=True, name=f"scan-local-{p.name}"
        ).start()
        return True

    if kind == "dsm":
        with session_factory() as s:
            config = load_config(s)
        if config is None:
            log.warning("skip DSM scan — NAS not configured: %s", path)
            return False
        password = load_password(config.username)
        if not password:
            log.warning("skip DSM scan — password missing: %s", path)
            return False
        device_id = load_device_id(config.username)
        scanner = DSMScanner(session_factory, config, password, device_id=device_id)
        threading.Thread(
            target=scanner.scan, args=(path,), daemon=True, name=f"scan-dsm-{path}"
        ).start()
        return True

    return False


def start_scans_for_job(session_factory: Callable[[], Session], folders_json: str) -> int:
    """이전 ScanJob의 folders를 재현. 시작된 스캔 수 반환."""
    started = 0
    for item in parse_folders(folders_json):
        if start_scan(session_factory, item):
            started += 1
    return started
