"""auth 관련 영속 상태(비밀번호 해시 등) 접근 헬퍼."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..storage.models import Setting

PASSWORD_HASH_KEY = "auth.password_hash"


def get_password_hash(session: Session) -> str | None:
    row = session.execute(
        select(Setting).where(Setting.key == PASSWORD_HASH_KEY)
    ).scalar_one_or_none()
    return row.value if row else None


def set_password_hash(session: Session, value: str) -> None:
    row = session.execute(
        select(Setting).where(Setting.key == PASSWORD_HASH_KEY)
    ).scalar_one_or_none()
    if row:
        row.value = value
    else:
        session.add(Setting(key=PASSWORD_HASH_KEY, value=value))
    session.commit()


def is_setup(session: Session) -> bool:
    return get_password_hash(session) is not None
