"""Builds the configured providers. Register new provider types here."""

from __future__ import annotations

from ..config import Settings, get_settings
from .base import ChatProvider, ProviderError, SpeechToText, TextToSpeech
from .faster_whisper import FasterWhisperTranscription
from .openai_compatible import (
    OpenAICompatibleChat,
    OpenAICompatibleSpeech,
    OpenAICompatibleTranscription,
)


def _openai_compatible_chat(settings: Settings) -> ChatProvider:
    return OpenAICompatibleChat(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout=settings.llm_timeout,
        context_tokens=settings.llm_context_tokens,
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


def _faster_whisper(settings: Settings) -> SpeechToText:
    return FasterWhisperTranscription(model=settings.stt_model, device=settings.stt_device)


def _openai_compatible_transcription(settings: Settings) -> SpeechToText:
    if not settings.stt_base_url or not settings.stt_model:
        raise ProviderError(
            "STT_PROVIDER is 'openai_compatible' but STT_BASE_URL or STT_MODEL "
            "is missing in your .env file."
        )
    return OpenAICompatibleTranscription(
        base_url=settings.stt_base_url,
        model=settings.stt_model,
        api_key=settings.stt_api_key,
        timeout=settings.stt_timeout,
    )


CHAT_PROVIDERS = {"openai_compatible": _openai_compatible_chat}
SPEECH_PROVIDERS = {"openai_compatible": _openai_compatible_speech}
TRANSCRIPTION_PROVIDERS = {
    "faster_whisper": _faster_whisper,
    "openai_compatible": _openai_compatible_transcription,
}


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


def get_transcription_provider() -> SpeechToText:
    settings = get_settings()
    build = _pick(TRANSCRIPTION_PROVIDERS, settings.stt_provider, "STT_PROVIDER")
    return build(settings)
