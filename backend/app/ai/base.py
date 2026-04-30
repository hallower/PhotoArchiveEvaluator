"""AI 어댑터 인터페이스.

SPEC §6.3의 4종 인터페이스 중 ScoreModel을 1차로 정의한다.
나머지(CaptionModel, EmbeddingModel, AdvancedReviewModel)는 Phase 2 이후 추가.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ScoreResult:
    score: float
    """정규화 점수. 1.0 - 5.0"""

    raw_score: float
    """모델 원본 출력 (모델별 스케일이 다를 수 있음)"""

    confidence: float
    """0.0 - 1.0. 모델이 미제공하면 1.0"""

    model_id: str
    model_version: str


@runtime_checkable
class ScoreModel(Protocol):
    model_id: str
    model_version: str

    def score(self, image: bytes) -> ScoreResult:
        """JPEG 바이트를 받아 미학 점수를 반환한다."""
        ...
