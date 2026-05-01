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
    """state=failed 잡들을 쿨다운 안에 들지 않은 것만 재시도. 시작된 스캔 수 반환."""
    now = time.time()
    started = 0
    with session_factory() as s:
        rows = s.execute(select(ScanJob).where(ScanJob.state == "failed")).scalars().all()
    for job in rows:
        last = _last_retry_at.get(job.id, 0)
        if now - last < COOLDOWN_SECONDS:
            continue
        _last_retry_at[job.id] = now
        started += start_scans_for_job(session_factory, job.folders)
    if started:
        log.info("auto-retry: started %d scans from %d failed jobs", started, len(rows))
    return started
