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

from sqlalchemy import select

from ..auth.dependencies import require_auth
from ..nas.credentials import load_config, load_device_id, load_password
from ..scanner.dispatch import start_scans_for_job
from ..scanner.dsm import DSMScanner
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


class _DSMScanRequest(BaseModel):
    folder: str  # DSM 절대 경로 (예: /photo/My Pictures-2023)


@router.post("/local", status_code=status.HTTP_202_ACCEPTED)
def scan_local(req: _LocalScanRequest) -> dict:
    p = Path(req.folder).resolve()
    if not p.exists() or not p.is_dir():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "folder not found or not a directory")

    scanner = LocalScanner(SessionLocal)
    thread = threading.Thread(target=scanner.scan, args=(p,), daemon=True, name="scan-local")
    thread.start()
    return {"folder": str(p), "queued": True}


@router.post("/dsm", status_code=status.HTTP_202_ACCEPTED)
def scan_dsm(req: _DSMScanRequest, session: Session = Depends(get_session)) -> dict:
    config = load_config(session)
    if config is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "NAS not configured")
    password = load_password(config.username)
    if not password:
        raise HTTPException(status.HTTP_409_CONFLICT, "NAS password missing")
    device_id = load_device_id(config.username)

    scanner = DSMScanner(SessionLocal, config, password, device_id=device_id)
    thread = threading.Thread(
        target=scanner.scan,
        args=(req.folder,),
        daemon=True,
        name="scan-dsm",
    )
    thread.start()
    return {"folder": req.folder, "queued": True, "nas_id": scanner.nas_id}


@router.get("/jobs/{job_id}")
def get_scan_job(job_id: int, session: Session = Depends(get_session)) -> dict:
    job = session.get(ScanJob, job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scan job not found")
    return _serialize_job(job)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scan_job(job_id: int, session: Session = Depends(get_session)) -> None:
    n = session.execute(
        ScanJob.__table__.delete().where(ScanJob.id == job_id)
    ).rowcount
    session.commit()
    if not n:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scan job not found")


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry_scan_job(job_id: int, session: Session = Depends(get_session)) -> dict:
    job = session.get(ScanJob, job_id)
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "scan job not found")
    started = start_scans_for_job(SessionLocal, job.folders)
    return {"queued": True, "started": started}


@router.post("/retry-failed", status_code=status.HTTP_202_ACCEPTED)
def retry_failed(session: Session = Depends(get_session)) -> dict:
    """state=failed인 모든 잡을 재시작. 즉시 실행 (사용자 강제 트리거)."""
    rows = session.execute(
        select(ScanJob).where(ScanJob.state == "failed")
    ).scalars().all()
    started = 0
    for job in rows:
        started += start_scans_for_job(SessionLocal, job.folders)
    return {"queued": True, "retried_jobs": len(rows), "started_scans": started}


class _BulkDeleteJobs(BaseModel):
    state: str | None = None  # 'failed', 'done', etc. — None이면 ids 사용
    ids: list[int] | None = None


@router.delete("/jobs", status_code=status.HTTP_200_OK)
def bulk_delete_jobs(body: _BulkDeleteJobs, session: Session = Depends(get_session)) -> dict:
    if body.state is None and not body.ids:
        return {"deleted": 0}
    stmt = ScanJob.__table__.delete()
    if body.ids:
        stmt = stmt.where(ScanJob.id.in_(body.ids))
    if body.state:
        stmt = stmt.where(ScanJob.state == body.state)
    n = session.execute(stmt).rowcount or 0
    session.commit()
    return {"deleted": int(n)}


@router.get("/jobs")
def list_scan_jobs(
    session: Session = Depends(get_session),
    limit: int = 20,
    state: str | None = None,
) -> list[dict]:
    stmt = ScanJob.__table__.select().order_by(ScanJob.id.desc())
    if state:
        stmt = stmt.where(ScanJob.state == state)
    stmt = stmt.limit(limit)
    rows = session.execute(stmt).fetchall()
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
