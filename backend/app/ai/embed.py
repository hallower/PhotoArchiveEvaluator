"""임베딩 모델 인터페이스 + 헬퍼.

이미지/텍스트를 동일 임베딩 공간으로 사상하는 모델(CLIP/SigLIP 류)을 다룬다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np


@dataclass(frozen=True)
class EmbeddingResult:
    vector: bytes  # float32 packed, L2-normalized
    dim: int
    model_id: str
    model_version: str


@runtime_checkable
class EmbeddingModel(Protocol):
    model_id: str
    model_version: str
    dim: int

    def embed_image(self, image: bytes) -> EmbeddingResult: ...
    def embed_text(self, text: str) -> EmbeddingResult: ...


def cosine_similarity(a: bytes, b: bytes) -> float:
    """두 정규화된 벡터(bytes)의 cosine similarity."""
    va = np.frombuffer(a, dtype=np.float32)
    vb = np.frombuffer(b, dtype=np.float32)
    return float(va @ vb)
