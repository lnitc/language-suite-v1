"""Grammar drills, with a fake model."""

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


def gap(n, **changes):
    entry = {"type": "gap", "sentence": f"I ____ to school {n} days ago.", "answers": ["went"], "hint": "(go)", "explanation": "Past simple of go."}
    entry.update(changes)
    return entry


def fix(n, **changes):
    entry = {"type": "fix", "sentence": f"She don't like coffee number {n}.", "answers": [f"She doesn't like coffee number {n}.", f"She does not like coffee number {n}."], "explanation": "Third person takes doesn't."}
    entry.update(changes)
    return entry


def batch(*entries):
    return json.dumps({"items": list(entries)})


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(fake):
    app.dependency_overrides[get_chat_provider] = lambda: fake


def start(client, **overrides):
    body = {"language": "English", "difficulty": "elementary", "count": 4}
    body.update(overrides)
    return client.post("/api/grammar/sessions", json=body)


def test_items_hide_the_answers_and_are_marked_by_code_with_a_second_opinion(client):
    verdicts = json.dumps({"verdicts": [
        {"number": 2, "correct": True, "comment": ""},
        {"number": 3, "correct": False, "comment": "'goed' is not a word; go is irregular."},
    ]})
    fake = FakeChat([batch(gap(1), fix(2), gap(3), fix(4)), verdicts])
    use(fake)
    started = start(client, topic="past simple and present simple", session_prompt="About school").json()
    assert started["requested"] == 4
    assert started["items"][0] == {"number": 1, "kind": "gap", "task": "Fill in the blank", "sentence": "I ____ to school 1 days ago.", "hint": "(go)"}
    assert started["items"][1]["task"] == "Correct the mistake" and started["items"][1]["hint"] == ""
    assert "went" not in json.dumps(started) and "doesn't" not in json.dumps(started)
    prompt = fake.calls[0][1]["content"]
    assert "Grammar point to practise: past simple and present simple." in prompt
    assert "About school" in prompt and "CEFR A2" in prompt and "use both kinds" in prompt

    url = f"/api/grammar/sessions/{started['session_id']}/submit"
    result = client.post(url, json={"answers": [" Went. ", "She doesnt likes coffee number 2", "goed", ""]}).json()
    assert [row["status"] for row in result["items"]] == ["correct", "accepted", "wrong", "skipped"]
    assert (result["score"], result["total"]) == (2, 4)
    assert result["items"][2]["comment"] == "'goed' is not a word; go is irregular."
    assert result["items"][0]["explanation"] == "Past simple of go."
    assert result["items"][1]["correct_answers"][0] == "She doesn't like coffee number 2."
    # Only the two doubtful answers go to the model, each with what was expected.
    asked = fake.calls[1][1]["content"]
    assert "Item 2 (correct the mistake)" in asked and "Item 3 (fill in the blank)" in asked
    assert "Item 1" not in asked and "Item 4" not in asked and "Hint: (go)." in asked
    assert client.post(url, json={"answers": []}).json() == result and len(fake.calls) == 2


def test_unchanged_sentence_and_all_correct_need_no_model(client):
    fake = FakeChat([batch(fix(1), gap(2))])
    use(fake)
    sid = start(client, count=2).json()["session_id"]
    result = client.post(f"/api/grammar/sessions/{sid}/submit", json={"answers": ["She don't like coffee number 1.", "went"]}).json()
    assert [row["status"] for row in result["items"]] == ["wrong", "correct"]
    assert "left the sentence as it was" in result["items"][0]["comment"]
    assert len(fake.calls) == 1


def test_bad_items_are_dropped_and_asked_for_again(client):
    bad = [
        gap(1, sentence="No blank here."),
        gap(2, sentence="Two ____ blanks ____ here."),
        gap(3, answers=[]),
        fix(4, answers=["She don't like coffee number 4."]),  # the "correction" equals the mistake
        {"type": "essay", "sentence": "x", "answers": ["y"]},
        "junk",
        gap(5, sentence="I ___ happy (be).", answers="am"),  # three underscores, answer as a string
    ]
    fake = FakeChat([batch(*bad), batch(gap(5, sentence="I ___ happy (be).", answers="am"), fix(6)), batch(gap(7))])
    use(fake)
    started = start(client, count=3, exercise="mixed").json()
    assert [item["sentence"] for item in started["items"]] == ["I ____ happy (be).", "She don't like coffee number 6.", "I ____ to school 7 days ago."]
    assert "These sentences already exist" in fake.calls[1][1]["content"]


def test_exercise_type_limits_the_kinds_and_teacher_chooses_without_a_topic(client):
    fake = FakeChat([batch(gap(1), fix(2), gap(3)), batch(), batch()])
    use(fake)
    started = start(client, count=3, exercise="gap").json()
    assert [item["kind"] for item in started["items"]] == ["gap", "gap"]  # the "fix" item is not wanted
    prompt = fake.calls[0][1]["content"]
    assert '"fix" (correct the mistake)' not in prompt and "use both kinds" not in prompt
    assert "Choose grammar points that learners at this level" in prompt


def test_errors_and_missing_second_opinion(client):
    use(FakeChat(["no json", "no json", "no json"]))
    assert start(client, count=1).status_code == 502
    assert start(client, count=11).status_code == 422
    assert start(client, exercise="quiz").status_code == 422
    use(FakeChat([batch(gap(1)), ProviderError("model offline")]))
    sid = start(client, count=1).json()["session_id"]
    result = client.post(f"/api/grammar/sessions/{sid}/submit", json={"answers": ["goed"]}).json()
    assert (result["items"][0]["status"], result["items"][0]["comment"], result["score"]) == ("wrong", "", 0)
    assert client.post("/api/grammar/sessions/nope/submit", json={"answers": []}).status_code == 404
