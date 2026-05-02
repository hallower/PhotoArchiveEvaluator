"""Anthropic Claude vision 어댑터 (AdvancedReviewModel).

지원 모델
- claude-opus-4-7   (최고 품질, 비싸요)
- claude-sonnet-4-6 (기본 — 균형)
- claude-haiku-4-5  (저렴·빠름)

비용 추정
- 이미지 token ≈ (width × height) / 750  (Anthropic 공식 근사)
- 입력 = 이미지 + prompt(작음)
- 출력 = max_tokens (상한)
"""

from __future__ import annotations

import base64
import logging

from ..base import AdvancedReviewModel, ReviewResult

log = logging.getLogger(__name__)

# USD per 1M tokens — input, output (대략적인 값. 실제는 운영 시점 가격 확인)
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-7": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (0.80, 4.0),
}

DEFAULT_MAX_OUTPUT = 1024


class ClaudeVisionReview(AdvancedReviewModel):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        from anthropic import Anthropic

        self._client = Anthropic(api_key=api_key)
        self._model = model
        self.model_id = f"claude:{model}"

    def review(self, image: bytes, prompt: str) -> ReviewResult:
        b64 = base64.b64encode(image).decode("ascii")
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=DEFAULT_MAX_OUTPUT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        usage = msg.usage
        cost = self._calc_cost(usage.input_tokens, usage.output_tokens)
        return ReviewResult(
            model_id=self.model_id,
            response=text,
            cost_usd=cost,
            tokens_in=int(usage.input_tokens),
            tokens_out=int(usage.output_tokens),
        )

    def estimate_cost(
        self,
        image_width: int,
        image_height: int,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT,
    ) -> float:
        # 이미지 토큰 근사 + prompt 100t 가정
        image_tokens = max(1, (image_width * image_height) // 750)
        in_tokens = image_tokens + 100
        return self._calc_cost(in_tokens, max_output_tokens)

    def _calc_cost(self, tokens_in: int, tokens_out: int) -> float:
        in_p, out_p = PRICING.get(self._model, PRICING["claude-sonnet-4-6"])
        return (tokens_in * in_p + tokens_out * out_p) / 1_000_000
