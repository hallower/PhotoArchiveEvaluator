"""DSM 클라이언트 — 프로세스 전역 공유 단일 세션.

Synology DSM은 동일 계정의 동시 로그인이 들어오면 이전 SID를 무효화한다.
또한 짧은 시간에 여러 번 로그인하면 IP/계정이 자동 차단될 수 있다.
따라서 NAS 부하를 최소화하기 위해 **프로세스당 1개의 DSMClient를 공유**하고,
SID 만료 시에만 자동 재로그인한다.

사용:
- `with open_dsm_client(session) as c:` 형태의 기존 호출자는 변경 없이 동작.
  단, 종료 시 logout/close 하지 않는다 — 공유 객체이기 때문.
- 명시적으로 클라이언트를 얻고 싶으면 `get_shared_client()`.
- 자격증명/연결을 강제로 갱신하려면 `reset_shared_client()`.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session

from .credentials import DEVICE_NAME, load_config, load_device_id, load_password
from .dsm import DSMClient

log = logging.getLogger(__name__)

_lock = threading.Lock()
_client: DSMClient | None = None


def _build_logged_in_client() -> DSMClient:
    from ..storage.db import SessionLocal

    with SessionLocal() as s:
        config = load_config(s)
    if config is None:
        raise RuntimeError("NAS not configured — POST /api/nas/setup or scripts.nas_login")
    password = load_password(config.username)
    if not password:
        raise RuntimeError("DSM password missing in OS keyring")
    device_id = load_device_id(config.username)

    c = DSMClient(config.base_url)
    c.mark_shared()
    c.login(
        config.username,
        password,
        device_id=device_id,
        device_name=DEVICE_NAME if device_id else None,
    )
    return c


def get_shared_client() -> DSMClient:
    """프로세스 전역 공유 DSMClient. 첫 호출 시 lazy login. 만료 시 자동 재로그인은 DSMClient 내부에서 처리."""
    global _client
    if _client is not None and _client.authenticated:
        return _client
    with _lock:
        if _client is not None and _client.authenticated:
            return _client
        if _client is not None:
            try:
                _client.close()
            except Exception:  # noqa: BLE001
                pass
            _client = None
        _client = _build_logged_in_client()
        log.info("DSM shared client initialized")
        return _client


def reset_shared_client() -> None:
    """현재 공유 클라이언트를 종료. 자격증명·DSM 설정 변경 시 호출."""
    global _client
    with _lock:
        if _client is None:
            return
        try:
            _client.close()
        except Exception:  # noqa: BLE001
            pass
        _client = None
        log.info("DSM shared client reset")


@contextmanager
def open_dsm_client(session: Session | None = None) -> Iterator[DSMClient]:
    """기존 caller 호환 API. `with open_dsm_client(...) as c:` 형태로 사용.

    내부적으로는 공유 클라이언트를 반환하며 종료 시 close/logout 하지 않는다.
    `session` 파라미터는 시그니처 호환용으로만 유지(내부에서 SessionLocal 사용).
    """
    yield get_shared_client()
