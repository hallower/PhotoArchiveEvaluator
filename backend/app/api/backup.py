"""DB 백업 API.

POST /api/backup            — DB를 NAS에 즉시 백업 (백그라운드)
GET  /api/backup            — 백업 이력
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth.dependencies import require_auth
from ..config import settings
from ..nas.session import open_dsm_client
from ..storage.db import SessionLocal, get_session
from ..storage.models import Backup, Photo

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/backup",
    tags=["backup"],
    dependencies=[Depends(require_auth)],
)

BACKUP_DIR_ON_NAS = "/photo/.photoarchive/backups"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _db_path() -> Path:
    """SQLite URL에서 파일 경로 추출."""
    url = settings.db_url
    if not url.startswith("sqlite"):
        raise RuntimeError("backup only supports sqlite")
    # sqlite:///./data/photo_archive.sqlite → ./data/photo_archive.sqlite
    parsed = urlparse(url)
    path_part = parsed.path
    if path_part.startswith("/"):
        # sqlite:///abs/path or sqlite:///./relative
        return Path(path_part[1:])
    return Path(path_part)


def _run_backup(backup_id: int) -> None:
    """SQLite VACUUM INTO로 일관된 스냅샷 생성 후 NAS로 업로드."""
    src_db = _db_path()
    ts = _utc_now().strftime("%Y%m%d_%H%M%S")
    tmp_dump = settings.data_dir / f"db_dump_{ts}.sqlite"

    with SessionLocal() as session:
        bkp = session.get(Backup, backup_id)
        if bkp is None:
            return

    try:
        # 1) VACUUM INTO 스냅샷
        with sqlite3.connect(str(src_db)) as conn:
            conn.execute(f"VACUUM INTO '{tmp_dump.as_posix()}'")
        size = tmp_dump.stat().st_size

        with SessionLocal() as session:
            photo_count = session.execute(select(func.count(Photo.id))).scalar() or 0

        # 2) NAS 업로드 (기본) — DSM 미구성이면 로컬 backups/ 폴더로 fallback
        nas_target: str | None = None
        try:
            with SessionLocal() as session:
                client = open_dsm_client(session)
            try:
                from ..nas.dsm import DSMClient  # noqa: F401  (타입 의존)

                # 디렉터리 보장
                _ensure_dsm_dir(client, BACKUP_DIR_ON_NAS)
                nas_target = f"{BACKUP_DIR_ON_NAS}/photoarchive_{ts}.sqlite"
                _upload_to_dsm(client, tmp_dump, nas_target)
            finally:
                try:
                    client.logout()
                finally:
                    client._client.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("NAS upload failed, falling back to local: %s", exc)
            local_dir = settings.data_dir / "backups"
            local_dir.mkdir(parents=True, exist_ok=True)
            target = local_dir / f"photoarchive_{ts}.sqlite"
            shutil.copy2(tmp_dump, target)
            nas_target = f"local:{target}"

        with SessionLocal() as session:
            bkp = session.get(Backup, backup_id)
            if bkp:
                bkp.state = "done"
                bkp.finished_at = _utc_now()
                bkp.nas_path = nas_target
                bkp.size_bytes = size
                bkp.photo_count = int(photo_count)
                session.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("backup failed")
        with SessionLocal() as session:
            bkp = session.get(Backup, backup_id)
            if bkp:
                bkp.state = "failed"
                bkp.error = str(exc)[:1000]
                bkp.finished_at = _utc_now()
                session.commit()
    finally:
        try:
            tmp_dump.unlink(missing_ok=True)
        except OSError:
            pass


def _ensure_dsm_dir(client, path: str) -> None:
    """DSM에 폴더가 없으면 생성. 부모 폴더는 존재한다고 가정."""
    parent, _, name = path.rstrip("/").rpartition("/")
    if not parent:
        parent = "/"
    # CreateFolder API
    client._call(
        "SYNO.FileStation.CreateFolder",
        2,
        "create",
        folder_path=parent,
        name=name,
        force_parent="true",
    )


def _upload_to_dsm(client, local_file: Path, dest_full_path: str) -> None:
    """SYNO.FileStation.Upload로 파일 업로드."""
    import httpx

    parent, _, name = dest_full_path.rstrip("/").rpartition("/")
    params = {
        "api": "SYNO.FileStation.Upload",
        "version": "2",
        "method": "upload",
        "_sid": client._sid,
    }
    data = {
        "path": parent,
        "create_parents": "true",
        "overwrite": "true",
    }
    with local_file.open("rb") as f:
        files = {"file": (name, f, "application/octet-stream")}
        resp = httpx.post(
            f"{client.base_url}/webapi/entry.cgi",
            params=params,
            data=data,
            files=files,
            timeout=300,
        )
    resp.raise_for_status()
    j = resp.json()
    if not j.get("success"):
        raise RuntimeError(f"DSM upload failed: {j.get('error')}")


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def trigger_backup(session: Session = Depends(get_session)) -> dict:
    bkp = Backup(state="running")
    session.add(bkp)
    session.commit()
    session.refresh(bkp)
    bid = bkp.id
    threading.Thread(target=_run_backup, args=(bid,), daemon=True, name="backup").start()
    return {"queued": True, "id": bid}


@router.get("")
def list_backups(session: Session = Depends(get_session), limit: int = 20) -> list[dict]:
    rows = session.execute(
        select(Backup).order_by(Backup.id.desc()).limit(limit)
    ).scalars().all()
    return [
        {
            "id": b.id,
            "state": b.state,
            "started_at": b.started_at.isoformat() if b.started_at else None,
            "finished_at": b.finished_at.isoformat() if b.finished_at else None,
            "nas_path": b.nas_path,
            "size_bytes": b.size_bytes,
            "photo_count": b.photo_count,
            "error": b.error,
        }
        for b in rows
    ]
