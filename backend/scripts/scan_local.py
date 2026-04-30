"""로컬 폴더 스캔 CLI.

DSM 어댑터가 들어오기 전, 로컬 사진 라이브러리에 식별·upsert 파이프라인을
검증하기 위한 도구.

사용법
  python -m scripts.scan_local <folder> [--nas-id <id>] [--log-level INFO]

DB는 app.config의 db_url(기본 ./data/photo_archive.sqlite)을 사용한다.
사전에 `alembic upgrade head`로 스키마가 적용되어 있어야 한다.
"""

from __future__ import annotations

import logging
from pathlib import Path

import click

from app.scanner.local import LocalScanner
from app.storage.db import SessionLocal
from app.storage.models import ScanJob


@click.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--nas-id", default="local", help="photo_paths.nas_id (다중 NAS 구분자)")
@click.option("--log-level", default="INFO")
def main(folder: Path, nas_id: str, log_level: str) -> None:
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    scanner = LocalScanner(SessionLocal, nas_id=nas_id)
    job_id = scanner.scan(folder.resolve())

    with SessionLocal() as s:
        job = s.get(ScanJob, job_id)
        click.echo(f"\n[+] scan job {job.id}: {job.state}")
        click.echo(f"    discovered: {job.discovered}")
        click.echo(f"    new:        {job.new_photos}")
        click.echo(f"    changed:    {job.changed}")
        click.echo(f"    skipped:    {job.skipped}")
        if job.error:
            click.echo(f"    error:      {job.error}", err=True)


if __name__ == "__main__":
    main()
