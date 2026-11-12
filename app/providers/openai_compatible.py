"""Chat provider for any server that speaks the OpenAI-style chat API.

Works with local Ollama (http://localhost:11434/v1) and with most cloud
services, by changing only the base URL, model name and key.
"""

from __future__ import annotations

import httpx

from .base import Message, ProviderError


class OpenAICompatibleChat:
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

        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        # Error messages below never include the key or request headers.
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions", json=payload, headers=headers
                )
        except httpx.ConnectError as exc:
            raise ProviderError(
                f"Could not reach the model server at {self._base_url}. "
                "If you use Ollama, check that it is running."
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "The model took too long to answer. Try again, use a smaller "
                "model, or raise LLM_TIMEOUT in your .env file."
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("The request to the model server failed.") from exc

        if response.status_code == 401:
            raise ProviderError("The model server rejected the API key (LLM_API_KEY).")
        if response.status_code == 404:
            raise ProviderError(
                f"Model '{self._model}' was not found on the server. "
                f"With Ollama, run: ollama pull {self._model}"
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"The model server returned an error (HTTP {response.status_code})."
            )

        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("The model server sent an unexpected reply.") from exc
        return content or ""
