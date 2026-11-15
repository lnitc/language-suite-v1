"""Shadowing (listen and repeat), with a fake model."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers.base import ProviderError
from app.providers.factory import get_chat_provider


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


SENTENCES = json.dumps(
    {"language_code": "en-US", "sentences": ["She sells sea shells.", "The weather is rather warm.", "Extra.", "Too many."]}
)


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(fake):
    app.dependency_overrides[get_chat_provider] = lambda: fake


def start(client, **overrides):
    body = {"language": "English", "difficulty": "elementary", "count": 3}
    body.update(overrides)
    return client.post("/api/shadowing/sessions", json=body)


def test_sentences_attempts_and_summary(client):
    fake = FakeChat([SENTENCES, "**Practise** the th sound."])
    use(fake)
    started = start(client, session_prompt="Tongue twisters", system_prompt="You are Coach Kim.").json()
    assert started["sentences"] == ["She sells sea shells.", "The weather is rather warm.", "Extra."]
    assert started["language_code"] == "en-US"
    system, user = fake.calls[0]
    assert system["content"] == "You are Coach Kim."
    assert "Write 3 separate sentences in English" in user["content"]
    assert "Tongue twisters" in user["content"] and "CEFR A2" in user["content"]

    url = f"/api/shadowing/sessions/{started['session_id']}"
    first = client.post(f"{url}/attempts", json={"index": 1, "text": "the weather is rather worm"}).json()
    assert (first["attempt"], first["percent"], first["best_percent"]) == (1, 80, 80)
    assert [t["text"] for t in first["expected"] if not t["ok"]] == ["warm."]
    assert [t["text"] for t in first["heard"] if not t["ok"]] == ["worm"]
    # A worse second try does not replace the best one; a better one does.
    worse = client.post(f"{url}/attempts", json={"index": 1, "text": "the feather"}).json()
    assert (worse["attempt"], worse["percent"], worse["best_percent"]) == (2, 20, 80)
    client.post(f"{url}/attempts", json={"index": 0, "text": "She sells sea shells"})
    assert len(fake.calls) == 1  # marking attempts needs no model

    result = client.post(f"{url}/finish").json()
    assert [(row["attempts"], row["best_percent"], row["missed"]) for row in result["sentences"]] == [
        (1, 100, []), (2, 80, ["warm"]), (0, None, []),
    ]
    assert (result["average"], result["practised"]) == (90, 2)  # the unpractised sentence is not counted
    assert result["missed_words"] == ["warm"] and result["tips"] == "Practise the th sound."
    tips_prompt = fake.calls[1][1]["content"]
    assert "warm" in tips_prompt and "You did not hear the learner" in tips_prompt
    assert client.post(f"{url}/finish").json() == result and len(fake.calls) == 2

    # Another attempt afterwards refreshes the summary.
    client.post(f"{url}/attempts", json={"index": 1, "text": "The weather is rather warm"})
    again = client.post(f"{url}/finish").json()
    assert again["average"] == 100 and again["tips"] == "" and len(fake.calls) == 2  # nothing missed: no tips call


def test_own_material_and_japanese_marking(client):
    fake = FakeChat([json.dumps({"language_code": "ja-JP", "sentences": ["今日は天気がいいです。"]}), ProviderError("offline")])
    use(fake)
    started = start(client, language="Japanese", count=1, material="今日は天気がいいです。\n明日は雨です。").json()
    prompt = fake.calls[0][1]["content"]
    assert "take 1 sentences in Japanese" in prompt and "Copy them exactly" in prompt and "明日は雨です" in prompt
    url = f"/api/shadowing/sessions/{started['session_id']}"
    attempt = client.post(f"{url}/attempts", json={"index": 0, "text": "今日は天気はいいです"}).json()
    assert (attempt["percent"], attempt["joiner"]) == (90, "")
    result = client.post(f"{url}/finish").json()
    assert result["missed_words"] == ["が"] and result["tips"] == ""  # the tips failed; the summary stands


def test_errors(client):
    use(FakeChat(["not json"]))
    assert start(client).status_code == 502
    assert start(client, count=11).status_code == 422
    use(FakeChat([SENTENCES, "Tips."]))
    sid = start(client, count=1).json()["session_id"]
    assert client.post(f"/api/shadowing/sessions/{sid}/attempts", json={"index": 3, "text": "x"}).status_code == 404
    assert client.post("/api/shadowing/sessions/nope/finish").status_code == 404
    empty = client.post(f"/api/shadowing/sessions/{sid}/attempts", json={"index": 0, "text": ""}).json()
    assert empty["percent"] == 0
    assert client.post(f"/api/shadowing/sessions/{sid}/finish").json()["average"] == 0
