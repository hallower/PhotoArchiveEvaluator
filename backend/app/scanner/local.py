"""로컬 디스크 폴더 스캐너.

LocalWalker(파일 시스템 walk + read)를 _runner.run_scan에 전달한다.
DSM 어댑터(scanner/dsm.py)는 동일 흐름을 DSMWalker로 사용.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ._runner import run_scan
from .walker import FileEntry

log = logging.getLogger(__name__)

JPG_SUFFIXES = {".jpg", ".jpeg"}


class LocalWalker:
    nas_id: str

    def __init__(self, nas_id: str = "local") -> None:
        self.nas_id = nas_id

    def walk(self, root: str) -> Iterator[FileEntry]:
        for p in Path(root).rglob("*"):
            try:
                if not (p.is_file() and p.suffix.lower() in JPG_SUFFIXES):
                    continue
                st = p.stat()
            except OSError as exc:
                log.warning("walk error %s: %s", p, exc)
                continue
            yield FileEntry(
                path=str(p),
                size_bytes=st.st_size,
                mtime=datetime.fromtimestamp(int(st.st_mtime), tz=timezone.utc),
            )

    def read(self, path: str) -> bytes:
        return Path(path).read_bytes()


class LocalScanner:
    """로컬 폴더 스캐너. 외부 API는 기존과 동일하게 유지."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        nas_id: str = "local",
    ) -> None:
        self._session_factory = session_factory
        self._walker = LocalWalker(nas_id=nas_id)

    @property
    def nas_id(self) -> str:
        return self._walker.nas_id

    def scan(self, root: str | Path) -> int:
        return run_scan(self._session_factory, self._walker, str(root))
