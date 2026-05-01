"""연속 평가 워커.

main.py의 lifespan에서 시작되는 daemon 스레드 풀. eval_jobs(state='pending')이 있으면
처리하고, 없으면 짧게 sleep 후 재시도.

다중 워커 동시 처리:
- 단일 EvaluatorWorker 인스턴스를 N개 스레드가 공유 (DSM 세션·모델 공유)
- _process_one의 race-safe UPDATE로 잡 청구 충돌 방지
- worker.py의 _gpu_lock으로 GPU forward 직렬화 — 다운로드/DB는 병렬

워커 수는 settings의 eval.max_workers로 조정. 기본 2 (단일 GPU + I/O 오버랩 sweet spot).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from sqlalchemy.orm import Session

from ..settings_store import get_max_workers
from ..storage.db import SessionLocal
from .worker import EvaluatorWorker

log = logging.getLogger(__name__)

IDLE_SLEEP_SEC = 5
START_DELAY_SEC = 20

_threads: list[threading.Thread] = []
_stop = threading.Event()
_worker: EvaluatorWorker | None = None


def start(session_factory: Callable[[], Session]) -> None:
    global _worker
    if _threads and any(t.is_alive() for t in _threads):
        return
    _stop.clear()
    _threads.clear()

    with SessionLocal() as s:
        n = get_max_workers(s)

    _worker = EvaluatorWorker(session_factory)
    for i in range(n):
        t = threading.Thread(
            target=_thread_loop,
            args=(_worker, session_factory),
            daemon=True,
            name=f"eval-worker-{i}",
        )
        t.start()
        _threads.append(t)
    log.info("evaluator loop started: %d worker(s)", n)


def stop() -> None:
    _stop.set()
    if _worker is not None:
        try:
            _worker._close_dsm()
        except Exception:  # noqa: BLE001
            pass
    log.info("evaluator loop stopping")


def _thread_loop(worker: EvaluatorWorker, session_factory: Callable[[], Session]) -> None:
    if _stop.wait(START_DELAY_SEC):
        return
    while not _stop.is_set():
        try:
            with session_factory() as s:
                got = worker._process_one(s)
        except Exception:  # noqa: BLE001
            log.exception("evaluator iteration failed")
            got = False
        if not got and _stop.wait(IDLE_SLEEP_SEC):
            break
