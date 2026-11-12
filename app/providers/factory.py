"""Builds the configured providers. Register new provider types here."""

from __future__ import annotations

from ..config import Settings, get_settings
from .base import ChatProvider, ProviderError
from .openai_compatible import OpenAICompatibleChat


def _openai_compatible(settings: Settings) -> ChatProvider:
    return OpenAICompatibleChat(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout,
    )


CHAT_PROVIDERS = {
    "openai_compatible": _openai_compatible,
}


def get_chat_provider() -> ChatProvider:
    settings = get_settings()
    try:
        build = CHAT_PROVIDERS[settings.llm_provider]
    except KeyError:
        known = ", ".join(sorted(CHAT_PROVIDERS))
        raise ProviderError(
            f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Available: {known}."
        ) from None
    return build(settings)
