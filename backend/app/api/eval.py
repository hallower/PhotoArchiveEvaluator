"""평가 큐 API.

GET  /api/eval/queue         — 상태별 카운트(pending/in_progress/done/failed)
POST /api/eval/process       — 백그라운드 워커 1회 트리거
"""

from __future__ import annotations

import threading

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.dependencies import require_auth
from ..evaluator.worker import EvaluatorWorker
from ..storage.db import SessionLocal, get_session
from ..storage.models import EvalJob

router = APIRouter(
    prefix="/api/eval",
    tags=["eval"],
    dependencies=[Depends(require_auth)],
)


class _ProcessRequest(BaseModel):
    max_jobs: int | None = None


@router.get("/queue")
def queue_stats(session: Session = Depends(get_session)) -> dict:
    rows = session.execute(
        select(EvalJob.state, func.count()).group_by(EvalJob.state)
    ).all()
    counts = {state: count for state, count in rows}
    counts.setdefault("pending", 0)
    counts.setdefault("in_progress", 0)
    counts.setdefault("done", 0)
    counts.setdefault("failed", 0)
    return counts


@router.post("/process", status_code=status.HTTP_202_ACCEPTED)
def trigger_process(req: _ProcessRequest) -> dict:
    worker = EvaluatorWorker(SessionLocal)
    thread = threading.Thread(
        target=worker.run,
        kwargs={"max_jobs": req.max_jobs},
        daemon=True,
        name="evaluator",
    )
    thread.start()
    return {"queued": True, "max_jobs": req.max_jobs}
