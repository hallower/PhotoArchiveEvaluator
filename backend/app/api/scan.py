"""스캔 API.

Phase 1: 로컬 폴더만. DSM은 추후 별도 엔드포인트로 추가.
스캔은 별도 데몬 스레드에서 진행. 진행 상태는 GET /api/scan/jobs/{id}로 조회.
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.dependencies import require_auth
from ..scanner.local import LocalScanner
from ..storage.db import SessionLocal, get_session
from ..storage.models import ScanJob

router = APIRouter(
    prefix="/api/scan",
    tags=["scan"],
    dependencies=[Depends(require_auth)],
)


class _LocalScanRequest(BaseModel):
    folder: str


@router.post("/local", status_code=status.HTTP_202_ACCEPTED)
def scan_local(req: _LocalScanRequest) -> dict:
    p = Path(req.folder).resolve()
    if not p.exists() or not p.is_dir():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "folder not found or not a directory")

    scanner = LocalScanner(SessionLocal)
    thread = threading.Thread(target=scanner.scan, args=(p,), daemon=True, name="scan-local")
    thread.start()
    return {"folder": str(p), "queued": True}


@router.get("/jobs/{job_id}")
def get_scan_job(job_id: int, session: Session = Depends(get_session)) -> dict:
    job = session.get(ScanJob, job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scan job not found")
    return _serialize_job(job)


@router.get("/jobs")
def list_scan_jobs(session: Session = Depends(get_session), limit: int = 20) -> list[dict]:
    rows = session.execute(
        # 최신순
        ScanJob.__table__.select().order_by(ScanJob.id.desc()).limit(limit)
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        # row는 RowMapping. ORM으로 다시 가져오는 비용 회피.
        out.append({
            "id": row.id,
            "state": row.state,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "discovered": row.discovered,
            "new_photos": row.new_photos,
            "changed": row.changed,
            "skipped": row.skipped,
            "error": row.error,
        })
    return out


def _serialize_job(job: ScanJob) -> dict:
    return {
        "id": job.id,
        "state": job.state,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "discovered": job.discovered,
        "new_photos": job.new_photos,
        "changed": job.changed,
        "skipped": job.skipped,
        "error": job.error,
        "folders": job.folders,
    }
