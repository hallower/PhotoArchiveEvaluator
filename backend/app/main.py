"""FastAPI 엔트리포인트.

Phase 1 골격: /healthz, 디렉터리/DB 연결 검증.
스캐너·평가 워커·라이브러리 API는 후속 PR에서 점진 추가.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from sqlalchemy import select

from .config import settings
from .storage.db import SessionLocal


def _setup_logging() -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    handlers.append(logging.FileHandler(settings.log_dir / "app.log", encoding="utf-8"))
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.thumb_dir.mkdir(parents=True, exist_ok=True)
    logging.getLogger(__name__).info(
        "startup: data_dir=%s db_url=%s", settings.data_dir, settings.db_url
    )
    yield


app = FastAPI(
    title="Photo Archive Evaluator",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/healthz")
def healthz() -> dict:
    """기본 헬스체크. DB 연결 라운드트립 포함."""
    db_ok = False
    try:
        with SessionLocal() as session:
            db_ok = session.execute(select(1)).scalar() == 1
    except Exception as exc:  # noqa: BLE001 — 헬스체크 목적으로 광범위 캐치
        logging.getLogger(__name__).exception("db health check failed: %s", exc)

    return {
        "status": "ok" if db_ok else "degraded",
        "db_ok": db_ok,
        "time": datetime.now(timezone.utc).isoformat(),
        "version": app.version,
    }
