"""Providers for any server that speaks the OpenAI-style API.

Works with local Ollama (http://localhost:11434/v1) and with most cloud
services, by changing only the base URL, model name and key.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from ..context import add_warning
from .base import Message, ProviderError

# Room kept free for the model's answer when judging whether a request fits.
ANSWER_RESERVE_TOKENS = 800


def estimate_tokens(messages: list[Message]) -> int:
    """A rough count of the tokens in a request. Exact counts depend on the
    model; this errs on the high side. Letters of alphabets come to about
    3.5 characters per token; kanji, kana and similar to about one each."""
    total = 0.0
    for message in messages:
        content = message["content"]
        parts = content if isinstance(content, list) else [{"type": "text", "text": content}]
        for part in parts:
            if part.get("type") == "image_url":
                total += 300
                continue
            text = str(part.get("text") or "")
            wide = sum(1 for char in text if ord(char) > 0x2E7F)
            total += wide * 1.1 + (len(text) - wide) / 3.5
        total += 4
    return int(total)


def _check_status(status: int, what: str, model: str) -> None:
    if status == 401:
        raise ProviderError(f"The {what} server rejected the API key.")
    if status == 404:
        raise ProviderError(
            f"Model '{model}' was not found on the {what} server. "
            f"With Ollama, run: ollama pull {model}"
        )
    if status >= 400:
        raise ProviderError(f"The {what} server returned an error (HTTP {status}).")


async def _post(
    *,
    base_url: str,
    path: str,
    payload: dict | None = None,
    api_key: str,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None,
    model: str,
    what: str,
    form: dict | None = None,
    files: dict | None = None,
) -> httpx.Response:
    """POST with friendly errors. Messages never include the key or headers."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            if files is not None:
                response = await client.post(
                    f"{base_url}{path}", data=form, files=files, headers=headers
                )
            else:
                response = await client.post(
                    f"{base_url}{path}", json=payload, headers=headers
                )
    except httpx.ConnectError as exc:
        raise ProviderError(
            f"Could not reach the {what} server at {base_url}. "
            "If it is a local server such as Ollama, check that it is running."
        ) from exc
    except httpx.TimeoutException as exc:
        raise ProviderError(
            f"The {what} server took too long to answer. Try again, use a "
            "smaller model, or raise the timeout in your .env file."
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderError(f"The request to the {what} server failed.") from exc

    _check_status(response.status_code, what, model)
    return response


class OpenAICompatibleChat:
    """Brain: POST {base_url}/chat/completions."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 120.0,
        context_tokens: int = 0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._context_tokens = context_tokens  # 0: unknown, no check
        self._transport = transport

    def _check_size(self, messages: list[Message]) -> None:
        """Local servers such as Ollama silently cut off a request that does
        not fit the model's context window. The app cannot prevent that, but
        it can tell the learner when it is likely."""
        if not self._context_tokens:
            return
        needed = estimate_tokens(messages)
        if needed + ANSWER_RESERVE_TOKENS > self._context_tokens:
            add_warning(
                f"This request is large for the model's working memory: about {needed} "
                f"tokens plus the answer, and the limit is set to {self._context_tokens}. "
                "The model may ignore part of the text, so check the result with care. "
                'See "Context window" in the README for how to raise the limit.'
            )

    async def chat_stream(
        self, messages: list[Message], *, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        """Like chat(), but yields the reply piece by piece as it is written."""
        self._check_size(messages)
        payload = {"model": self._model, "messages": messages, "temperature": temperature, "stream": True}
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                async with client.stream(
                    "POST", f"{self._base_url}/chat/completions", json=payload, headers=headers
                ) as response:
                    _check_status(response.status_code, "model", self._model)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            piece = json.loads(data)["choices"][0]["delta"].get("content") or ""
                        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                            continue
                        if piece:
                            yield piece
        except httpx.ConnectError as exc:
            raise ProviderError(
                f"Could not reach the model server at {self._base_url}. "
                "If it is a local server such as Ollama, check that it is running."
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "The model server took too long to answer. Try again, use a "
                "smaller model, or raise the timeout in your .env file."
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("The request to the model server failed.") from exc

    async def chat(
        self,
        messages: list[Message],
        *,
        json_mode: bool = False,
        temperature: float = 0.7,
    ) -> str:
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        self._check_size(messages)

        response = await _post(
            base_url=self._base_url,
            path="/chat/completions",
            payload=payload,
            api_key=self._api_key,
            timeout=self._timeout,
            transport=self._transport,
            model=self._model,
            what="model",
        )
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("The model server sent an unexpected reply.") from exc
        return content or ""


class OpenAICompatibleSpeech:
    """Mouth: POST {base_url}/audio/speech, returns WAV audio."""

    media_type = "audio/wav"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        voice: str = "",
        api_key: str = "",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._voice = voice
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    async def synthesize(
        self, text: str, *, language: str | None = None, voice: str | None = None
    ) -> bytes:
        payload = {"model": self._model, "input": text, "response_format": "wav"}
        if voice or self._voice:
            payload["voice"] = voice or self._voice
        response = await _post(
            base_url=self._base_url,
            path="/audio/speech",
            payload=payload,
            api_key=self._api_key,
            timeout=self._timeout,
            transport=self._transport,
            model=self._model,
            what="speech",
        )
        if not response.content:
            raise ProviderError("The speech server returned no audio.")
        return response.content


_AUDIO_EXTENSIONS = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}


class OpenAICompatibleTranscription:
    """Ear: POST {base_url}/audio/transcriptions (multipart upload)."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 120.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    async def transcribe(
        self,
        audio: bytes,
        *,
        language: str | None = None,
        content_type: str = "audio/webm",
    ) -> str:
        extension = _AUDIO_EXTENSIONS.get(content_type, "webm")
        form = {"model": self._model, "response_format": "json"}
        if language:
            form["language"] = language
        response = await _post(
            base_url=self._base_url,
            path="/audio/transcriptions",
            form=form,
            files={"file": (f"speech.{extension}", audio, content_type)},
            api_key=self._api_key,
            timeout=self._timeout,
            transport=self._transport,
            model=self._model,
            what="speech recognition",
        )
        try:
            return str(response.json()["text"]).strip()
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderError("The speech recognition server sent an unexpected reply.") from exc
