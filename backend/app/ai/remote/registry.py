"""외부 비전 LLM 모델 레지스트리.

각 모델은 (provider, 가격, 어댑터 클래스)로 등록.
provider는 keyring 슬롯명과 일치 (anthropic / openai / google).
가격은 USD/1M 토큰 (input, output) — 운영 시점 공식 가격으로 주기적 동기화 필요.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    provider: str  # 'anthropic' | 'openai' | 'google'
    input_price: float  # USD per 1M input tokens
    output_price: float  # USD per 1M output tokens


# 가격은 2026 시점 공개 가격 기준 — Anthropic / OpenAI / Google 공식 페이지 참조 후 갱신.
MODELS: dict[str, ModelInfo] = {
    # Anthropic Claude
    "claude-opus-4-7": ModelInfo("anthropic", 15.0, 75.0),
    "claude-sonnet-4-6": ModelInfo("anthropic", 3.0, 15.0),
    "claude-haiku-4-5": ModelInfo("anthropic", 0.80, 4.0),
    # OpenAI
    "gpt-4o": ModelInfo("openai", 2.50, 10.0),
    "gpt-4o-mini": ModelInfo("openai", 0.15, 0.60),
    # Google Gemini
    "gemini-2.5-pro": ModelInfo("google", 1.25, 10.0),
    "gemini-2.5-flash": ModelInfo("google", 0.15, 0.60),
}

# 텍스트-only 분석(공모전 테마 추출 등)에 권장되는 저렴한 모델 — provider별
TEXT_DEFAULTS: dict[str, str] = {
    "anthropic": "claude-haiku-4-5",
    "openai": "gpt-4o-mini",
    "google": "gemini-2.5-flash",
}


def get_provider(model: str) -> str | None:
    info = MODELS.get(model)
    return info.provider if info else None


def get_price(model: str) -> tuple[float, float]:
    info = MODELS.get(model)
    if info is None:
        # 알 수 없는 모델 — sonnet 가격으로 보수적 추정
        info = MODELS["claude-sonnet-4-6"]
    return info.input_price, info.output_price


def make_adapter(model: str, api_key: str):
    """provider에 맞는 AdvancedReviewModel 인스턴스 생성."""
    info = MODELS.get(model)
    if info is None:
        raise ValueError(f"unknown model: {model}")
    if info.provider == "anthropic":
        from .claude import ClaudeVisionReview

        return ClaudeVisionReview(api_key=api_key, model=model)
    if info.provider == "openai":
        from .openai_vision import OpenAIVisionReview

        return OpenAIVisionReview(api_key=api_key, model=model)
    if info.provider == "google":
        from .gemini_vision import GeminiVisionReview

        return GeminiVisionReview(api_key=api_key, model=model)
    raise ValueError(f"unsupported provider: {info.provider}")
