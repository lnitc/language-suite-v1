"""Reading comprehension, with a fake model."""

import json

import pytest
from fastapi.testclient import TestClient

from app.features import reading
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


TEXT = "# The Old Bridge\n\n" + "The bridge was built in 1900 by the town. " * 3 + "\n\n" + "People still cross it every day. " * 3


def q(n, answer=1, **changes):
    entry = {
        "question": f"Question {n}?",
        "options": [f"right {n}", f"wrong {n}a", f"wrong {n}b", f"wrong {n}c"],
        "answer": answer,
        "explanation": f"Because of line {n}.",
    }
    entry.update(changes)
    return entry


def batch(*entries):
    return json.dumps({"questions": list(entries)})


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(fake):
    app.dependency_overrides[get_chat_provider] = lambda: fake


def start(client, **overrides):
    body = {"language": "English", "difficulty": "intermediate", "question_count": 3}
    body.update(overrides)
    return client.post("/api/reading/sessions", json=body)


def test_text_step_splits_title_and_paragraphs_and_sets_the_length(client):
    fake = FakeChat([TEXT])
    use(fake)
    started = start(client, session_prompt="About a town", system_prompt="You are Ms Ito.").json()
    assert started["title"] == "The Old Bridge"
    assert started["text"].count("\n\n") == 1 and started["text"].startswith("The bridge was built")
    system, user = fake.calls[0]
    assert system["content"] == "You are Ms Ito."
    prompt = user["content"]
    assert "about 500 words" in prompt and "about 1000 characters" in prompt  # "long" is the default
    assert "About a town" in prompt and "CEFR B1" in prompt and "3 comprehension questions" in prompt

    use(FakeChat([TEXT]))
    start(client, length="short")
    use(FakeChat(["Too short."]))
    assert start(client).status_code == 502
    assert start(client, question_count=11).status_code == 422


def test_questions_hide_the_answers_and_are_marked_by_the_code(client, monkeypatch):
    monkeypatch.setattr(reading._rng, "shuffle", lambda order: order.reverse())  # predictable "shuffle"
    why = json.dumps({"explanations": [{"number": 2, "why_wrong": "The text says 1900."}, {"number": 1, "why_wrong": "ignored"}]})
    fake = FakeChat([TEXT, batch(q(1), q(2, answer="B"), q(3, answer="right 3")), why])
    use(fake)
    sid = start(client).json()["session_id"]
    url = f"/api/reading/sessions/{sid}"
    assert client.post(f"{url}/submit", json={"answers": []}).status_code == 409  # no questions yet

    made = client.post(f"{url}/questions").json()
    assert made["requested"] == 3 and len(made["questions"]) == 3
    assert made["questions"][0] == {
        "number": 1, "question": "Question 1?", "options": ["wrong 1c", "wrong 1b", "wrong 1a", "right 1"],
    }
    assert "correct" not in json.dumps(made) and "explanation" not in json.dumps(made)
    assert "The bridge was built in 1900" in fake.calls[1][1]["content"]

    # Question 1 right (option 4 after the reversal), question 2 wrong, question 3 not answered.
    result = client.post(f"{url}/submit", json={"answers": [3, 0, None]}).json()
    assert (result["score"], result["total"]) == (1, 3)
    rows = result["questions"]
    assert [(r["correct"], r["chosen"], r["is_correct"]) for r in rows] == [(3, 3, True), (2, 0, False), (3, None, False)]
    # "B" was the second option before shuffling ("wrong 2a"), now at position 3.
    assert rows[1]["options"][rows[1]["correct"]] == "wrong 2a"
    assert rows[2]["options"][rows[2]["correct"]] == "right 3"  # answer given as the option's text
    assert [r["why_wrong"] for r in rows] == ["", "The text says 1900.", ""]
    assert rows[0]["explanation"] == "Because of line 1."
    # Only the wrong choice is sent for explanation.
    asked = fake.calls[2][1]["content"]
    assert "Question 2:" in asked and "Question 1:" not in asked and "Question 3:" not in asked
    assert client.post(f"{url}/submit", json={"answers": [0, 0, 0]}).json() == result  # marked once
    assert len(fake.calls) == 3


def test_bad_questions_are_dropped_and_asked_for_again(client):
    bad = [
        q(1, options=["a", "b", "c"]),            # three options
        q(2, options=["same", "same", "x", "y"]),  # two identical options
        q(3, answer=7),                            # no such option
        q(4, answer="maybe"),                      # unclear answer
        "junk",
    ]
    fake = FakeChat([TEXT, batch(*bad, q(5, options=["A. one", "B) two", "（C）three", "4. four"], answer="C")), batch(q(5), q(6)), batch(q(7))])
    use(fake)
    sid = start(client, question_count=3).json()["session_id"]
    made = client.post(f"/api/reading/sessions/{sid}/questions").json()
    assert [item["question"] for item in made["questions"]] == ["Question 5?", "Question 6?", "Question 7?"]
    assert sorted(made["questions"][0]["options"]) == ["four", "one", "three", "two"]  # labels removed
    assert "These questions already exist" in fake.calls[2][1]["content"]
    assert fake.calls[2][1]["content"].count("- Question 5?") == 1


