"""DSM 최초 설정 / 로그인 검증 (사용자 PC 로컬 실행 전용).

OTP가 채팅 등 외부 채널에 노출되지 않도록 본 스크립트에서만 prompt로 입력 받는다.
로그인 성공 시 device_id가 키체인에 저장되어 다음부터 OTP 입력이 불필요하다.

사용법:
  python -m scripts.nas_login --url http://192.168.0.222:5000 --user photo

흐름:
  1) 비밀번호: 키체인에서 읽음. 없으면 prompt하여 저장.
  2) device_id: 키체인에 있으면 OTP 없이 로그인 시도.
  3) device_id 미존재 또는 만료: OTP prompt → 로그인 + enable_device_token=True →
     응답의 did를 키체인에 저장.
"""

from __future__ import annotations

import sys

import click
import keyring

from app.nas.credentials import (
    DEVICE_NAME,
    KEYRING_SERVICE,
    clear_device_id,
    load_device_id,
    save_device_id,
)
from app.nas.dsm import DSMClient, DSMError


@click.command()
@click.option("--url", required=True, help="예: http://192.168.0.222:5000")
@click.option("--user", required=True, help="DSM 사용자명")
def main(url: str, user: str) -> None:
    # 1) 비밀번호 확보
    pw = keyring.get_password(KEYRING_SERVICE, user)
    if pw is None:
        pw = click.prompt("DSM password", hide_input=True)
        keyring.set_password(KEYRING_SERVICE, user, pw)
        click.echo("  password saved to keyring")

    # 2) device_id로 로그인 시도
    did = load_device_id(user)
    if did:
        click.echo(f"[1] device_id 로그인 시도 (did=...{did[-6:]})")
        try:
            with DSMClient(url) as c:
                c.login(user, pw, device_id=did, device_name=DEVICE_NAME)
                click.echo("    OK — OTP 없이 로그인 성공")
                _show_shares(c)
            return
        except DSMError as exc:
            click.echo(f"    실패 ({exc}) — device_id 만료 또는 무효, 재발급 필요")
            clear_device_id(user)

    # 3) OTP 경로
    click.echo("[2] OTP 인증 + device_id 발급")
    otp = click.prompt("    현재 6자리 OTP 코드", hide_input=False)
    try:
        with DSMClient(url) as c:
            c.login(
                user,
                pw,
                otp_code=otp,
                enable_device_token=True,
                device_name=DEVICE_NAME,
            )
            click.echo(f"    로그인 OK (sid=...{c._sid[-6:]})")
            if c.device_id:
                save_device_id(user, c.device_id)
                click.echo(f"    device_id 저장 완료 — 다음부터 OTP 불필요 (did=...{c.device_id[-6:]})")
            else:
                click.echo("    경고: 응답에 did 없음 — DSM 설정에서 'Trust this device' 옵션 확인")
            _show_shares(c)
    except DSMError as exc:
        click.echo(f"    로그인 실패: {exc}", err=True)
        sys.exit(1)


def _show_shares(c: DSMClient) -> None:
    shares = c.list_shares()
    click.echo(f"\nshares ({len(shares)}):")
    for s in shares:
        click.echo(f"  {s.get('name'):24s} -> {s.get('path')}")


if __name__ == "__main__":
    main()
