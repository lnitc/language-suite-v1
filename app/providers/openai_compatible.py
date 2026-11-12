"""Providers for any server that speaks the OpenAI-style API.

Works with local Ollama (http://localhost:11434/v1) and with most cloud
services, by changing only the base URL, model name and key.
"""

from __future__ import annotations

import httpx

from .base import Message, ProviderError


async def _post(
    *,
    base_url: str,
    path: str,
    payload: dict,
    api_key: str,
    timeout: float,
    transport: httpx.AsyncBaseTransport | None,
    model: str,
    what: str,
) -> httpx.Response:
    """POST with friendly errors. Messages never include the key or headers."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(f"{base_url}{path}", json=payload, headers=headers)
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

    if response.status_code == 401:
        raise ProviderError(f"The {what} server rejected the API key.")
    if response.status_code == 404:
        raise ProviderError(
            f"Model '{model}' was not found on the {what} server. "
            f"With Ollama, run: ollama pull {model}"
        )
    if response.status_code >= 400:
        raise ProviderError(
            f"The {what} server returned an error (HTTP {response.status_code})."
        )
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
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

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
