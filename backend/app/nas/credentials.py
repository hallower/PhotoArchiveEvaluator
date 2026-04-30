"""NAS 자격증명 보관.

비밀번호: OS 키체인 (Windows: Credential Manager / Linux: libsecret / macOS: Keychain)
URL·사용자명·연결 옵션: settings 테이블 (DB)

비밀번호는 절대 DB에 저장하지 않으며, 키체인 사용 불가 환경에서는 의도적으로 실패한다
(설정 우회로 평문 저장하지 않음).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import keyring
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..storage.models import Setting

log = logging.getLogger(__name__)

KEYRING_SERVICE = "PhotoArchiveEvaluator-NAS"
KEYRING_DEVICE_SERVICE = "PhotoArchiveEvaluator-NAS-Device"
SETTING_KEY = "nas.dsm"
DEVICE_NAME = "PhotoArchiveEvaluator"


@dataclass
class DSMConfig:
    base_url: str
    username: str
    use_otp: bool = False  # 2FA 사용 여부 (otp_code는 매번 사용자 입력)


def save_config(session: Session, config: DSMConfig, password: str) -> None:
    """비밀번호는 키체인에, 나머지는 DB에 저장."""
    keyring.set_password(KEYRING_SERVICE, config.username, password)

    payload = json.dumps(
        {
            "base_url": config.base_url,
            "username": config.username,
            "use_otp": config.use_otp,
        }
    )
    row = session.execute(
        select(Setting).where(Setting.key == SETTING_KEY)
    ).scalar_one_or_none()
    if row:
        row.value = payload
    else:
        session.add(Setting(key=SETTING_KEY, value=payload))
    session.commit()
    log.info("nas.dsm config saved: url=%s user=%s", config.base_url, config.username)


def load_config(session: Session) -> DSMConfig | None:
    row = session.execute(
        select(Setting).where(Setting.key == SETTING_KEY)
    ).scalar_one_or_none()
    if not row:
        return None
    raw = json.loads(row.value)
    return DSMConfig(**raw)


def load_password(username: str) -> str | None:
    return keyring.get_password(KEYRING_SERVICE, username)


def save_device_id(username: str, device_id: str) -> None:
    keyring.set_password(KEYRING_DEVICE_SERVICE, username, device_id)


def load_device_id(username: str) -> str | None:
    return keyring.get_password(KEYRING_DEVICE_SERVICE, username)


def clear_device_id(username: str) -> None:
    try:
        keyring.delete_password(KEYRING_DEVICE_SERVICE, username)
    except keyring.errors.PasswordDeleteError:
        pass


def clear(session: Session) -> bool:
    config = load_config(session)
    if config is None:
        return False
    try:
        keyring.delete_password(KEYRING_SERVICE, config.username)
    except keyring.errors.PasswordDeleteError:
        log.warning("password already absent in keyring")
    clear_device_id(config.username)
    session.execute(
        Setting.__table__.delete().where(Setting.key == SETTING_KEY)
    )
    session.commit()
    return True
