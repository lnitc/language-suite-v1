"""Speech (public speaking), with a fake model."""

import json

import pytest
from fastapi.testclient import TestClient

from app.features.public_speaking import MAX_TRANSCRIPT_CHARS, language_code_for, pace
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


REVIEW = json.dumps(
    {
        "language_code": "en-GB",
        "scores": {
            "content": {"score": 4, "comment": "Clear message."},
            "structure": {"score": 2, "comment": "No real ending."},
            "language": {"score": 3, "comment": "Some tense slips."},
            "impact": "n/a",
        },
        "feedback": "**Good start.**\n\nYou ran short: add an example.",
        "corrections": [
            {"original": "I am agree", "better": "I agree", "explanation": "No 'am' with agree."},
            {"original": "same", "better": "same", "explanation": "no change"},
        ],
    }
)
TRANSCRIPT = "Good morning everyone. Today I want to talk about my town. I am agree that it is small but it is friendly."


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(fake):
    app.dependency_overrides[get_chat_provider] = lambda: fake


def start(client, **overrides):
    body = {"language": "English", "difficulty": "intermediate", "minutes": 2}
    body.update(overrides)
    return client.post("/api/speaking/sessions", json=body)


def test_language_codes_and_pace():
    assert [language_code_for(n) for n in ("English", " japanese ", "日本語", "Spanish (Mexico)", "Klingon", "")] == [
        "en-US", "ja-JP", "ja-JP", "es-ES", "", "",
    ]
    assert pace("one two three four five six", 12) == {"unit": "words", "count": 6, "per_minute": 30}
    assert pace("今日は、天気がいいです。", 60) == {"unit": "characters", "count": 10, "per_minute": 10}
    assert pace("too short to time", 2)["per_minute"] is None


def test_assignment_then_review_with_timing_and_sample_script(client):
    fake = FakeChat(["**Introduce your home town** to visitors. Cover: location, food.", REVIEW, "Good morning. Let me take you to my town."])
    use(fake)
    started = start(client, session_prompt="Travel", system_prompt="You are Coach Lee.").json()
    assert started["assignment"] == "Introduce your home town to visitors. Cover: location, food."
    assert (started["language_code"], started["target_seconds"], started["max_seconds"]) == ("en-US", 120, 180)
    system, user = fake.calls[0]
    assert system["content"] == "You are Coach Lee."
    assert "about 2 minutes" in user["content"] and "Travel" in user["content"] and "CEFR B1" in user["content"]

    url = f"/api/speaking/sessions/{started['session_id']}/submit"
    result = client.post(url, json={"transcript": TRANSCRIPT, "seconds": 45}).json()
    assert [(row["name"], row["score"]) for row in result["scores"]] == [
        ("Content and message", 4), ("Structure", 2), ("Language", 3), ("Impact on the audience", None),
    ]
    assert (result["total"], result["max_total"]) == (9, 15)
    assert result["feedback"] == "Good start.\n\nYou ran short: add an example."
    assert result["corrections"] == [{"original": "I am agree", "better": "I agree", "explanation": "No 'am' with agree."}]
    assert result["sample"] == "Good morning. Let me take you to my town."
    assert result["pace"] == {"unit": "words", "count": 22, "per_minute": 29}
    assert (result["seconds"], result["target_seconds"], result["language_code"]) == (45, 120, "en-US")

    review_prompt = fake.calls[1][1]["content"]
    assert "meant to last about 2:00 and lasted 0:45, at about 29 words per minute" in review_prompt
    assert "You did not hear the speech" in review_prompt and "Introduce your home town" in review_prompt
    sample_prompt = fake.calls[2][1]["content"]
    assert "about 260 words" in sample_prompt and "about 600 characters" in sample_prompt and TRANSCRIPT in sample_prompt


def test_own_topic_unknown_language_and_repeat_logic(client):
    fake = FakeChat([REVIEW, ProviderError("model offline"), "Sample one.", REVIEW, "Sample two."])
    use(fake)
    started = start(client, with_assignment=False, language="Klingon", session_prompt="My hobby").json()
    assert (started["assignment"], started["language_code"]) == ("", "") and fake.calls == []
    url = f"/api/speaking/sessions/{started['session_id']}/submit"
    body = {"transcript": TRANSCRIPT, "seconds": 50}
    assert client.post(url, json=body).status_code == 502  # the sample script failed
    first = client.post(url, json=body).json()
    assert first["sample"] == "Sample one." and len(fake.calls) == 3  # the review was kept
    assert first["language_code"] == "en-GB"  # not in the list: taken from the model's reply
    assert "chose the topic themselves" in fake.calls[0][1]["content"] and "My hobby" in fake.calls[0][1]["content"]
    assert client.post(url, json=body).json() == first and len(fake.calls) == 3
    again = client.post(url, json={"transcript": TRANSCRIPT + " Thank you.", "seconds": 60}).json()
    assert again["sample"] == "Sample two." and len(fake.calls) == 5  # a new recording is marked afresh


def test_limits_and_errors(client):
    use(FakeChat(["not json"]))
    url = f"/api/speaking/sessions/{start(client, with_assignment=False).json()['session_id']}/submit"
    assert "too little speech" in client.post(url, json={"transcript": "Hi.", "seconds": 3}).json()["detail"]
    too_long = client.post(url, json={"transcript": "word " * (MAX_TRANSCRIPT_CHARS // 5 + 5), "seconds": 300})
    assert too_long.status_code == 422 and str(MAX_TRANSCRIPT_CHARS) in too_long.json()["detail"]
    bad = client.post(url, json={"transcript": TRANSCRIPT, "seconds": 30})
    assert bad.status_code == 502 and "usable review" in bad.json()["detail"]
    assert start(client, minutes=5).status_code == 422
    assert client.post("/api/speaking/sessions/nope/submit", json={"transcript": TRANSCRIPT}).status_code == 404
