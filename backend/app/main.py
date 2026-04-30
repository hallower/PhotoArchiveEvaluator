"""FastAPI 엔트리포인트.

Phase 1 골격: /healthz + 인증.
스캐너·평가 워커·라이브러리 API는 후속 PR에서 점진 추가.
"""

from __future__ import annotations

import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from .auth.dependencies import require_auth
from .auth.router import router as auth_router
from .config import settings
from .storage.db import SessionLocal


def _setup_logging() -> None:
    settings.log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler(settings.log_dir / "app.log", encoding="utf-8"),
    ]
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def _resolve_session_secret() -> str:
    """env > data_dir/session.key > 자동 생성."""
    if settings.session_secret_env:
        return settings.session_secret_env
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key_path = settings.data_dir / "session.key"
    if key_path.exists():
        return key_path.read_text().strip()
    secret = secrets.token_urlsafe(48)
    key_path.write_text(secret)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        # Windows는 chmod 의미 제한적. .gitignore와 ACL로 1차 보호.
        pass
    return secret


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
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

app.add_middleware(
    SessionMiddleware,
    secret_key=_resolve_session_secret(),
    same_site="lax",
    https_only=settings.cookie_secure,
    max_age=settings.cookie_max_age_days * 24 * 60 * 60,
)

app.include_router(auth_router)


@app.get("/healthz")
def healthz() -> dict:
    """기본 헬스체크. DB 연결 라운드트립 포함. 인증 불필요."""
    db_ok = False
    try:
        with SessionLocal() as session:
            db_ok = session.execute(select(1)).scalar() == 1
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).exception("db health check failed: %s", exc)

    return {
        "status": "ok" if db_ok else "degraded",
        "db_ok": db_ok,
        "time": datetime.now(timezone.utc).isoformat(),
        "version": app.version,
    }


@app.get("/api/me", dependencies=[Depends(require_auth)])
def me() -> dict:
    """인증 동작 검증용. 후속 사용자 프로필 엔드포인트로 확장 가능."""
    return {"authenticated": True}
