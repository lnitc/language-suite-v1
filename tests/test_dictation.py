"""Dictation tests. No model or speech engine needed: fakes are plugged in."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers.base import ProviderError
from app.providers.factory import get_chat_provider, get_speech_provider
from app.textutils import compare


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


class FakeSpeech:
    media_type = "audio/wav"

    def __init__(self):
        self.spoken = []

    async def synthesize(self, text, *, language=None, voice=None):
        self.spoken.append((text, language))
        return b"RIFF-fake-audio-" + text.encode()


TEXT = json.dumps(
    {
        "language_code": "en-US",
        "sentences": ["The cat sat on the mat.", "It was a sunny day!", "Extra one.", "Too many."],
    }
)


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(chat, speech=None):
    app.dependency_overrides[get_chat_provider] = lambda: chat
    app.dependency_overrides[get_speech_provider] = lambda: speech


def start(client, **overrides):
    body = {"language": "English", "difficulty": "beginner", "length": "short"}
    body.update(overrides)
    return client.post("/api/dictation/sessions", json=body)


# ---------- marking ----------

def test_compare_ignores_case_and_punctuation():
    result = compare("The cat sat on the mat.", "the cat sat on the mat")
    assert (result["correct"], result["total"]) == (6, 6)
    assert all(token["ok"] for token in result["expected"] + result["typed"])


def test_compare_marks_wrong_missing_and_extra_words():
    result = compare("The cat sat on the mat.", "The cat sit on mat today")
    assert [t["text"] for t in result["expected"] if not t["ok"]] == ["sat", "the"]
    assert [t["text"] for t in result["typed"] if not t["ok"]] == ["sit", "today"]
    assert (result["correct"], result["total"], result["joiner"]) == (4, 6, " ")


def test_compare_empty_answer():
    result = compare("Hello there.", "")
    assert (result["correct"], result["total"], result["typed"]) == (0, 2, [])


def test_compare_japanese_is_character_based():
    result = compare("今日は天気がいいです。", "今日は天気はいいです")
    assert result["joiner"] == ""
    assert (result["correct"], result["total"]) == (9, 10)
    assert [t["text"] for t in result["expected"] if not t["ok"]] == ["が"]


# ---------- sessions ----------

def test_browser_mode_full_session(client):
    fake = FakeChat([TEXT, "Watch your verb endings."])
    use(fake)

    started = start(client, system_prompt="Be strict.", session_prompt="About cats").json()
    assert started["total"] == 3  # "short" keeps three sentences
    assert started["speech"]["mode"] == "browser"
    assert started["speech"]["language_code"] == "en-US"
    assert started["speech"]["texts"][0] == "The cat sat on the mat."
    system, user = fake.calls[0]
    assert system["content"] == "Be strict."
    assert "About cats" in user["content"] and "CEFR A1" in user["content"]

    url = f"/api/dictation/sessions/{started['session_id']}"
    assert client.get(f"{url}/audio/0").status_code == 404  # no server speech

    result = client.post(
        f"{url}/submit", json={"answers": ["the cat sat on the mat", "It was a sunny"]}
    ).json()
    assert [(s["correct"], s["total"]) for s in result["sentences"]] == [(6, 6), (4, 5), (0, 2)]
    assert (result["correct"], result["total"], result["accuracy"]) == (10, 13, 77)
    assert result["feedback"] == "Watch your verb endings."
    # Only the sentences with mistakes are sent to the teacher.
    feedback_prompt = fake.calls[1][1]["content"]
    assert "It was a sunny day!" in feedback_prompt
    assert "The cat sat on the mat." not in feedback_prompt

    # Submitting again returns the same result without new model calls.
    assert client.post(f"{url}/submit", json={"answers": []}).json() == result
    assert len(fake.calls) == 2


def test_perfect_dictation_needs_no_feedback_call(client):
    fake = FakeChat([TEXT])
    use(fake)
    sid = start(client).json()["session_id"]
    result = client.post(
        f"/api/dictation/sessions/{sid}/submit",
        json={"answers": ["The cat sat on the mat", "it was a sunny day", "extra one"]},
    ).json()
    assert result["accuracy"] == 100
    assert "Perfect" in result["feedback"]
    assert len(fake.calls) == 1


def test_marking_survives_feedback_failure(client):
    use(FakeChat([TEXT, ProviderError("model offline")]))
    sid = start(client).json()["session_id"]
    result = client.post(f"/api/dictation/sessions/{sid}/submit", json={"answers": ["x"]}).json()
    assert result["feedback"] is None
    assert result["total"] == 13


def test_server_mode_audio_is_generated_once_and_text_stays_hidden(client):
    speech = FakeSpeech()
    use(FakeChat([TEXT]), speech)
    started = start(client).json()
    assert started["speech"] == {"mode": "server", "language_code": "en-US"}

    url = f"/api/dictation/sessions/{started['session_id']}/audio"
    first = client.get(f"{url}/1")
    assert first.headers["content-type"] == "audio/wav"
    assert first.content == b"RIFF-fake-audio-It was a sunny day!"
    assert client.get(f"{url}/1").content == first.content  # "repeat"
    assert speech.spoken == [("It was a sunny day!", "en-US")]
    assert client.get(f"{url}/9").status_code == 404


def test_bad_model_output_and_bad_language_code(client):
    use(FakeChat(["I refuse."]))
    response = start(client)
    assert response.status_code == 502
    assert "dictation text" in response.json()["detail"]

    use(FakeChat([json.dumps({"language_code": "<script>", "sentences": ["Hi there."]})]))
    assert start(client).json()["speech"]["language_code"] == ""


def test_validation(client):
    use(FakeChat([]))
    assert start(client, difficulty="impossible").status_code == 422
    assert start(client, language="").status_code == 422
    assert client.post("/api/dictation/sessions/nope/submit", json={"answers": []}).status_code == 404
