"""Tests run without any model: a fake brain is plugged into the socket."""

import json

import pytest
from fastapi.testclient import TestClient

from app.features.vocabulary import normalize, parse_json
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


WORDS = json.dumps(
    {
        "items": [
            {"word": "dog", "translations": ["perro"]},
            {"word": "car", "translations": ["coche", "carro"]},
            {"word": "house", "translations": ["casa"]},
            {"word": "extra", "translations": ["extra"]},
        ]
    }
)


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(fake):
    app.dependency_overrides[get_chat_provider] = lambda: fake


def start(client, **overrides):
    body = {"source_language": "English", "target_language": "Spanish", "count": 3}
    body.update(overrides)
    return client.post("/api/vocabulary/sessions", json=body)


def test_full_session_with_synonym_and_skip(client):
    verdicts = json.dumps({"verdicts": [{"index": 1, "correct": True}]})
    fake = FakeChat([f"```json\n{WORDS}\n```", verdicts])
    use(fake)

    first = start(client).json()
    assert first["total"] == 3  # trimmed to the requested count
    assert first["word"] == "dog"
    sid = first["session_id"]
    url = f"/api/vocabulary/sessions/{sid}"

    assert client.get(f"{url}/result").status_code == 409  # not finished yet

    step = client.post(f"{url}/answers", json={"answer": "  ¡Perro! "}).json()
    assert step["word"] == "car"
    client.post(f"{url}/answers", json={"answer": "automóvil"})
    step = client.post(f"{url}/answers", json={"skip": True}).json()
    assert step["done"] is True

    result = client.get(f"{url}/result").json()
    assert [i["status"] for i in result["items"]] == ["correct", "accepted", "skipped"]
    assert (result["score"], result["total"]) == (2, 3)
    assert result["items"][1]["correct_translations"] == ["coche", "carro"]

    # Asking again must not call the model a third time.
    assert client.get(f"{url}/result").json()["score"] == 2
    assert len(fake.calls) == 2


def test_wrong_answer_stays_wrong_if_second_opinion_fails(client):
    use(FakeChat([WORDS, ProviderError("model offline")]))
    sid = start(client, count=1).json()["session_id"]
    url = f"/api/vocabulary/sessions/{sid}"
    client.post(f"{url}/answers", json={"answer": "gato"})
    result = client.get(f"{url}/result").json()
    assert result["items"][0]["status"] == "wrong"
    assert result["score"] == 0


def test_material_and_prompts_reach_the_model(client):
    fake = FakeChat([WORDS])
    use(fake)
    start(
        client,
        system_prompt="You are Señora Lopez.",
        session_prompt="Topic: animals",
        material="dog\ncat\nbird",
    )
    system, user = fake.calls[0]
    assert system["content"] == "You are Señora Lopez."
    assert "Topic: animals" in user["content"]
    assert "dog\ncat\nbird" in user["content"]


def test_unusable_model_output_gives_clear_error(client):
    use(FakeChat(["Sorry, I cannot do that."]))
    response = start(client)
    assert response.status_code == 502
    assert "word list" in response.json()["detail"]


def test_input_validation_and_unknown_session(client):
    use(FakeChat([]))
    assert start(client, count=0).status_code == 422
    assert start(client, count=51).status_code == 422
    assert client.post(
        "/api/vocabulary/sessions/nope/answers", json={"answer": "x"}
    ).status_code == 404


def test_normalize_is_forgiving():
    assert normalize("  ¡Hola,  Mundo! ") == normalize("hola mundo")
    assert normalize("ＡＢＣ") == "abc"  # full-width letters
    assert normalize("犬。") == "犬"
    assert normalize("gato") != normalize("perro")


def test_parse_json_tolerates_wrapping_text():
    assert parse_json('Here you go: {"a": 1} Enjoy!') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json("no json here")
