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


@dataclass(frozen=True)
class ReviewResult:
    model_id: str
    response: str
    cost_usd: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None


@dataclass(frozen=True)
class CaptionResult:
    caption: str
    lang: str
    model_id: str
    model_version: str


@runtime_checkable
class CaptionModel(Protocol):
    model_id: str
    model_version: str

    def caption(self, image: bytes) -> CaptionResult: ...


@dataclass(frozen=True)
class TagItem:
    name: str
    confidence: float


@dataclass(frozen=True)
class TagResult:
    tags: list[TagItem]
    model_id: str
    model_version: str


@runtime_checkable
class TagModel(Protocol):
    model_id: str
    model_version: str

    def tag_from_image(self, image: bytes) -> TagResult: ...


@runtime_checkable
class AdvancedReviewModel(Protocol):
    """외부 비전 LLM 기반 상세 리뷰. SPEC §6.3."""

    model_id: str

    def review(self, image: bytes, prompt: str) -> ReviewResult: ...

    def estimate_cost(
        self, image_width: int, image_height: int, max_output_tokens: int
    ) -> float: ...
