"""로컬 디스크 폴더 스캐너.

DSM 어댑터 도입 전 단계 검증용. 식별·upsert 로직은 DSM 스캐너에서 그대로 재사용된다.

식별 정책 (SPEC §4.3)
  1차: photo_paths(nas_id, path)에서 (size, mtime) 동일하면 변경 없음으로 간주
  2차: 변화 시 SHA-256 재계산 → 같은 sha의 photo가 있으면 path만 갱신
  3차(Phase 2): pHash로 이름변경/이동/리사이즈 추적
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..storage.models import EvalJob, Evaluation, Photo, PhotoPath, ScanJob
from .exif import parse as parse_exif

log = logging.getLogger(__name__)

JPG_SUFFIXES = {".jpg", ".jpeg"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _walk_jpgs(root: Path) -> Iterator[Path]:
    for p in root.rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() in JPG_SUFFIXES:
                yield p
        except OSError as exc:
            log.warning("walk error %s: %s", p, exc)


def _sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


@dataclass
class ScanStats:
    discovered: int = 0
    new_photos: int = 0
    changed: int = 0
    skipped: int = 0
    failed: int = 0


class LocalScanner:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        nas_id: str = "local",
    ) -> None:
        self._session_factory = session_factory
        self.nas_id = nas_id

    def scan(self, root: Path) -> int:
        """root 폴더를 스캔. ScanJob.id 반환. 진행 중 상태는 DB에 즉시 반영된다."""
        root = Path(root).resolve()
        log.info("scan start: nas_id=%s root=%s", self.nas_id, root)

        with self._session_factory() as s:
            job = ScanJob(state="running", folders=json.dumps([str(root)]))
            s.add(job)
            s.commit()
            s.refresh(job)
            job_id = job.id

        try:
            with self._session_factory() as s:
                job = s.get(ScanJob, job_id)
                for path in _walk_jpgs(root):
                    outcome = self._process_file(s, path)
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
            with self._session_factory() as s:
                job = s.get(ScanJob, job_id)
                if job:
                    job.state = "failed"
                    job.error = str(exc)
                    job.finished_at = _utc_now()
                    s.commit()
            raise

        log.info("scan done: job_id=%d", job_id)
        return job_id

    def _process_file(self, session: Session, path: Path) -> str:
        """반환: 'new' | 'changed' | 'skipped' | 'failed'."""
        try:
            st = path.stat()
        except OSError as exc:
            log.warning("stat failed %s: %s", path, exc)
            return "failed"

        size_bytes = st.st_size
        # 초 단위로 정규화. 파일시스템/SQLite 정밀도 차이로 인한 불일치 방지.
        mtime = datetime.fromtimestamp(int(st.st_mtime), tz=timezone.utc)
        path_str = str(path)

        pp = session.execute(
            select(PhotoPath).where(
                PhotoPath.nas_id == self.nas_id,
                PhotoPath.path == path_str,
            )
        ).scalar_one_or_none()

        # Fast path: 변화 없음
        if pp and pp.size_bytes == size_bytes and pp.mtime.replace(tzinfo=timezone.utc) == mtime:
            pp.last_seen_at = _utc_now()
            if pp.photo:
                pp.photo.last_seen_at = _utc_now()
                if pp.photo.state == "missing":
                    pp.photo.state = "active"
            return "skipped"

        # Slow path: 새 파일이거나 변경됨
        try:
            sha = _sha256_of(path)
        except OSError as exc:
            log.warning("hash failed %s: %s", path, exc)
            return "failed"

        photo = session.execute(
            select(Photo).where(Photo.sha256 == sha)
        ).scalar_one_or_none()

        is_new_photo = photo is None
        if is_new_photo:
            meta = parse_exif(path)
            photo = Photo(
                sha256=sha,
                size_bytes=size_bytes,
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

        # photo_paths upsert
        if pp is None:
            session.add(
                PhotoPath(
                    photo_id=photo.id,
                    nas_id=self.nas_id,
                    path=path_str,
                    size_bytes=size_bytes,
                    mtime=mtime,
                )
            )
        else:
            pp.photo_id = photo.id
            pp.size_bytes = size_bytes
            pp.mtime = mtime
            pp.last_seen_at = _utc_now()

        if is_new_photo:
            self._enqueue_basic(session, photo.id, priority=10)
            return "new"

        # 같은 sha 사진의 새 path 또는 같은 path에서 같은 sha 콘텐츠 변경 없음.
        # 평가 한 번도 없었거나 큐도 없으면 enqueue.
        if not self._has_eval_or_pending(session, photo.id):
            self._enqueue_basic(session, photo.id, priority=5)
        return "changed"

    @staticmethod
    def _enqueue_basic(session: Session, photo_id: int, priority: int) -> None:
        session.add(
            EvalJob(
                photo_id=photo_id,
                kind="basic",
                priority=priority,
                state="pending",
            )
        )

    @staticmethod
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
