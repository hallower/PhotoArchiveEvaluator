"""텍스트-only 외부 LLM 호출 — 공모전 분석, 번역 등 vision 없는 작업에 사용.

provider별 SDK를 지연 import해서 미설치 환경에서도 모듈 로딩이 깨지지 않게 한다.
"""

from __future__ import annotations

from typing import Tuple


def call_text_llm(
    provider: str,
    model: str,
    api_key: str,
    prompt: str,
    *,
    max_tokens: int = 512,
) -> Tuple[str, int | None, int | None]:
    """텍스트 only 호출. (response_text, tokens_in, tokens_out) 반환."""
    if provider == "anthropic":
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return (
            text,
            getattr(msg.usage, "input_tokens", None),
            getattr(msg.usage, "output_tokens", None),
        )

    if provider == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        return (
            text,
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "completion_tokens", None),
        )

    if provider == "google":
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=[prompt],
            config=types.GenerateContentConfig(max_output_tokens=max_tokens),
        )
        usage = response.usage_metadata
        return (
            response.text or "",
            getattr(usage, "prompt_token_count", None),
            getattr(usage, "candidates_token_count", None),
        )

    raise ValueError(f"unsupported provider: {provider}")
