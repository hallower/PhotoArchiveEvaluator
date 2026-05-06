"""OpenAI GPT-4o vision 어댑터.

지원 모델
- gpt-4o      (높은 품질)
- gpt-4o-mini (저렴)

이미지 토큰 산출은 OpenAI의 detail 모드에 따라 다르며, 정확한 추정 어려움.
보수적 근사: (w * h) / 1500 + 100 (high detail에 가까움).
"""

from __future__ import annotations

import base64
import logging

from ..base import AdvancedReviewModel, ReviewResult
from .registry import get_price

log = logging.getLogger(__name__)

DEFAULT_MAX_OUTPUT = 1024


class OpenAIVisionReview(AdvancedReviewModel):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model
        self.model_id = f"openai:{model}"

    def review(self, image: bytes, prompt: str) -> ReviewResult:
        b64 = base64.b64encode(image).decode("ascii")
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=DEFAULT_MAX_OUTPUT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        in_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        out_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
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
        # OpenAI image tile 기반 토큰화. high-detail은 ~85 + 170/tile.
        # 거친 근사: (w*h)/1500 + 100
        image_tokens = max(85, (image_width * image_height) // 1500)
        in_tokens = image_tokens + 100
        in_p, out_p = get_price(self._model)
        return (in_tokens * in_p + max_output_tokens * out_p) / 1_000_000
