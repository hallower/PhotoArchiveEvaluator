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
EVAL_MAX_WORKERS = "eval.max_workers"
LIBRARY_MIN_SCORE = "library.min_score"
SCAN_LOCAL_PATHS = "scan.local.paths"  # JSON list[str]
SCAN_DSM_PATHS = "scan.dsm.paths"  # JSON list[str]

DEFAULT_EVAL_PROMPT = (
    "a high-quality aesthetic photograph with strong composition, "
    "balanced lighting, mood, and emotional impact, suitable for "
    "a photography portfolio or contest"
)
DEFAULT_MIN_SCORE = 4.0
DEFAULT_MAX_WORKERS = 2  # GPU 1개 + 다운로드 오버랩 가정 시 2가 sweet spot
MAX_ALLOWED_WORKERS = 6


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


def get_min_score(session: Session) -> float:
    raw = get(session, LIBRARY_MIN_SCORE)
    if raw is None:
        return DEFAULT_MIN_SCORE
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_MIN_SCORE


def set_min_score(session: Session, value: float) -> None:
    set_value(session, LIBRARY_MIN_SCORE, str(value))


def get_max_workers(session: Session) -> int:
    raw = get(session, EVAL_MAX_WORKERS)
    if raw is None:
        return DEFAULT_MAX_WORKERS
    try:
        n = int(raw)
        return max(1, min(MAX_ALLOWED_WORKERS, n))
    except ValueError:
        return DEFAULT_MAX_WORKERS


def set_max_workers(session: Session, n: int) -> None:
    n = max(1, min(MAX_ALLOWED_WORKERS, int(n)))
    set_value(session, EVAL_MAX_WORKERS, str(n))


def get_paths_list(session: Session, key: str) -> list[str]:
    import json

    raw = get(session, key)
    if not raw:
        return []
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [str(p) for p in v if p]
    except json.JSONDecodeError:
        pass
    return []


def set_paths_list(session: Session, key: str, paths: list[str]) -> None:
    import json

    cleaned = [p.strip() for p in paths if p and p.strip()]
    set_value(session, key, json.dumps(cleaned, ensure_ascii=False))
