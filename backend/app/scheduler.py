"""스캔 자동 재시도 스케줄러.

별도 의존성(APScheduler 등) 없이 daemon 스레드로 N분마다 깨어나
state=failed인 스캔을 재시도한다. 무한 루프 방지를 위해 in-memory cooldown 적용 —
같은 ScanJob.id를 너무 자주 재시도하지 않는다.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .scanner.dispatch import start_scans_for_job
from .storage.db import SessionLocal
from .storage.models import ScanJob

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 30 * 60  # 30분
COOLDOWN_SECONDS = 30 * 60  # 같은 잡 재시도 쿨다운

_thread: threading.Thread | None = None
_stop = threading.Event()
_last_retry_at: dict[int, float] = {}  # job_id → unix ts


def start(interval_seconds: int = DEFAULT_INTERVAL_SECONDS) -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_loop,
        args=(interval_seconds,),
        daemon=True,
        name="scan-retry-scheduler",
    )
    _thread.start()
    log.info("retry scheduler started: interval=%ds", interval_seconds)


def stop() -> None:
    _stop.set()


def _loop(interval: int) -> None:
    # 부팅 직후에도 한 번 시도 (지난 세션의 실패를 즉시 따라잡기 위해 짧은 지연 후)
    if _stop.wait(60):
        return
    while True:
        try:
            run_once(SessionLocal)
        except Exception:  # noqa: BLE001
            log.exception("retry scheduler error")
        if _stop.wait(interval):
            return


def run_once(session_factory: Callable[[], Session]) -> int:
    """state=failed 잡들을 쿨다운 안에 들지 않은 것만 재시도. 시작된 스캔 수 반환.

    동일 folders payload는 하나로 dedup해서 재시도. 같은 폴더에 대해 누적된 수십~수백 개의
    실패 잡이 있어도 한 번만 재시도해 NAS 부하를 막는다.
    """
    now = time.time()
    with session_factory() as s:
        rows = s.execute(select(ScanJob).where(ScanJob.state == "failed")).scalars().all()

    # folders payload 기준 dedup — 같은 폴더라면 첫 잡만 사용 (id 큰 순으로 보면 최신)
    by_folders: dict[str, ScanJob] = {}
    for job in sorted(rows, key=lambda j: -j.id):
        if job.folders not in by_folders:
            by_folders[job.folders] = job

    started = 0
    skipped_dup = len(rows) - len(by_folders)
    for job in by_folders.values():
        last = _last_retry_at.get(job.folders, 0)
        if now - last < COOLDOWN_SECONDS:
            continue
        _last_retry_at[job.folders] = now
        started += start_scans_for_job(session_factory, job.folders)
    if started or skipped_dup:
        log.info(
            "auto-retry: started %d scans (failed_jobs=%d, deduped=%d)",
            started, len(rows), skipped_dup,
        )
    return started
