"""Synology DSM Web API (FileStation) 클라이언트.

사용 API
- SYNO.API.Auth (login/logout) — 세션 sid 발급
- SYNO.FileStation.List — list_share / list / getinfo
- SYNO.FileStation.Download — 파일 스트리밍

레퍼런스
- Synology File Station Official API Guide

세션 관리
- login()으로 sid 획득. close() 또는 with 블록으로 logout.
- 세션 만료(에러 코드 105/106/119) 시 호출자가 재로그인을 트리거.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import httpx

log = logging.getLogger(__name__)


# DSM Auth / FileStation 에러 코드 (전체는 공식 문서 참조)
DSM_ERROR_CODES: dict[int, str] = {
    100: "Unknown error",
    101: "Invalid parameter",
    102: "API does not exist",
    103: "Method does not exist",
    104: "Version not supported",
    105: "Insufficient privilege / not logged in",
    106: "Session timeout",
    107: "Session interrupted by duplicate login",
    119: "SID not found",
    400: "No such file or directory",
    401: "Invalid file type",
    402: "File access denied",
    403: "File path too long",
    404: "Internal error (FileStation)",
    405: "File already exists",
    406: "Disk quota exceeded",
    407: "Out of internal disk space",
    408: "Out of external disk space",
    409: "Request data limit exceeded",
    # Auth-specific
    400_001: "No such account or incorrect password",  # placeholder — 실제 코드는 400 계열 + 메시지로 구분
}

# Auth 에러는 별도 매핑 (DSM은 auth 카테고리에 다른 코드 셋 사용)
AUTH_ERROR_CODES: dict[int, str] = {
    400: "No such account or incorrect password",
    401: "Account disabled",
    402: "Permission denied",
    403: "2-step verification code required",
    404: "Failed to authenticate 2-step verification code",
    406: "Enforce to authenticate with 2-factor authentication code",
}


class DSMError(Exception):
    """DSM API가 success=false로 응답한 경우."""

    def __init__(self, code: int, *, category: str = "general"):
        self.code = code
        self.category = category
        msg_table = AUTH_ERROR_CODES if category == "auth" else DSM_ERROR_CODES
        message = msg_table.get(code, f"unknown error ({code})")
        super().__init__(f"DSM[{category}] {code}: {message}")


class DSMClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        verify: bool = True,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            verify=verify,
        )
        self._sid: str | None = None
        self._device_id: str | None = None

    # ─── 컨텍스트 매니저 ────────────────────────────────────────────────

    def __enter__(self) -> DSMClient:
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._sid:
                self.logout()
        finally:
            self._client.close()

    # ─── 인증 ────────────────────────────────────────────────────────────

    def login(
        self,
        username: str,
        password: str,
        *,
        otp_code: str | None = None,
        device_id: str | None = None,
        device_name: str | None = None,
        enable_device_token: bool = False,
    ) -> None:
        """SYNO.API.Auth login.

        2FA 계정:
          - 최초: otp_code 전달 + enable_device_token=True → 응답의 did를 self.device_id로 받아
                  키체인 등에 보관해두면 다음부터는 OTP 없이 로그인.
          - 이후: device_id + device_name 전달 (otp_code 불필요).
        """
        params: dict[str, str] = {
            "api": "SYNO.API.Auth",
            "version": "7",
            "method": "login",
            "account": username,
            "passwd": password,
            "session": "FileStation",
            "format": "sid",
        }
        if otp_code:
            params["otp_code"] = otp_code
        if device_id:
            params["device_id"] = device_id
        if device_name:
            params["device_name"] = device_name
        if enable_device_token:
            params["enable_device_token"] = "yes"

        resp = self._client.post(f"{self.base_url}/webapi/entry.cgi", data=params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise DSMError(data.get("error", {}).get("code", -1), category="auth")
        payload = data.get("data", {})
        self._sid = payload["sid"]
        self._device_id = payload.get("did")
        log.info(
            "DSM login ok: %s sid=...%s did=%s",
            self.base_url,
            self._sid[-6:],
            "yes" if self._device_id else "no",
        )

    @property
    def device_id(self) -> str | None:
        """로그인 후 응답의 did. enable_device_token=True일 때만 채워진다."""
        return self._device_id

    def logout(self) -> None:
        if not self._sid:
            return
        try:
            self._client.get(
                f"{self.base_url}/webapi/entry.cgi",
                params={
                    "api": "SYNO.API.Auth",
                    "version": "7",
                    "method": "logout",
                    "session": "FileStation",
                    "_sid": self._sid,
                },
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("logout error (ignored): %s", exc)
        self._sid = None

    @property
    def authenticated(self) -> bool:
        return self._sid is not None

    # ─── FileStation ────────────────────────────────────────────────────

    def list_shares(self) -> list[dict[str, Any]]:
        data = self._call("SYNO.FileStation.List", 2, "list_share")
        return data.get("shares", [])

    def list_folder(
        self,
        folder_path: str,
        offset: int = 0,
        limit: int = 1000,
        with_size: bool = True,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "folder_path": folder_path,
            "offset": offset,
            "limit": limit,
        }
        if with_size:
            params["additional"] = '["size","time","real_path"]'
        data = self._call("SYNO.FileStation.List", 2, "list", **params)
        return data.get("files", [])

    def walk(
        self,
        folder_path: str,
        suffixes: tuple[str, ...] = (".jpg", ".jpeg"),
    ) -> Iterator[dict[str, Any]]:
        """folder_path 하위를 재귀 walk. 파일 항목만 yield (additional에 size/time 포함)."""
        offset = 0
        page = 1000
        while True:
            files = self.list_folder(folder_path, offset=offset, limit=page)
            if not files:
                break
            for item in files:
                if item.get("isdir"):
                    yield from self.walk(item["path"], suffixes=suffixes)
                else:
                    name = item.get("name", "").lower()
                    if not suffixes or name.endswith(suffixes):
                        yield item
            if len(files) < page:
                break
            offset += page

    def download(self, path: str) -> bytes:
        params = {
            "api": "SYNO.FileStation.Download",
            "version": "2",
            "method": "download",
            "path": path,
            "mode": "open",
            "_sid": self._sid,
        }
        resp = self._client.get(f"{self.base_url}/webapi/entry.cgi", params=params)
        resp.raise_for_status()
        return resp.content

    def stream_download(self, path: str, chunk_size: int = 1 << 16) -> Iterator[bytes]:
        """대용량 파일은 chunk 스트림으로."""
        params = {
            "api": "SYNO.FileStation.Download",
            "version": "2",
            "method": "download",
            "path": path,
            "mode": "open",
            "_sid": self._sid,
        }
        with self._client.stream("GET", f"{self.base_url}/webapi/entry.cgi", params=params) as resp:
            resp.raise_for_status()
            yield from resp.iter_bytes(chunk_size=chunk_size)

    # ─── 내부 ────────────────────────────────────────────────────────────

    def _call(
        self,
        api: str,
        version: int,
        method: str,
        **params: Any,
    ) -> dict[str, Any]:
        if not self._sid:
            raise RuntimeError("not logged in — call login() first")
        all_params: dict[str, Any] = {
            "api": api,
            "version": str(version),
            "method": method,
            "_sid": self._sid,
            **{k: str(v) for k, v in params.items()},
        }
        resp = self._client.get(f"{self.base_url}/webapi/entry.cgi", params=all_params)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"):
            raise DSMError(data.get("error", {}).get("code", -1))
        return data.get("data", {})


def query_api_info(base_url: str, timeout: float = 5.0) -> dict[str, Any]:
    """인증 없이 호출 가능. 도달성 + 사용 가능 API 메타데이터 확인."""
    url = (
        f"{base_url.rstrip('/')}/webapi/query.cgi"
        "?api=SYNO.API.Info&version=1&method=query"
        "&query=SYNO.API.Auth,SYNO.FileStation.List,SYNO.FileStation.Download"
    )
    with httpx.Client(timeout=timeout, follow_redirects=True) as c:
        resp = c.get(url)
        resp.raise_for_status()
        return resp.json()
