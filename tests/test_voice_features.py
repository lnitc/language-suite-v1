"""Conversation, interview, interpreter and the speech endpoints, with fakes."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers.base import ProviderError
from app.providers.factory import (
    get_chat_provider,
    get_speech_provider,
    get_transcription_provider,
)


class FakeChat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def chat(self, messages, *, json_mode=False, temperature=0.7):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeEar:
    def __init__(self):
        self.heard = []

    async def transcribe(self, audio, *, language=None, content_type="audio/webm"):
        self.heard.append((audio, language, content_type))
        return "  hello there  "


class FakeMouth:
    media_type = "audio/wav"

    async def synthesize(self, text, *, language=None, voice=None):
        return f"{language}:{text}".encode()


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(chat=None, ear=None, mouth=None):
    app.dependency_overrides[get_chat_provider] = lambda: chat
    app.dependency_overrides[get_transcription_provider] = lambda: ear
    app.dependency_overrides[get_speech_provider] = lambda: mouth


OPENING = json.dumps({"language_code": "es-ES", "say": "**Hola!** ¿Cómo estás?"})


# ---------- speech endpoints ----------

def test_transcribe_passes_audio_and_two_letter_language(client):
    ear = FakeEar()
    use(ear=ear)
    response = client.post(
        "/api/speech/transcribe?language=ja-JP",
        content=b"fake-audio",
        headers={"Content-Type": "audio/webm;codecs=opus"},
    )
    assert response.json() == {"text": "hello there"}
    assert ear.heard == [(b"fake-audio", "ja", "audio/webm")]

    client.post("/api/speech/transcribe?language=<bad>", content=b"x")
    assert ear.heard[-1][1] is None  # unknown code: let the ear detect the language
    assert client.post("/api/speech/transcribe", content=b"").status_code == 400


def test_synthesize_only_with_a_speech_server(client):
    use(mouth=None)
    body = {"text": "Hola.", "language_code": "es-ES"}
    assert client.post("/api/speech/synthesize", json=body).status_code == 404
    use(mouth=FakeMouth())
    response = client.post("/api/speech/synthesize", json=body)
    assert response.content == b"es-ES:Hola."
    assert response.headers["content-type"] == "audio/wav"


def test_local_whisper_missing_gives_install_hint(monkeypatch):
    import asyncio
    import sys

    from app.providers.faster_whisper import FasterWhisperTranscription

    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # pretend it is not installed
    with pytest.raises(ProviderError, match="requirements-voice.txt"):
        asyncio.run(FasterWhisperTranscription(model="unused-test-model").transcribe(b"x"))


# ---------- conversation ----------

def start_talk(client, **overrides):
    body = {"kind": "conversation", "language": "Spanish", "difficulty": "beginner"}
    body.update(overrides)
    return client.post("/api/talk/sessions", json=body)


def test_conversation_flow_and_feedback(client):
    fake = FakeChat([OPENING, "Muy bien. ¿Qué te gusta hacer?", "Good work.\nTip: verbs."])
    use(chat=fake)
    started = start_talk(
        client, system_prompt="You are Ana.", session_prompt="Talk about hobbies", material="fútbol, cine"
    ).json()
    assert started["reply"] == "Hola! ¿Cómo estás?"  # markdown removed for the voice
    assert started["language_code"] == "es-ES"
    system = fake.calls[0][0]["content"]
    assert system.startswith("You are Ana.")
    assert "Talk about hobbies" in system and "fútbol, cine" in system and "CEFR A1" in system

    url = f"/api/talk/sessions/{started['session_id']}"
    turn = client.post(f"{url}/turns", json={"text": "Estoy bien"}).json()
    assert turn == {"reply": "Muy bien. ¿Qué te gusta hacer?", "done": False, "turn": 1}
    # The model sees clean history: no JSON instruction from the opening call.
    sent = fake.calls[1]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[2]["content"] == "Hola! ¿Cómo estás?" and sent[3]["content"] == "Estoy bien"

    result = client.post(f"{url}/finish").json()
    assert result["feedback"] == "Good work.\nTip: verbs."
    assert [row["speaker"] for row in result["transcript"]] == ["Teacher", "Learner", "Teacher"]
    assert "Learner: Estoy bien" in fake.calls[2][1]["content"]
    assert client.post(f"{url}/finish").json() == result  # cached, no new model call
    assert client.post(f"{url}/turns", json={"text": "más"}).status_code == 409


def test_failed_turn_can_be_repeated(client):
    fake = FakeChat([OPENING, ProviderError("model offline"), "Vale."])
    use(chat=fake)
    url = f"/api/talk/sessions/{start_talk(client).json()['session_id']}"
    assert client.post(f"{url}/turns", json={"text": "Hola"}).status_code == 502
    assert client.post(f"{url}/turns", json={"text": "Hola"}).json()["turn"] == 1
    assert len(fake.calls[2]) == 4  # the failed turn left nothing behind


def test_finish_without_speaking_needs_no_model(client):
    fake = FakeChat([OPENING])
    use(chat=fake)
    url = f"/api/talk/sessions/{start_talk(client).json()['session_id']}"
    assert "Nothing was said" in client.post(f"{url}/finish").json()["feedback"]
    assert len(fake.calls) == 1


def test_image_material_is_attached_for_the_model(client):
    fake = FakeChat([OPENING])
    use(chat=fake)
    image = "data:image/png;base64,AAAA"
    assert start_talk(client, image=image).status_code == 200
    parts = fake.calls[0][1]["content"]
    assert parts[1] == {"type": "image_url", "image_url": {"url": image}}
    assert start_talk(client, image="not-an-image").status_code == 422


def test_plain_text_opening_is_accepted_and_bad_input_rejected(client):
    use(chat=FakeChat(["Hola, bienvenido."]))
    started = start_talk(client).json()
    assert (started["reply"], started["language_code"]) == ("Hola, bienvenido.", "")
    assert start_talk(client, difficulty="strict").status_code == 422  # interview-only value


# ---------- interview ----------

def test_interview_counts_questions_and_closes(client):
    fake = FakeChat([OPENING, "Question two?", "Thank you, goodbye.", "Solid interview."])
    use(chat=fake)
    started = start_talk(client, kind="interview", difficulty="strict", question_count=2).json()
    assert started["question_count"] == 2
    system = fake.calls[0][0]["content"]
    assert "strict interviewer" in system and "exactly 2 questions" in system
    assert "question 1 of 2" in fake.calls[0][1]["content"]

    url = f"/api/talk/sessions/{started['session_id']}"
    first = client.post(f"{url}/turns", json={"text": "I led a team."}).json()
    assert (first["done"], first["turn"]) == (False, 1)
    assert "ask question 2 of 2" in fake.calls[1][-1]["content"]

    last = client.post(f"{url}/turns", json={"text": "I want to grow."}).json()
    assert last["done"] is True
    assert "last answer" in fake.calls[2][-1]["content"]
    # Stage directions are not stored: the earlier answer is kept clean.
    assert fake.calls[2][3]["content"] == "I led a team."

    result = client.post(f"{url}/finish").json()
    assert result["feedback"] == "Solid interview."
    assert "how to answer that question better" in fake.calls[3][1]["content"]
    assert result["transcript"][1] == {"speaker": "Candidate", "text": "I led a team."}


# ---------- interpreter ----------

TEXT = json.dumps(
    {
        "source_language_code": "en-US",
        "target_language_code": "ja-JP",
        "sentences": ["One.", "Two.", "Three.", "Four.", "Five."],
    }
)
REVIEW = json.dumps(
    {
        "batches": [{"ideal": "一。二。", "comment": "Good."}, {"ideal": "三。四。", "comment": "Missed four."}],
        "overall": "Keep going.",
    }
)


def test_interpreter_batches_and_feedback(client):
    fake = FakeChat([TEXT, REVIEW])
    use(chat=fake)
    started = client.post(
        "/api/interpreter/sessions",
        json={
            "source_language": "English",
            "target_language": "Japanese",
            "sentences_per_batch": 2,
            "batch_count": 2,
            "session_prompt": "A factory tour",
        },
    ).json()
    assert started["batches"] == ["One. Two.", "Three. Four."]  # trimmed to 2 x 2
    assert (started["source_language_code"], started["target_language_code"]) == ("en-US", "ja-JP")
    assert "exactly 4 sentences" in fake.calls[0][1]["content"]
    assert "A factory tour" in fake.calls[0][1]["content"]

    url = f"/api/interpreter/sessions/{started['session_id']}/submit"
    result = client.post(url, json={"interpretations": ["一、二"]}).json()
    assert result["overall"] == "Keep going."
    assert result["batches"][0] == {
        "number": 1, "original": "One. Two.", "interpretation": "一、二", "ideal": "一。二。", "comment": "Good.",
    }
    assert result["batches"][1]["interpretation"] == ""
    assert "(nothing said)" in fake.calls[1][1]["content"]
    assert client.post(url, json={"interpretations": []}).json() == result
    assert len(fake.calls) == 2


def test_interpreter_bad_feedback_can_be_retried(client):
    use(chat=FakeChat([TEXT, "not json", REVIEW]))
    sid = client.post(
        "/api/interpreter/sessions",
        json={"source_language": "English", "target_language": "Japanese", "batch_count": 2},
    ).json()["session_id"]
    url = f"/api/interpreter/sessions/{sid}/submit"
    assert client.post(url, json={"interpretations": ["a", "b"]}).status_code == 502
    assert client.post(url, json={"interpretations": ["a", "b"]}).json()["overall"] == "Keep going."


def test_vocabulary_returns_language_codes_for_voice_mode(client):
    words = json.dumps(
        {
            "source_language_code": "en-US",
            "target_language_code": "es-ES",
            "items": [{"word": "dog", "translations": ["perro"]}],
        }
    )
    use(chat=FakeChat([words]))
    started = client.post(
        "/api/vocabulary/sessions",
        json={"source_language": "English", "target_language": "Spanish", "count": 1},
    ).json()
    assert (started["source_language_code"], started["target_language_code"]) == ("en-US", "es-ES")


def test_local_whisper_decodes_a_recording_and_skips_silence(monkeypatch):
    """Runs the real audio decoding (needs the optional voice install)."""
    pytest.importorskip("av")
    import asyncio
    import io
    import math
    import struct
    import wave

    from app.providers import faster_whisper as fw

    def wav(seconds, rate=44100):
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as out:
            out.setnchannels(2)
            out.setsampwidth(2)
            out.setframerate(rate)
            frames = int(seconds * rate)
            out.writeframes(
                b"".join(struct.pack("<hh", *[int(9000 * math.sin(i / 20))] * 2) for i in range(frames))
            )
        return buffer.getvalue()

    samples = fw.decode_recording(wav(1.0))
    assert samples.dtype.name == "float32" and samples.ndim == 1
    assert abs(samples.shape[0] - fw.SAMPLE_RATE) < 800  # stereo 44.1 kHz -> mono 16 kHz
    assert 0.1 < float(abs(samples).max()) <= 1.0

    class FakeSegment:
        text = " hola "

    class FakeModel:
        def __init__(self):
            self.calls = []

        def transcribe(self, audio, language=None, vad_filter=False):
            self.calls.append((audio.shape[0], language, vad_filter))
            return iter([FakeSegment(), FakeSegment()]), None

    model = FakeModel()
    monkeypatch.setitem(fw._models, ("test-model", "cpu"), model)
    ear = fw.FasterWhisperTranscription(model="test-model")
    assert asyncio.run(ear.transcribe(wav(1.0), language="es")) == "hola hola"
    assert model.calls[0][1:] == ("es", True)
    assert asyncio.run(ear.transcribe(wav(0.05))) == ""  # too short: model not called
    assert len(model.calls) == 1
    with pytest.raises(ProviderError, match="could not be read"):
        asyncio.run(ear.transcribe(b"not audio"))
