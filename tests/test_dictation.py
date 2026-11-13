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


def test_uploaded_material_reaches_the_model_and_is_capped(client):
    fake = FakeChat([TEXT, TEXT])
    use(fake)
    start(client, material="bridge\nmountain\nriver")
    prompt = fake.calls[0][1]["content"]
    assert "--- material ---\nbridge\nmountain\nriver\n--- end material ---" in prompt

    start(client)  # no upload: no material section at all
    assert "material" not in fake.calls[1][1]["content"]

    fake.replies.append(TEXT)
    start(client, material="x" * 20000)
    assert fake.calls[2][1]["content"].count("x" * 100) and "x" * 8001 not in fake.calls[2][1]["content"]


# ---------- handwriting ----------

from app.textutils import split_by_sentence  # noqa: E402

SENTENCES = ["The cat sat on the mat.", "It was a sunny day!", "We walked to the old bridge."]


def test_split_by_sentence_follows_the_original_even_with_mistakes():
    # No punctuation, a wrong first word, misspellings, a missing word and an extra one.
    text = "The cat sat on mat Is was a suny day We walkd to the very old bridge"
    assert split_by_sentence(SENTENCES, text) == [
        "The cat sat on mat",
        "Is was a suny day",
        "We walkd to the very old bridge",
    ]


def test_split_by_sentence_edge_cases():
    assert split_by_sentence(SENTENCES, "") == ["", "", ""]
    assert split_by_sentence(SENTENCES, "It was a sunny day.") == ["", "It was a sunny day.", ""]
    # Nothing matches at all: the words are spread out in order, and none is lost.
    assert " ".join(split_by_sentence(SENTENCES, "xx yy zz")).split() == ["xx", "yy", "zz"]
    # Languages written without spaces are cut character by character.
    assert split_by_sentence(["今日は晴れです。", "明日は雨です。"], "今日は晴れです明日わ雨です") == [
        "今日は晴れです",
        "明日わ雨です",
    ]


def test_handwriting_is_read_without_showing_the_model_the_original(client):
    fake = FakeChat([TEXT, "The cat sat on mat\nIt was a suny day\nExtra one [?]", "Mind your spelling."])
    use(fake)
    sid = start(client).json()["session_id"]
    url = f"/api/dictation/sessions/{sid}"
    photo = "data:image/jpeg;base64,AAAA"

    read = client.post(f"{url}/handwriting", json={"images": [photo, photo]})
    assert read.json() == {"text": "The cat sat on mat\nIt was a suny day\nExtra one [?]"}
    system, user = fake.calls[1]
    assert user["content"][1:] == [{"type": "image_url", "image_url": {"url": photo}}] * 2
    prompt = system["content"] + user["content"][0]["text"]
    assert "do not correct" in prompt and "English" in prompt
    for sentence in ("The cat sat on the mat.", "It was a sunny day!"):
        assert sentence not in prompt  # the model must not see the answer

    result = client.post(f"{url}/submit", json={"full_text": read.json()["text"]}).json()
    assert [row["typed"] and " ".join(t["text"] for t in row["typed"]) for row in result["sentences"]] == [
        "The cat sat on mat",
        "It was a suny day",
        "Extra one [?]",
    ]
    assert [(row["correct"], row["total"]) for row in result["sentences"]] == [(5, 6), (4, 5), (2, 2)]
    assert result["feedback"] == "Mind your spelling."


def test_handwriting_input_checks_and_model_without_vision(client):
    use(FakeChat([TEXT, ProviderError("The model server returned an error (HTTP 400)."), "  "]))
    url = f"/api/dictation/sessions/{start(client).json()['session_id']}/handwriting"
    assert client.post(url, json={"images": []}).status_code == 422
    assert client.post(url, json={"images": ["data:text/plain;base64,AAAA"]}).status_code == 422
    photo = {"images": ["data:image/png;base64,AAAA"]}
    failed = client.post(url, json=photo)
    assert failed.status_code == 502 and "can read images" in failed.json()["detail"]
    empty = client.post(url, json=photo)
    assert empty.status_code == 502 and "no text" in empty.json()["detail"]
