"""스캔 자동 재시도 + 주기 재스캔 스케줄러.

별도 의존성(APScheduler 등) 없이 daemon 스레드로 N분마다 깨어나:
  1. state=failed인 스캔을 재시도 (in-memory cooldown으로 무한 루프 방지)
  2. 하루에 한 번, 저장된 폴더 전체를 자동 재스캔 — 새 파일 발견 목적

재스캔은 마지막 완료 스캔으로부터 PAE_AUTO_RESCAN_HOURS(기본 24h)가 지났을 때만 실행한다.
스캐너는 이미 알려진 파일을 skip하므로 재스캔이 다시 다운로드하지 않는다(디렉터리 walk 비용만).
PAE_AUTO_RESCAN_HOURS=0 이면 주기 재스캔 비활성화.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .scanner.dispatch import scan_saved_paths, start_scans_for_job
from .storage.db import SessionLocal
from .storage.models import ScanJob

log = logging.getLogger(__name__)

DEFAULT_INTERVAL_SECONDS = 30 * 60  # 30분
COOLDOWN_SECONDS = 30 * 60  # 같은 잡 재시도 쿨다운

# 주기 재스캔 설정
AUTO_RESCAN_HOURS = int(os.environ.get("PAE_AUTO_RESCAN_HOURS", "24"))  # 0이면 비활성

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
        try:
            maybe_auto_rescan(SessionLocal)
        except Exception:  # noqa: BLE001
            log.exception("auto-rescan error")
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


def maybe_auto_rescan(session_factory: Callable[[], Session]) -> bool:
    """조건이 맞으면 저장된 폴더 전체를 재스캔. 실제로 시작했으면 True.

    조건 (모두 충족해야 실행):
      1. PAE_AUTO_RESCAN_HOURS > 0
      2. 진행 중인 스캔(pending/running)이 없음 — 중복 방지
      3. 마지막 완료(done) 스캔으로부터 AUTO_RESCAN_HOURS 이상 경과
         (한 번도 스캔한 적 없으면 바로 실행 — scan_saved_paths가 빈 DB에선 no-op)
    """
    if AUTO_RESCAN_HOURS <= 0:
        return False

    with session_factory() as s:
        active = s.execute(
            select(func.count())
            .select_from(ScanJob)
            .where(ScanJob.state.in_(("pending", "running")))
        ).scalar_one()
        if active:
            return False
        last_done = s.execute(
            select(ScanJob.finished_at)
            .where(ScanJob.state == "done", ScanJob.finished_at.is_not(None))
            .order_by(ScanJob.finished_at.desc())
            .limit(1)
        ).scalar_one_or_none()

    if last_done is not None:
        if last_done.tzinfo is None:
            last_done = last_done.replace(tzinfo=timezone.utc)
        elapsed_h = (datetime.now(timezone.utc) - last_done).total_seconds() / 3600
        if elapsed_h < AUTO_RESCAN_HOURS:
            return False

    log.info("auto-rescan: triggering scan_saved_paths (last_done=%s)", last_done)
    scan_saved_paths(session_factory)
    return True