def test_ten_questions_come_in_two_rounds_and_fewer_is_accepted(client):
    first, second = batch(*[q(n) for n in range(1, 6)]), batch(*[q(n) for n in range(6, 9)])
    fake = FakeChat([TEXT, first, second, batch(), batch()])
    use(fake)
    sid = start(client, question_count=10).json()["session_id"]
    made = client.post(f"/api/reading/sessions/{sid}/questions").json()
    assert (len(made["questions"]), made["requested"]) == (8, 10)
    assert "Write 5 multiple-choice" in fake.calls[1][1]["content"]
    assert "Write 2 multiple-choice" in fake.calls[3][1]["content"]


def test_no_questions_can_be_retried_and_missing_explanations_do_not_matter(client):
    fake = FakeChat([TEXT, "no json", "no json", "no json", batch(q(1)), ProviderError("model offline")])
    use(fake)
    url = f"/api/reading/sessions/{start(client, question_count=1).json()['session_id']}"
    assert client.post(f"{url}/questions").status_code == 502
    assert len(client.post(f"{url}/questions").json()["questions"]) == 1
    result = client.post(f"{url}/submit", json={"answers": [5]}).json()  # 5 is not an option: unanswered
    assert (result["score"], result["questions"][0]["chosen"]) == (0, None)
    assert len(fake.calls) == 5  # nothing to explain, so no further model call


def test_question_style_changes_the_instructions(client):
    fake = FakeChat([TEXT, batch(q(1)), TEXT, batch(q(1)), ProviderError("no second opinion in this test")])
    use(fake)
    plain = start(client, question_count=1).json()["session_id"]
    client.post(f"/api/reading/sessions/{plain}/questions")
    tricky = start(client, question_count=1, question_style="tricky").json()["session_id"]
    client.post(f"/api/reading/sessions/{tricky}/questions")

    plain_prompt, tricky_prompt = fake.calls[1][1]["content"], fake.calls[3][1]["content"]
    assert "Question style: straightforward" in plain_prompt and "must NOT repeat" not in plain_prompt
    assert "Question style: tricky" in tricky_prompt
    assert "must NOT repeat the wording of the text" in tricky_prompt
    assert "reuse words and phrases straight from the text" in tricky_prompt
    # The text itself is written the same way for both.
    assert fake.calls[0][1]["content"] == fake.calls[2][1]["content"]

    result = client.post(f"/api/reading/sessions/{tricky}/submit", json={"answers": [None]}).json()
    assert result["question_style"] == "tricky"
    assert start(client, question_style="impossible").status_code == 422


def test_tricky_questions_get_a_second_opinion(client, monkeypatch):
    monkeypatch.setattr(reading._rng, "shuffle", lambda order: None)  # keep the options in place
    # The checker agrees on question 1, disagrees on 2, and cannot decide on 3.
    opinion = json.dumps({"answers": [{"question": 1, "answer": 1}, {"question": 2, "answer": 3}, {"question": 3, "answer": 0}]})
    refill = batch(q(4), q(5))
    opinion_two = json.dumps({"answers": [{"question": 1, "answer": 1}, {"question": 2, "answer": 1}]})
    fake = FakeChat([TEXT, batch(q(1), q(2), q(3)), opinion, refill, opinion_two])
    use(fake)
    sid = start(client, question_count=3, question_style="tricky").json()["session_id"]
    made = client.post(f"/api/reading/sessions/{sid}/questions").json()
    assert [item["question"] for item in made["questions"]] == ["Question 1?", "Question 4?", "Question 5?"]

    check = fake.calls[2]
    assert "careful reader" in check[0]["content"]
    asked = check[1]["content"]
    assert "Question 2: Question 2?" in asked and "  1. right 2" in asked and "The bridge was built" in asked
    assert "Because of line" not in asked and '"answer": 1, "explanation"' not in asked  # the key is not shown
    assert "Write 2 multiple-choice" in fake.calls[3][1]["content"]  # only the rejected ones are replaced


def test_second_opinion_is_skipped_when_it_fails_and_for_straightforward_questions(client):
    fake = FakeChat([TEXT, batch(q(1)), ProviderError("model offline")])
    use(fake)
    sid = start(client, question_count=1, question_style="tricky").json()["session_id"]
    assert len(client.post(f"/api/reading/sessions/{sid}/questions").json()["questions"]) == 1

    fake = FakeChat([TEXT, batch(q(1))])
    use(fake)
    sid = start(client, question_count=1).json()["session_id"]
    client.post(f"/api/reading/sessions/{sid}/questions")
    assert len(fake.calls) == 2  # straightforward: no checking call
