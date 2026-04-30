"""DSM 폴더 스캔 CLI.

사전: scripts.nas_login으로 NAS 자격증명이 키체인에 + DB(settings)에 저장돼 있어야 한다.

사용법
  python -m scripts.scan_dsm --folder "/photo/My Pictures-2023"
"""

from __future__ import annotations

import logging
import sys

import click

from app.nas.credentials import load_config, load_device_id, load_password
from app.scanner.dsm import DSMScanner
from app.storage.db import SessionLocal
from app.storage.models import ScanJob


@click.command()
@click.option("--folder", required=True, help="DSM 절대경로, 예: /photo/My Pictures-2023")
@click.option("--log-level", default="INFO")
def main(folder: str, log_level: str) -> None:
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    with SessionLocal() as s:
        config = load_config(s)
    if config is None:
        click.echo("NAS not configured. Run: python -m scripts.nas_login --url ... --user ...", err=True)
        sys.exit(1)

    password = load_password(config.username)
    if not password:
        click.echo(f"NAS password for '{config.username}' missing in keyring", err=True)
        sys.exit(1)

    device_id = load_device_id(config.username)
    scanner = DSMScanner(SessionLocal, config, password, device_id=device_id)
    click.echo(f"[*] DSM scanner nas_id={scanner.nas_id}")
    click.echo(f"[*] folder       {folder}")

    job_id = scanner.scan(folder)

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
