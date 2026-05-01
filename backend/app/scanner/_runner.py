"""소스 무관 스캔 루프.

LocalWalker / DSMWalker가 walk() + read()만 제공하면 동일 식별·평가 큐 enqueue 로직이 적용된다.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..storage.models import EvalJob, Evaluation, Photo, PhotoPath, ScanJob
from .exif import parse_bytes, parse_phash_bytes
from .walker import FileEntry, Walker

log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_scan(
    session_factory: Callable[[], Session],
    walker: Walker,
    root: str,
) -> int:
    """root 폴더를 walker로 스캔. ScanJob.id 반환. 파일 단위 commit으로 재개 가능."""
    log.info("scan start: nas_id=%s root=%s", walker.nas_id, root)

    # folders는 nas_id 정보를 포함해 retry 시 어느 스캐너로 다시 돌릴지 알 수 있게 한다.
    kind = "dsm" if walker.nas_id.startswith("dsm:") else "local"
    folders_payload = json.dumps([{"kind": kind, "path": str(root)}], ensure_ascii=False)

    with session_factory() as s:
        job = ScanJob(state="running", folders=folders_payload)
        s.add(job)
        s.commit()
        s.refresh(job)
        job_id = job.id

    try:
        with session_factory() as s:
            job = s.get(ScanJob, job_id)
            for entry in walker.walk(root):
                outcome = _process_file(s, walker, entry)
                job.discovered += 1
                if outcome == "new":
                    job.new_photos += 1
                elif outcome == "changed":
                    job.changed += 1
                elif outcome == "skipped":
                    job.skipped += 1
                s.commit()
            job.state = "done"
            job.finished_at = _utc_now()
            s.commit()
    except Exception as exc:
        log.exception("scan failed")
        with session_factory() as s:
            j = s.get(ScanJob, job_id)
            if j:
                j.state = "failed"
                j.error = str(exc)
                j.finished_at = _utc_now()
                s.commit()
        raise

    log.info("scan done: job_id=%d", job_id)
    return job_id


def _process_file(session: Session, walker: Walker, entry: FileEntry) -> str:
    pp = session.execute(
        select(PhotoPath).where(
            PhotoPath.nas_id == walker.nas_id,
            PhotoPath.path == entry.path,
        )
    ).scalar_one_or_none()

    if pp and pp.size_bytes == entry.size_bytes and (
        pp.mtime.replace(tzinfo=timezone.utc) == entry.mtime
    ):
        pp.last_seen_at = _utc_now()
        if pp.photo:
            pp.photo.last_seen_at = _utc_now()
            if pp.photo.state == "missing":
                pp.photo.state = "active"
        return "skipped"

    try:
        content = walker.read(entry.path)
    except Exception as exc:  # noqa: BLE001
        log.warning("read failed %s: %s", entry.path, exc)
        return "failed"

    sha = _sha256(content)
    photo = session.execute(
        select(Photo).where(Photo.sha256 == sha)
    ).scalar_one_or_none()

    is_new_photo = photo is None
    if is_new_photo:
        meta = parse_bytes(content)
        phash = parse_phash_bytes(content)
        photo = Photo(
            sha256=sha,
            phash=phash,
            size_bytes=entry.size_bytes,
            mime_type="image/jpeg",
            width=meta.width,
            height=meta.height,
            taken_at=meta.taken_at,
            camera_make=meta.camera_make,
            camera_model=meta.camera_model,
            lens_model=meta.lens_model,
            iso=meta.iso,
            aperture=meta.aperture,
            shutter=meta.shutter,
            focal_mm=meta.focal_mm,
            gps_lat=meta.gps_lat,
            gps_lon=meta.gps_lon,
            state="active",
        )
        session.add(photo)
        session.flush()
    else:
        photo.last_seen_at = _utc_now()
        if photo.state == "missing":
            photo.state = "active"

    if pp is None:
        session.add(
            PhotoPath(
                photo_id=photo.id,
                nas_id=walker.nas_id,
                path=entry.path,
                size_bytes=entry.size_bytes,
                mtime=entry.mtime,
            )
        )
    else:
        pp.photo_id = photo.id
        pp.size_bytes = entry.size_bytes
        pp.mtime = entry.mtime
        pp.last_seen_at = _utc_now()

    if is_new_photo:
        _enqueue_basic(session, photo.id, priority=10)
        return "new"

    if not _has_eval_or_pending(session, photo.id):
        _enqueue_basic(session, photo.id, priority=5)
    return "changed"


def _enqueue_basic(session: Session, photo_id: int, priority: int) -> None:
    session.add(
        EvalJob(
            photo_id=photo_id,
            kind="basic",
            priority=priority,
            state="pending",
        )
    )


def _has_eval_or_pending(session: Session, photo_id: int) -> bool:
    eval_exists = session.execute(
        select(Evaluation.id).where(Evaluation.photo_id == photo_id).limit(1)
    ).scalar_one_or_none()
    if eval_exists is not None:
        return True
    job_exists = session.execute(
        select(EvalJob.id)
        .where(
            EvalJob.photo_id == photo_id,
            EvalJob.kind == "basic",
            EvalJob.state.in_(("pending", "in_progress")),
        )
        .limit(1)
    ).scalar_one_or_none()
    return job_exists is not None
