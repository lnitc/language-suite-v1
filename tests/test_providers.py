"""The OpenAI-compatible provider, tested against a pretend server."""

import asyncio
import json

import httpx
import pytest

from app.main import app
from app.providers.base import ProviderError
from app.providers.openai_compatible import OpenAICompatibleChat

FAKE_KEY = "test-key-not-real"


def make(handler, api_key=""):
    return OpenAICompatibleChat(
        base_url="http://model.test/v1/",
        model="some-model",
        api_key=api_key,
        transport=httpx.MockTransport(handler),
    )


def ask(provider, **kwargs):
    return asyncio.run(provider.chat([{"role": "user", "content": "hi"}], **kwargs))


def test_sends_openai_style_request_and_reads_reply():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    assert ask(make(handler, api_key=FAKE_KEY), json_mode=True) == "hello"
    assert seen["url"] == "http://model.test/v1/chat/completions"
    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    assert seen["body"]["model"] == "some-model"
    assert seen["body"]["response_format"] == {"type": "json_object"}


def test_no_auth_header_without_key():
    def handler(request):
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    assert ask(make(handler)) == "ok"


@pytest.mark.parametrize(
    "status, expected", [(401, "API key"), (404, "ollama pull some-model"), (500, "HTTP 500")]
)
def test_http_errors_become_friendly_messages_without_the_key(status, expected):
    provider = make(lambda request: httpx.Response(status, text=FAKE_KEY), api_key=FAKE_KEY)
    with pytest.raises(ProviderError) as error:
        ask(provider)
    assert expected in str(error.value)
    assert FAKE_KEY not in str(error.value)


def test_unreachable_server_mentions_ollama():
    def handler(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderError, match="Ollama"):
        ask(make(handler))


def test_health_never_exposes_the_key(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("LLM_API_KEY", FAKE_KEY)
    response = TestClient(app).get("/api/health")
    assert response.json()["llm_key_set"] is True
    assert FAKE_KEY not in response.text


# ---------- speech ----------

def test_speech_sends_openai_style_request_and_returns_audio():
    from app.providers.openai_compatible import OpenAICompatibleSpeech

    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"RIFFaudio")

    speech = OpenAICompatibleSpeech(
        base_url="http://speech.test/v1",
        model="some-voice-model",
        voice="Freya",
        api_key=FAKE_KEY,
        transport=httpx.MockTransport(handler),
    )
    assert asyncio.run(speech.synthesize("Hello.")) == b"RIFFaudio"
    assert seen["url"] == "http://speech.test/v1/audio/speech"
    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    assert seen["body"] == {
        "model": "some-voice-model",
        "input": "Hello.",
        "response_format": "wav",
        "voice": "Freya",
    }


def test_speech_factory(monkeypatch):
    from app.providers.factory import get_speech_provider

    monkeypatch.setenv("TTS_PROVIDER", "browser")
    assert get_speech_provider() is None

    monkeypatch.setenv("TTS_PROVIDER", "openai_compatible")
    monkeypatch.setenv("TTS_BASE_URL", "")
    with pytest.raises(ProviderError, match="TTS_BASE_URL"):
        get_speech_provider()

    monkeypatch.setenv("TTS_PROVIDER", "nonsense")
    with pytest.raises(ProviderError, match="browser"):
        get_speech_provider()


def test_transcription_uploads_audio_and_reads_text():
    from app.providers.openai_compatible import OpenAICompatibleTranscription

    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.content
        return httpx.Response(200, json={"text": " konnichiwa "})

    ear = OpenAICompatibleTranscription(
        base_url="http://ear.test/v1",
        model="some-ear-model",
        api_key=FAKE_KEY,
        transport=httpx.MockTransport(handler),
    )
    text = asyncio.run(ear.transcribe(b"AUDIOBYTES", language="ja", content_type="audio/ogg"))
    assert text == "konnichiwa"
    assert seen["url"] == "http://ear.test/v1/audio/transcriptions"
    assert seen["auth"] == f"Bearer {FAKE_KEY}"
    assert b"AUDIOBYTES" in seen["body"] and b'filename="speech.ogg"' in seen["body"]
    assert b"some-ear-model" in seen["body"] and b"ja" in seen["body"]


def test_transcription_factory(monkeypatch):
    from app.providers.factory import get_transcription_provider
    from app.providers.faster_whisper import FasterWhisperTranscription

    monkeypatch.setenv("STT_PROVIDER", "faster_whisper")
    assert isinstance(get_transcription_provider(), FasterWhisperTranscription)  # loads nothing yet

    monkeypatch.setenv("STT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("STT_BASE_URL", "")
    with pytest.raises(ProviderError, match="STT_BASE_URL"):
        get_transcription_provider()
