"""FastAPI 의존성: 보호된 엔드포인트에 부착."""

from __future__ import annotations

from fastapi import HTTPException, Request, status


def require_auth(request: Request) -> None:
    """세션에 auth 플래그가 없으면 401."""
    if not request.session.get("auth"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="auth required",
        )
