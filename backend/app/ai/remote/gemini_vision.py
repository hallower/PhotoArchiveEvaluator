"""Google Gemini vision 어댑터 (google-genai SDK).

지원 모델
- gemini-2.5-pro    (고품질)
- gemini-2.5-flash  (저렴·빠름)

google-genai (1.x) 사용 — 구 google-generativeai와는 다른 패키지.
"""

from __future__ import annotations

import logging

from ..base import AdvancedReviewModel, ReviewResult
from .registry import get_price

log = logging.getLogger(__name__)

DEFAULT_MAX_OUTPUT = 1024


class GeminiVisionReview(AdvancedReviewModel):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        from google import genai

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self.model_id = f"gemini:{model}"

    def review(self, image: bytes, prompt: str) -> ReviewResult:
        from google.genai import types

        config = types.GenerateContentConfig(max_output_tokens=DEFAULT_MAX_OUTPUT)
        response = self._client.models.generate_content(
            model=self._model,
            contents=[
                types.Part.from_bytes(data=image, mime_type="image/jpeg"),
                prompt,
            ],
            config=config,
        )
        text = response.text or ""
        usage = response.usage_metadata
        in_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
        out_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
        in_p, out_p = get_price(self._model)
        cost = (in_tokens * in_p + out_tokens * out_p) / 1_000_000
        return ReviewResult(
            model_id=self.model_id,
            response=text.strip(),
            cost_usd=cost,
            tokens_in=in_tokens,
            tokens_out=out_tokens,
        )

    def estimate_cost(
        self,
        image_width: int,
        image_height: int,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT,
    ) -> float:
        # Gemini는 이미지를 768px 단위 tile로 ~258 토큰씩 카운트.
        tiles_w = max(1, image_width // 768) + 1
        tiles_h = max(1, image_height // 768) + 1
        image_tokens = tiles_w * tiles_h * 258
        in_tokens = image_tokens + 100
        in_p, out_p = get_price(self._model)
        return (in_tokens * in_p + max_output_tokens * out_p) / 1_000_000
