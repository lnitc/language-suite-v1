"""Written translation, with a fake model."""

import json

import pytest
from fastapi.testclient import TestClient

from app.features.translation import MAX_CHARS, wrong_language
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


SOURCE = "I went to the zoo last weekend. It was a lot of fun, although it rained in the afternoon."
MINE = "先週末、動物園に行きました。午後に雨が降りましたが、楽しいでした。"
IDEAL = "先週末、動物園に行きました。午後は雨が降りましたが、とても楽しかったです。"
REVIEW = json.dumps(
    {
        "scores": {
            "accuracy": {"score": 4, "comment": "Meaning is right."},
            "completeness": {"score": 5, "comment": "Nothing missing."},
            "naturalness": {"score": 3, "comment": "A little stiff."},
            "language": {"score": 2.6, "comment": "Adjective past tense."},
        },
        "feedback": "**Good work.**\n\nWatch i-adjectives in the past tense.",
        "corrections": [
            {"source": "It was a lot of fun", "yours": "楽しいでした", "better": "とても楽しかったです", "explanation": "Past of 楽しい is 楽しかった."},
            {"source": "x", "yours": "same", "better": "same", "explanation": "no change"},
            {"source": "although", "yours": "", "better": "けれども", "explanation": "Left out."},
        ],
    }
)


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(fake):
    app.dependency_overrides[get_chat_provider] = lambda: fake


def start(client, **overrides):
    body = {"source_language": "English", "target_language": "Japanese", "difficulty": "elementary"}
    body.update(overrides)
    return client.post("/api/translation/sessions", json=body)


def test_teacher_text_then_review_and_ideal_translation(client):
    fake = FakeChat([f"**{SOURCE}**", REVIEW, IDEAL])
    use(fake)
    started = start(client, session_prompt="About a day out", system_prompt="You are Ms Abe.", length="short").json()
    assert started["source_text"] == SOURCE
    assert (started["recommended_chars"], started["max_chars"]) == (1500, 3000)
    system, user = fake.calls[0]
    assert system["content"] == "You are Ms Abe."
    assert "About a day out" in user["content"] and "about 60 words" in user["content"]
    assert "translate it into Japanese" in user["content"] and "CEFR A2" in user["content"]

    # The learner's source_text is ignored when the teacher wrote the text.
    result = client.post(
        f"/api/translation/sessions/{started['session_id']}/submit",
        json={"translation": MINE, "source_text": "something else"},
    ).json()
    assert result["source_text"] == SOURCE and result["translation"] == MINE
    assert [(row["name"], row["score"]) for row in result["scores"]] == [
        ("Accuracy", 4), ("Completeness", 5), ("Naturalness", 3), ("Grammar and vocabulary", 3),
    ]
    assert (result["total"], result["max_total"]) == (15, 20)
    assert result["feedback"] == "Good work.\n\nWatch i-adjectives in the past tense."
    assert [(c["source"], c["yours"], c["better"]) for c in result["corrections"]] == [
        ("It was a lot of fun", "楽しいでした", "とても楽しかったです"),
        ("although", "", "けれども"),  # something left out is a correction too
    ]
    assert result["ideal"] == IDEAL and result["over_recommended"] is False
    for call in fake.calls[1:]:
        assert SOURCE in call[1]["content"] and MINE in call[1]["content"]


def test_own_text_and_translation(client):
    fake = FakeChat([REVIEW, IDEAL])
    use(fake)
    started = start(client, with_text=False, session_prompt="From my textbook").json()
    assert started["source_text"] == "" and fake.calls == []
    url = f"/api/translation/sessions/{started['session_id']}/submit"
    missing = client.post(url, json={"translation": MINE})
    assert missing.status_code == 422 and "source text" in missing.json()["detail"]
    result = client.post(url, json={"translation": MINE, "source_text": f"  {SOURCE}  "}).json()
    assert result["source_text"] == SOURCE
    assert "From my textbook" in fake.calls[0][1]["content"]


def test_ideal_translation_in_the_source_language_is_asked_for_again(client):
    fake = FakeChat([REVIEW, "I visited the zoo last weekend. It was great fun, though it rained.", IDEAL])
    use(fake)
    url = f"/api/translation/sessions/{start(client, with_text=False).json()['session_id']}/submit"
    result = client.post(url, json={"translation": MINE, "source_text": SOURCE}).json()
    assert result["ideal"] == IDEAL
    retry = fake.calls[2][1]["content"]
    assert "Your whole answer must be in Japanese" in retry and SOURCE in retry and MINE not in retry

    # Wrong twice: an error, and the review is not repeated on the next try.
    fake = FakeChat([REVIEW, "Still English.", "English again.", IDEAL])
    use(fake)
    url = f"/api/translation/sessions/{start(client, with_text=False).json()['session_id']}/submit"
    failed = client.post(url, json={"translation": MINE, "source_text": SOURCE})
    assert failed.status_code == 502 and "right language" in failed.json()["detail"]
    assert client.post(url, json={"translation": MINE, "source_text": SOURCE}).json()["ideal"] == IDEAL
    assert len(fake.calls) == 4


def test_wrong_language_rules():
    assert wrong_language("I went to the zoo.", SOURCE, MINE) is True
    assert wrong_language(IDEAL, SOURCE, MINE) is False
    spanish = "Fui al zoológico el fin de semana pasado. Fue muy divertido, aunque llovió por la tarde."
    assert wrong_language(spanish, SOURCE, "Fui al zoo el fin de semana.") is False  # same alphabet, a real translation
    assert wrong_language(SOURCE.replace("a lot of", "lots of"), SOURCE, "Fui al zoo.") is True  # a near copy


def test_limits_reworked_translation_and_handwriting(client):
    fake = FakeChat([REVIEW, ProviderError("model offline"), IDEAL, REVIEW, IDEAL, "先週末、動物園に行った"])
    use(fake)
    sid = start(client, with_text=False).json()["session_id"]
    url = f"/api/translation/sessions/{sid}/submit"
    assert "too short" in client.post(url, json={"translation": "a", "source_text": SOURCE}).json()["detail"]
    long_source = client.post(url, json={"translation": MINE, "source_text": "word " * (MAX_CHARS // 5 + 5)})
    assert long_source.status_code == 422 and "source text has" in long_source.json()["detail"]
    long_translation = client.post(url, json={"translation": "語" * (MAX_CHARS + 1), "source_text": SOURCE})
    assert "translation has" in long_translation.json()["detail"]

    body = {"translation": MINE, "source_text": SOURCE}
    assert client.post(url, json=body).status_code == 502  # the ideal translation failed
    first = client.post(url, json=body).json()
    assert len(fake.calls) == 3  # the review was kept
    assert client.post(url, json=body).json() == first and len(fake.calls) == 3
    client.post(url, json={"translation": MINE + "よかった。", "source_text": SOURCE})
    assert len(fake.calls) == 5  # a reworked translation is marked afresh

    read = client.post(f"/api/translation/sessions/{sid}/handwriting", json={"images": ["data:image/png;base64,AAAA"]})
    assert read.json() == {"text": "先週末、動物園に行った"}
    assert "handwritten translation in Japanese" in fake.calls[5][1]["content"][0]["text"]
