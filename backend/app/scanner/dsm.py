"""Synology DSM (FileStation) 스캐너.

DSMWalker는 DSM 클라이언트로 폴더를 walk하고 파일을 download한다.
DSMScanner는 스캔 시작 시 로그인하고, 종료 시 logout/close.

세션 1회로 스캔 전체를 처리해 NAS 부하·재로그인 비용을 최소화.

**동시성 정책**: 동일 NAS host에 대해 동시에 여러 스캔이 로그인하면 Synology가
이전 SID를 무효화(에러 107: Session interrupted by duplicate login)하기 때문에
host별로 직렬화한다. 또한 같은 (nas_id, root)가 이미 진행 중이면 중복 스캔을 건너뛴다.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..nas.credentials import DSMConfig
from ..nas.dsm import DSMClient
from ..nas.session import get_shared_client
from ._runner import run_scan
from .walker import FileEntry

log = logging.getLogger(__name__)


# host(예: "192.168.0.222:5000")별로 동시 1개의 스캔만 허용.
# 여러 폴더 스캔이 큐잉되면 락 대기로 순차 실행된다.
_HOST_LOCKS: dict[str, threading.Lock] = {}
_HOST_LOCKS_GUARD = threading.Lock()

# 진행 중인 (nas_id, root) 조합. 중복 스캔 요청을 차단한다.
_ACTIVE_SCANS: set[tuple[str, str]] = set()
_ACTIVE_GUARD = threading.Lock()


def _get_host_lock(host: str) -> threading.Lock:
    with _HOST_LOCKS_GUARD:
        lock = _HOST_LOCKS.get(host)
        if lock is None:
            lock = threading.Lock()
            _HOST_LOCKS[host] = lock
        return lock


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
        # 중복 스캔 차단: 같은 (nas_id, root) 조합이 이미 돌고 있으면 곧바로 종료.
        key = (self.nas_id, root)
        with _ACTIVE_GUARD:
            if key in _ACTIVE_SCANS:
                log.info("DSM scan already running, skip duplicate: %s %s", *key)
                return -1
            _ACTIVE_SCANS.add(key)

        host = _host_label(self._config.base_url)
        host_lock = _get_host_lock(host)
        try:
            # host 단위 직렬화: 한 번에 하나의 스캔만 walk·download 하도록 (네트워크 부하 제어).
            # 로그인은 프로세스 전역 공유 DSMClient가 1번만 처리한다.
            with host_lock:
                client = get_shared_client()
                walker = DSMWalker(client, nas_id=self.nas_id)
                return run_scan(self._session_factory, walker, root)
        finally:
            with _ACTIVE_GUARD:
                _ACTIVE_SCANS.discard(key)
