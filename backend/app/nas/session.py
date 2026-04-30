"""DSM 클라이언트 생성 헬퍼.

저장된 자격증명(키체인) + 설정(DB) 기반으로 로그인된 DSMClient를 반환한다.
호출자는 with 블록(또는 명시 close)으로 세션을 정리해야 한다.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from .credentials import DEVICE_NAME, load_config, load_device_id, load_password
from .dsm import DSMClient


def open_dsm_client(session: Session) -> DSMClient:
    config = load_config(session)
    if config is None:
        raise RuntimeError("NAS not configured — POST /api/nas/setup or scripts.nas_login")
    password = load_password(config.username)
    if not password:
        raise RuntimeError("DSM password missing in OS keyring")
    device_id = load_device_id(config.username)

    client = DSMClient(config.base_url)
    client.login(
        config.username,
        password,
        device_id=device_id,
        device_name=DEVICE_NAME if device_id else None,
    )
    return client
