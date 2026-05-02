"""외부 AI API 키체인 보관.

provider 이름(anthropic, openai, google) 단위로 키를 별도 슬롯에 저장.
DB에는 어떤 provider의 키가 등록됐는지만 표시(키 자체는 키체인 외부 노출 X).
"""

from __future__ import annotations

import keyring

KEYRING_SERVICE = "PhotoArchiveEvaluator-API"

KNOWN_PROVIDERS = ("anthropic", "openai", "google")


def get(provider: str) -> str | None:
    return keyring.get_password(KEYRING_SERVICE, provider)


def set_key(provider: str, key: str) -> None:
    keyring.set_password(KEYRING_SERVICE, provider, key)


def delete(provider: str) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, provider)
    except keyring.errors.PasswordDeleteError:
        pass


def configured_providers() -> list[str]:
    """현재 키가 저장된 provider 목록."""
    return [p for p in KNOWN_PROVIDERS if get(p)]
