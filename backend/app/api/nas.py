"""NAS (Synology DSM) 설정·테스트 API.

POST   /api/nas/test        — 입력한 자격증명으로 1회 로그인 시도 (저장 안 함)
POST   /api/nas/setup       — 자격증명 저장 (URL/사용자명: DB, 비밀번호: 키체인)
GET    /api/nas/status      — 현재 저장된 설정과 연결 가능성
GET    /api/nas/folders     — 저장된 자격증명으로 폴더 브라우즈
DELETE /api/nas              — 저장된 NAS 설정 제거
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..auth.dependencies import require_auth
from ..nas.credentials import (
    DEVICE_NAME,
    DSMConfig,
    clear,
    load_config,
    load_device_id,
    load_password,
    save_config,
    save_device_id,
)
from ..nas.dsm import DSMClient, DSMError, query_api_info
from ..storage.db import get_session

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/nas",
    tags=["nas"],
    dependencies=[Depends(require_auth)],
)


class _NASCreds(BaseModel):
    base_url: str = Field(..., examples=["http://192.168.0.222:5000"])
    username: str
    password: str
    otp_code: str | None = None


class _NASSetup(_NASCreds):
    use_otp: bool = False


@router.post("/test")
def test_connection(body: _NASCreds) -> dict:
    """저장 없이 1회 로그인 시도. shares 목록까지 확인."""
    try:
        info = query_api_info(body.base_url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"NAS unreachable or not DSM: {exc}",
        ) from exc

    if not info.get("success"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "DSM API.Info call failed")

    try:
        with DSMClient(body.base_url) as client:
            client.login(body.username, body.password, otp_code=body.otp_code)
            shares = client.list_shares()
    except DSMError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"connection failed: {exc}") from exc

    return {
        "ok": True,
        "api_versions": {k: v.get("maxVersion") for k, v in info.get("data", {}).items()},
        "shares": [{"name": s.get("name"), "path": s.get("path")} for s in shares],
    }


@router.post("/setup", status_code=status.HTTP_204_NO_CONTENT)
def setup(body: _NASSetup, session: Session = Depends(get_session)) -> None:
    # 저장 전 검증 — 잘못된 자격증명을 키체인에 남기지 않는다.
    # 2FA 활성 시 enable_device_token=True로 did를 받아 키체인에 보관, 다음부터 OTP 우회.
    try:
        with DSMClient(body.base_url) as client:
            client.login(
                body.username,
                body.password,
                otp_code=body.otp_code,
                enable_device_token=bool(body.use_otp or body.otp_code),
                device_name=DEVICE_NAME,
            )
            device_id = client.device_id
    except DSMError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    save_config(
        session,
        DSMConfig(base_url=body.base_url, username=body.username, use_otp=body.use_otp),
        body.password,
    )
    if device_id:
        save_device_id(body.username, device_id)


@router.get("/status")
def get_status(session: Session = Depends(get_session)) -> dict:
    config = load_config(session)
    if config is None:
        return {"configured": False}

    has_password = load_password(config.username) is not None
    return {
        "configured": True,
        "base_url": config.base_url,
        "username": config.username,
        "use_otp": config.use_otp,
        "password_in_keyring": has_password,
    }


@router.get("/folders")
def list_folders(
    path: str = "",
    session: Session = Depends(get_session),
) -> dict:
    config = load_config(session)
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "NAS not configured")
    password = load_password(config.username)
    if password is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "password missing in keyring")

    device_id = load_device_id(config.username)
    try:
        with DSMClient(config.base_url) as client:
            client.login(
                config.username,
                password,
                device_id=device_id,
                device_name=DEVICE_NAME if device_id else None,
            )
            if not path:
                items = client.list_shares()
                # list_share 응답을 list 형태와 비슷하게 정규화
                return {
                    "path": "",
                    "items": [
                        {"name": s.get("name"), "path": s.get("path"), "isdir": True}
                        for s in items
                    ],
                }
            else:
                files = client.list_folder(path)
                return {
                    "path": path,
                    "items": [
                        {
                            "name": f.get("name"),
                            "path": f.get("path"),
                            "isdir": bool(f.get("isdir")),
                            "size": f.get("additional", {}).get("size"),
                        }
                        for f in files
                    ],
                }
    except DSMError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def remove(session: Session = Depends(get_session)) -> None:
    if not clear(session):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no NAS config saved")
