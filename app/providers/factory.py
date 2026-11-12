"""Builds the configured providers. Register new provider types here."""

from __future__ import annotations

from ..config import Settings, get_settings
from .base import ChatProvider, ProviderError, TextToSpeech
from .openai_compatible import OpenAICompatibleChat, OpenAICompatibleSpeech


def _openai_compatible_chat(settings: Settings) -> ChatProvider:
    return OpenAICompatibleChat(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout,
    )


def _openai_compatible_speech(settings: Settings) -> TextToSpeech:
    if not settings.tts_base_url or not settings.tts_model:
        raise ProviderError(
            "TTS_PROVIDER is 'openai_compatible' but TTS_BASE_URL or TTS_MODEL "
            "is missing in your .env file."
        )
    return OpenAICompatibleSpeech(
        base_url=settings.tts_base_url,
        model=settings.tts_model,
        voice=settings.tts_voice,
        api_key=settings.tts_api_key,
        timeout=settings.tts_timeout,
    )


CHAT_PROVIDERS = {"openai_compatible": _openai_compatible_chat}
SPEECH_PROVIDERS = {"openai_compatible": _openai_compatible_speech}


def _pick(registry: dict, name: str, setting: str, extra: tuple[str, ...] = ()):
    try:
        return registry[name]
    except KeyError:
        known = ", ".join(sorted((*registry, *extra)))
        raise ProviderError(f"Unknown {setting} '{name}'. Available: {known}.") from None


def get_chat_provider() -> ChatProvider:
    settings = get_settings()
    return _pick(CHAT_PROVIDERS, settings.llm_provider, "LLM_PROVIDER")(settings)


def get_speech_provider() -> TextToSpeech | None:
    """Returns None for 'browser': the browser's own voices speak the text."""
    settings = get_settings()
    if settings.tts_provider == "browser":
        return None
    build = _pick(SPEECH_PROVIDERS, settings.tts_provider, "TTS_PROVIDER", ("browser",))
    return build(settings)
