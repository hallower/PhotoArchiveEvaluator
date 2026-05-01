"""연속 평가 워커.

main.py의 lifespan에서 시작되는 daemon 스레드. eval_jobs(state='pending')이 있으면
처리하고, 없으면 짧게 sleep 후 재시도. 사용자가 별도 트리거 없이도 스캔 → 평가가
자연스럽게 흐른다.

다중 워커 가정 시 race-safe 청구가 필요한데, _process_one 내부의 UPDATE WHERE
state='pending'이 그 역할을 한다(worker.py 참조).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from sqlalchemy.orm import Session

from .worker import EvaluatorWorker

log = logging.getLogger(__name__)

IDLE_SLEEP_SEC = 5
START_DELAY_SEC = 20  # 부팅·스키마 안정화 후 시작

_thread: threading.Thread | None = None
_stop = threading.Event()


def start(session_factory: Callable[[], Session]) -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_loop,
        args=(session_factory,),
        daemon=True,
        name="evaluator-loop",
    )
    _thread.start()
    log.info("evaluator loop started")


def stop() -> None:
    _stop.set()


def _loop(session_factory: Callable[[], Session]) -> None:
    if _stop.wait(START_DELAY_SEC):
        return
    worker = EvaluatorWorker(session_factory)
    while not _stop.is_set():
        try:
            with session_factory() as s:
                got = worker._process_one(s)
        except Exception:  # noqa: BLE001
            log.exception("evaluator loop iteration failed")
            got = False
        if not got and _stop.wait(IDLE_SLEEP_SEC):
            break
    # 종료 시 DSM 세션 정리
    try:
        worker._close_dsm()
    except Exception:  # noqa: BLE001
        pass
    log.info("evaluator loop stopped")
