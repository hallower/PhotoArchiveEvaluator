"""CLIP zero-shot 태깅.

기존 저장된 CLIP 이미지 임베딩을 재사용해 추가 GPU forward 없이 태그 산출.
사전 정의된 사진 어휘(~150개)에 대한 cosine similarity로 top-K 추출.

Worker가 평가 직후 호출하며, 같은 image_emb.vector를 입력으로 받는다.
"""

from __future__ import annotations

import logging

import numpy as np

from ..base import TagItem, TagResult
from ..embed import EmbeddingModel  # noqa: F401  — type hint

log = logging.getLogger(__name__)

MODEL_ID = "clip-tagger"
MODEL_VERSION = "vit-l-14"

# 사진 라이브러리 분류용 어휘. 영어 권장 (CLIP 정확도)
TAG_VOCABULARY: tuple[str, ...] = (
    # 인물
    "portrait of a person", "group of people", "child", "baby", "couple",
    "elderly person", "selfie",
    # 풍경
    "landscape", "mountain view", "ocean", "beach", "river", "lake",
    "forest", "field", "sunset", "sunrise", "blue sky", "cloudy sky",
    "stars at night", "moon",
    # 도시
    "cityscape", "street scene", "building exterior", "architecture",
    "skyscraper", "monument", "neon lights at night", "traffic", "alley",
    "rooftop view",
    # 시간·조명
    "indoor scene", "outdoor scene", "night photography", "daylight scene",
    "golden hour lighting", "blue hour", "backlit subject",
    # 음식·실내
    "food on plate", "dessert", "drink in glass", "coffee cup",
    "cafe interior", "restaurant interior",
    # 동물·자연
    "cat", "dog", "bird", "wildlife animal", "flower close-up",
    "tree", "garden", "leaves",
    # 사물
    "car", "bicycle", "boat on water", "train",
    # 분위기·스타일
    "black and white photograph", "vintage photo", "minimalist composition",
    "vibrant colors", "monochrome", "dramatic lighting", "soft natural light",
    "high contrast",
    # 활동·이벤트
    "concert performance", "wedding ceremony", "celebration party",
    "sports activity", "travel destination", "documentary photography",
    "street art", "festival",
    # 기타
    "abstract pattern", "still life", "macro detail", "silhouette",
    "reflection in water", "snow scene", "rain",
)


class CLIPTagger:
    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION

    def __init__(
        self,
        embed_model,
        vocabulary: tuple[str, ...] = TAG_VOCABULARY,
        threshold: float = 0.20,
        top_k: int = 8,
    ) -> None:
        self._embed = embed_model
        self._vocab = vocabulary
        self._threshold = threshold
        self._top_k = top_k

        # 텍스트 임베딩을 1회 미리 계산하고 stack
        log.info("precomputing %d tag embeddings...", len(vocabulary))
        vectors = []
        for term in vocabulary:
            r = embed_model.embed_text(term)
            vectors.append(np.frombuffer(r.vector, dtype=np.float32))
        self._tag_matrix = np.stack(vectors)  # (N, dim)

    def tag_from_embedding(self, image_vector: bytes) -> TagResult:
        """이미지 임베딩 bytes만으로 태그 — 추가 CLIP forward 없음."""
        img_vec = np.frombuffer(image_vector, dtype=np.float32)
        sims = self._tag_matrix @ img_vec  # (N,)
        sorted_idx = np.argsort(-sims)

        items: list[TagItem] = []
        for i in sorted_idx[: self._top_k]:
            sim = float(sims[i])
            if sim < self._threshold:
                break
            items.append(TagItem(name=self._vocab[i], confidence=sim))

        return TagResult(tags=items, model_id=self.model_id, model_version=self.model_version)

    def tag_from_image(self, image: bytes) -> TagResult:
        """raw bytes에서 시작하는 fallback — embedding을 먼저 계산."""
        emb = self._embed.embed_image(image)
        return self.tag_from_embedding(emb.vector)
