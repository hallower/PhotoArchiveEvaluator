"""인증 라우터.

흐름
  1) 최초 부팅: GET /api/auth/status → setup_required = true
  2) POST /api/auth/setup { password } → 204 + 세션 쿠키 발급
  3) 이후: POST /api/auth/login { password } / POST /api/auth/logout
  4) 보호 라우트: dependencies.py의 require_auth 사용
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..storage.db import get_session
from .password import hash_password, verify_password
from .store import get_password_hash, is_setup, set_password_hash

router = APIRouter(prefix="/api/auth", tags=["auth"])


class _PasswordIn(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class _LoginIn(BaseModel):
    password: str


@router.get("/status")
def status_(request: Request, session: Session = Depends(get_session)) -> dict:
    return {
        "authenticated": bool(request.session.get("auth")),
        "setup_required": not is_setup(session),
    }


@router.post("/setup", status_code=status.HTTP_204_NO_CONTENT)
def setup(
    body: _PasswordIn,
    request: Request,
    session: Session = Depends(get_session),
) -> None:
    if is_setup(session):
        # 이미 세팅된 시스템에서 재설정은 인증된 change-password 경로로 분리.
        raise HTTPException(status.HTTP_409_CONFLICT, "already set up")
    set_password_hash(session, hash_password(body.password))
    request.session["auth"] = True


@router.post("/login")
def login(
    body: _LoginIn,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
    h = get_password_hash(session)
    if h is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "setup required")
    if not verify_password(body.password, h):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid password")
    request.session["auth"] = True
    return {"ok": True}


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}
