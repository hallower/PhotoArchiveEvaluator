"""기존 photos에 perceptual hash 보강.

사용법
  python -m scripts.backfill_phash [--limit N]
"""

from __future__ import annotations

import logging
from pathlib import Path

import click
from sqlalchemy import select

from app.nas.session import open_dsm_client
from app.scanner.exif import parse_phash_bytes
from app.storage.db import SessionLocal
from app.storage.models import Photo, PhotoPath


def _read(session, pp: PhotoPath, dsm=None):
    if pp.nas_id == "local":
        return Path(pp.path).read_bytes(), dsm
    if pp.nas_id.startswith("dsm:"):
        if dsm is None:
            dsm = open_dsm_client(session)
        return dsm.download(pp.path), dsm
    raise ValueError(f"unsupported nas_id: {pp.nas_id}")


@click.command()
@click.option("--limit", type=int, default=None)
@click.option("--log-level", default="INFO")
def main(limit: int | None, log_level: str) -> None:
    logging.basicConfig(level=log_level, format="%(levelname)s %(name)s: %(message)s")

    with SessionLocal() as s:
        ids = [
            r[0]
            for r in s.execute(
                select(Photo.id).where(Photo.phash.is_(None), Photo.state == "active").order_by(Photo.id)
            )
        ]
    if limit:
        ids = ids[:limit]
    click.echo(f"[*] {len(ids)} photos missing phash")

    dsm = None
    done = 0
    failed = 0
    try:
        for pid in ids:
            with SessionLocal() as s:
                photo = s.get(Photo, pid)
                pp = s.execute(
                    select(PhotoPath).where(PhotoPath.photo_id == pid).limit(1)
                ).scalar_one_or_none()
                if photo is None or pp is None:
                    failed += 1
                    continue
                try:
                    content, dsm = _read(s, pp, dsm)
                except Exception as exc:  # noqa: BLE001
                    click.echo(f"  [!] read fail pid={pid}: {exc}", err=True)
                    failed += 1
                    continue
                ph = parse_phash_bytes(content)
                if ph is None:
                    failed += 1
                    continue
                photo.phash = ph
                s.commit()
                done += 1
                if done % 25 == 0:
                    click.echo(f"    progress: {done}/{len(ids)}")
    finally:
        if dsm is not None:
            try:
                dsm.logout()
            finally:
                dsm._client.close()

    click.echo(f"\n[+] phashed: {done}  failed: {failed}")


if __name__ == "__main__":
    main()
