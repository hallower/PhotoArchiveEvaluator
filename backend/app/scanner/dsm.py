"""Synology DSM (FileStation) 스캐너.

DSMWalker는 DSM 클라이언트로 폴더를 walk하고 파일을 download한다.
DSMScanner는 스캔 시작 시 로그인하고, 종료 시 logout/close.

세션 1회로 스캔 전체를 처리해 NAS 부하·재로그인 비용을 최소화.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..nas.credentials import DEVICE_NAME, DSMConfig
from ..nas.dsm import DSMClient
from ._runner import run_scan
from .walker import FileEntry

log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _host_label(url: str) -> str:
    p = urlparse(url)
    return f"{p.hostname}:{p.port}" if p.port else (p.hostname or url)


class DSMWalker:
    """walk + read를 DSM 클라이언트에 위임."""

    def __init__(self, client: DSMClient, nas_id: str) -> None:
        self._client = client
        self.nas_id = nas_id

    def walk(self, root: str) -> Iterator[FileEntry]:
        for item in self._client.walk(root):
            add = item.get("additional", {}) or {}
            size = int(add.get("size") or 0)
            time_block = add.get("time") or {}
            mtime_unix = time_block.get("mtime")
            mtime = (
                datetime.fromtimestamp(int(mtime_unix), tz=timezone.utc)
                if mtime_unix is not None
                else _utc_now()
            )
            yield FileEntry(path=item["path"], size_bytes=size, mtime=mtime)

    def read(self, path: str) -> bytes:
        return self._client.download(path)


class DSMScanner:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        config: DSMConfig,
        password: str,
        device_id: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._config = config
        self._password = password
        self._device_id = device_id

    @property
    def nas_id(self) -> str:
        return f"dsm:{self._config.username}@{_host_label(self._config.base_url)}"

    def scan(self, root: str) -> int:
        with DSMClient(self._config.base_url) as c:
            c.login(
                self._config.username,
                self._password,
                device_id=self._device_id,
                device_name=DEVICE_NAME if self._device_id else None,
            )
            walker = DSMWalker(c, nas_id=self.nas_id)
            return run_scan(self._session_factory, walker, root)
