"""SQLAlchemy 엔진 / 세션 / Base.

세션은 short-lived. 워커는 작업 단위로 SessionLocal()을 열고 닫는다.
FastAPI 라우터는 get_session() 의존성으로 주입받는다.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ..config import settings


class Base(DeclarativeBase):
    pass


def _build_engine():
    connect_args: dict = {}
    if settings.db_url.startswith("sqlite"):
        # SQLite는 기본적으로 같은 파일에 다중 스레드 접근 시 락 충돌. 워커가 비동기/스레드로
        # 함께 접근할 수 있으므로 check_same_thread=False로 풀어둔다(쓰기 직렬화는 SQLite 자체).
        connect_args["check_same_thread"] = False
    return create_engine(settings.db_url, future=True, echo=False, connect_args=connect_args)


engine = _build_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_session() -> Generator[Session, None, None]:
    """FastAPI 의존성."""
    with SessionLocal() as session:
        yield session
