"""런타임 설정 (settings 테이블) 접근 헬퍼.

config.py는 부팅 시 환경변수/.env에서 읽는 정적 설정.
settings_store는 사용자가 UI에서 수정 가능한 동적 설정.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .storage.models import Setting

# 키 상수
EVAL_PROMPT = "eval.prompt"

DEFAULT_EVAL_PROMPT = (
    "a high-quality aesthetic photograph with strong composition, "
    "balanced lighting, mood, and emotional impact, suitable for "
    "a photography portfolio or contest"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get(session: Session, key: str, default: str | None = None) -> str | None:
    row = session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    return row.value if row else default


def set_value(session: Session, key: str, value: str) -> None:
    row = session.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()
    if row:
        row.value = value
        row.updated_at = _utc_now()
    else:
        session.add(Setting(key=key, value=value))
    session.commit()


def get_eval_prompt(session: Session) -> str:
    return get(session, EVAL_PROMPT, default=DEFAULT_EVAL_PROMPT) or DEFAULT_EVAL_PROMPT
