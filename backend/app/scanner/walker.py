"""사진 소스 추상화.

Walker는 (1) 폴더를 walk해서 파일 메타데이터를 yield하고, (2) 경로로 바이트를 읽는다.
LocalWalker / DSMWalker가 동일 인터페이스를 구현하므로 스캐너 본체는 소스에 무관.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class FileEntry:
    path: str
    size_bytes: int
    mtime: datetime  # tz-aware UTC


class Walker(Protocol):
    nas_id: str

    def walk(self, root: str) -> Iterator[FileEntry]: ...

    def read(self, path: str) -> bytes: ...
