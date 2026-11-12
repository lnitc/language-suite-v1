"""The three "sockets" of the app: brain, ear and mouth.

Features only ever talk to these interfaces, never to a specific vendor.
To support a new service, add one file that implements the interface and
register it in ``factory.py``.
"""

from __future__ import annotations

from typing import Protocol, TypedDict


class Message(TypedDict):
    role: str  # "system" | "user" | "assistant"
    # Plain text, or OpenAI-style parts when an image is attached:
    # [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "data:..."}}]
    content: str | list[dict]


class ProviderError(Exception):
    """A provider failed. The message is safe to show to the user."""


class ChatProvider(Protocol):
    """Brain: turns a conversation into a reply."""

    async def chat(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.7,
    ) -> str: ...


class SpeechToText(Protocol):
    """Ear: turns recorded audio into text."""

    async def transcribe(
        self,
        audio: bytes,
        *,
        language: str | None = None,  # two-letter code such as "ja", or None to detect
        content_type: str = "audio/webm",
    ) -> str: ...


class TextToSpeech(Protocol):
    """Mouth: turns text into audio."""

    media_type: str  # e.g. "audio/wav"

    async def synthesize(
        self, text: str, *, language: str | None = None, voice: str | None = None
    ) -> bytes: ...
