"""Essay writing, with a fake model."""

import json

import pytest
from fastapi.testclient import TestClient

from app.features.essay import MAX_CHARS
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
        "scores": {
            "content": {"score": 4, "comment": "Answers the question."},
            "organization": {"score": "3", "comment": "**Needs** paragraphs."},
            "vocabulary": 9,
            "grammar": {"score": "good", "comment": "Tense slips."},
        },
        "feedback": "## Well done\n\nClear ideas.\n\n\nWatch your tenses.",
        "corrections": [
            {"original": "I goed to school", "corrected": "I went to school", "explanation": "Irregular past."},
            {"original": "same", "corrected": "same", "explanation": "not a change"},
            "junk",
        ],
    }
)
ESSAY = "I goed to school yesterday. It was a very interesting day for me."


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(fake):
    app.dependency_overrides[get_chat_provider] = lambda: fake


def start(client, **overrides):
    body = {"language": "English", "difficulty": "elementary"}
    body.update(overrides)
    return client.post("/api/essay/sessions", json=body)


def test_assignment_then_review_and_ideal_version(client):
    fake = FakeChat(["**Write about your school day.** Cover: lessons, friends.", REVIEW, "I went to school yesterday."])
    use(fake)
    started = start(client, system_prompt="You are Mr Lee.", session_prompt="School life").json()
    assert started["assignment"] == "Write about your school day. Cover: lessons, friends."
    assert (started["recommended_chars"], started["max_chars"]) == (2000, 5000)
    system, user = fake.calls[0]
    assert system["content"] == "You are Mr Lee."
    assert "School life" in user["content"] and "CEFR A2" in user["content"]

    result = client.post(f"/api/essay/sessions/{started['session_id']}/submit", json={"text": ESSAY}).json()
    assert [(row["name"], row["score"]) for row in result["scores"]] == [
        ("Content and task", 4),
        ("Organisation", 3),
        ("Vocabulary", 5),  # 9 is capped at the top of the scale
        ("Grammar and accuracy", None),  # "good" is not a number: not rated
    ]
    assert (result["total"], result["max_total"]) == (12, 15)  # only the rated criteria count
    assert result["scores"][1]["comment"] == "Needs paragraphs."
    assert result["feedback"] == "Well done\n\nClear ideas.\n\nWatch your tenses."
    assert result["corrections"] == [
        {"original": "I goed to school", "corrected": "I went to school", "explanation": "Irregular past."}
    ]
    assert result["ideal"] == "I went to school yesterday."
    assert result["essay"] == ESSAY and result["over_recommended"] is False
    # Both marking calls are given the assignment and the essay.
    for call in fake.calls[1:]:
        assert "Write about your school day." in call[1]["content"] and ESSAY in call[1]["content"]


def test_own_essay_needs_no_assignment(client):
    fake = FakeChat([REVIEW, "Ideal."])
    use(fake)
    started = start(client, with_assignment=False, session_prompt="My trip to Kyoto").json()
    assert started["assignment"] == "" and fake.calls == []
    client.post(f"/api/essay/sessions/{started['session_id']}/submit", json={"text": ESSAY})
    assert "without an assignment" in fake.calls[0][1]["content"]
    assert "My trip to Kyoto" in fake.calls[0][1]["content"]


def test_failed_ideal_version_keeps_the_review_and_rewrites_are_marked_afresh(client):
    fake = FakeChat([REVIEW, ProviderError("model offline"), "Ideal one.", REVIEW, "Ideal two."])
    use(fake)
    url = f"/api/essay/sessions/{start(client, with_assignment=False).json()['session_id']}/submit"
    assert client.post(url, json={"text": ESSAY}).status_code == 502
    first = client.post(url, json={"text": ESSAY}).json()
    assert first["ideal"] == "Ideal one." and len(fake.calls) == 3  # the review was not repeated
    assert client.post(url, json={"text": ESSAY}).json() == first and len(fake.calls) == 3

    second = client.post(url, json={"text": ESSAY + " I liked it."}).json()
    assert second["ideal"] == "Ideal two." and len(fake.calls) == 5


def test_length_limits_and_bad_review(client):
    use(FakeChat(["not json at all", REVIEW, "Ideal."]))
    url = f"/api/essay/sessions/{start(client, with_assignment=False).json()['session_id']}/submit"
    assert "too short" in client.post(url, json={"text": "Hi."}).json()["detail"]
    too_long = client.post(url, json={"text": "word " * (MAX_CHARS // 5 + 10)})
    assert too_long.status_code == 422 and str(MAX_CHARS) in too_long.json()["detail"]
    bad = client.post(url, json={"text": ESSAY})
    assert bad.status_code == 502 and "usable review" in bad.json()["detail"]
    long_essay = "A sentence of the essay. " * 100  # over the recommended length, under the maximum
    assert client.post(url, json={"text": long_essay}).json()["over_recommended"] is True


def test_handwritten_essay_is_read_literally(client):
    fake = FakeChat(["I goed to school\n\nIt was fun"])
    use(fake)
    sid = start(client, with_assignment=False).json()["session_id"]
    photo = "data:image/jpeg;base64,AAAA"
    read = client.post(f"/api/essay/sessions/{sid}/handwriting", json={"images": [photo]})
    assert read.json() == {"text": "I goed to school\n\nIt was fun"}
    instruction = fake.calls[0][1]["content"][0]["text"]
    assert "handwritten essay in English" in instruction and "do not correct" in instruction
    assert client.post(f"/api/essay/sessions/{sid}/handwriting", json={"images": ["x"]}).status_code == 422
    assert client.post("/api/essay/sessions/nope/submit", json={"text": ESSAY}).status_code == 404
