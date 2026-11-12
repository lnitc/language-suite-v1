"""The three "sockets" of the app: brain, ear and mouth.

Features only ever talk to these interfaces, never to a specific vendor.
To support a new service, add one file that implements the interface and
register it in ``factory.py``.
"""

from __future__ import annotations

from typing import Protocol, TypedDict


class Message(TypedDict):
    role: str  # "system" | "user" | "assistant"
    content: str


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
    """Ear: turns recorded audio into text. (Used from the voice features on.)"""

    async def transcribe(self, audio: bytes, *, language: str | None = None) -> str: ...


class TextToSpeech(Protocol):
    """Mouth: turns text into audio. (Used from the voice features on.)"""

    async def synthesize(
        self, text: str, *, language: str | None = None, voice: str | None = None
    ) -> bytes: ...
