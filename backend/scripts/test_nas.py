"""DSM 연결 테스트 CLI.

사용법:
  python -m scripts.test_nas --url http://192.168.0.222:5000 --user USER --password PASS

DB나 키체인은 건드리지 않는다 — 1회성 검증용.
"""

from __future__ import annotations

import logging
import sys

import click

from app.nas.dsm import DSMClient, DSMError, query_api_info


@click.command()
@click.option("--url", required=True, help="DSM base URL, e.g. http://192.168.0.222:5000")
@click.option("--user", required=True)
@click.option("--password", required=True, prompt=True, hide_input=True)
@click.option("--otp", default=None, help="2FA code (있을 때만)")
def main(url: str, user: str, password: str, otp: str | None) -> None:
    logging.basicConfig(level="INFO", format="%(levelname)s %(name)s: %(message)s")

    click.echo(f"[1] API.Info on {url}")
    try:
        info = query_api_info(url)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"    FAILED: {exc}", err=True)
        sys.exit(1)
    if not info.get("success"):
        click.echo(f"    FAILED: {info}", err=True)
        sys.exit(1)
    apis = info.get("data", {})
    for name, meta in apis.items():
        click.echo(f"    {name:32s} maxVersion={meta.get('maxVersion')}")

    click.echo(f"\n[2] login as {user}")
    try:
        with DSMClient(url) as client:
            client.login(user, password, otp_code=otp)
            click.echo("    OK")

            click.echo("\n[3] list shares")
            shares = client.list_shares()
            for s in shares:
                click.echo(f"    {s.get('name'):20s} -> {s.get('path')}")

            if shares:
                click.echo(f"\n[4] list root of '{shares[0].get('path')}' (first 10)")
                files = client.list_folder(shares[0]["path"], limit=10)
                for f in files:
                    kind = "DIR" if f.get("isdir") else "FILE"
                    size = f.get("additional", {}).get("size", "-")
                    click.echo(f"    {kind:5s} {size:>12} {f.get('name')}")
    except DSMError as exc:
        click.echo(f"    FAILED: {exc}", err=True)
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001
        click.echo(f"    FAILED: {exc}", err=True)
        sys.exit(3)


if __name__ == "__main__":
    main()
