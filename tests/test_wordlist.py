"""Vocabulary list creator, with a fake model."""

import json
import re

import pytest
from fastapi.testclient import TestClient

from app.features.wordlist import note_lines
from app.main import app
from app.providers.factory import get_chat_provider


class EchoChat:
    """Answers the way a well-behaved model would, from the prompt it is given."""

    def __init__(self, words=None, skip=(), broken_batches=0):
        self.words = list(words or [])
        self.skip = set(skip)
        self.broken_batches = broken_batches
        self.calls = []

    async def chat(self, messages, *, json_mode=False, temperature=0.7):
        prompt = messages[-1]["content"]
        self.calls.append(prompt)
        if '"words"' in prompt:
            wanted = int(re.search(r"List (\d+) words", prompt).group(1))
            batch, self.words = self.words[:wanted], self.words[wanted:]
            return json.dumps({"words": batch})
        if self.broken_batches:
            self.broken_batches -= 1
            return "Sorry, here is your list: ..."
        lines = re.findall(r"^(\d+)\. (.+)$", prompt.split("Lines:\n")[1], flags=re.M)
        entries = [
            {
                "n": int(n),
                "word": line.split()[0],
                "pronunciation": "よみ",
                "translation": f"meaning of {line.split()[0]}",
                "example": "例文です。",
                "example_translation": "An example.",
                "remarks": "",
            }
            for n, line in lines
            if int(n) not in self.skip
        ]
        return json.dumps({"entries": list(reversed(entries))})  # order must not matter


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(fake):
    app.dependency_overrides[get_chat_provider] = lambda: fake


def start(client, **overrides):
    body = {"source_language": "Japanese", "target_language": "English", "count": 12}
    body.update(overrides)
    return client.post("/api/wordlist/sessions", json=body)


def test_note_lines_cleans_the_learners_file():
    text = "精進 しょうじん　devotion\n\n   \n---\n123\n精進 しょうじん　devotion\n錦（にしき）brocade\n"
    assert note_lines(text) == ["精進 しょうじん devotion", "錦（にしき）brocade"]


def test_create_mode_proposes_words_then_fills_them_in_batches(client):
    words = [f"語{i}" for i in range(1, 13)]
    fake = EchoChat(words=words[:9] + ["語1"] + words[9:])  # one repeat: needs a top-up round
    use(fake)
    plan = start(client, prompt="Weather words", difficulty="advanced").json()
    assert (plan["total"], plan["batch_count"], plan["from_file"]) == (12, 2, False)
    assert "Weather words" in fake.calls[0] and "Advanced (CEFR C1)" in fake.calls[0]
    assert "Do not repeat" in fake.calls[1]

    url = f"/api/wordlist/sessions/{plan['session_id']}/batches"
    first = client.post(f"{url}/0").json()["rows"]
    second = client.post(f"{url}/1").json()["rows"]
    assert [row["word"] for row in first + second] == words
    assert first[0] == {
        "word": "語1", "pronunciation": "よみ", "translation": "meaning of 語1", "example": "例文です。",
        "example_translation": "An example.", "remarks": "", "complete": True, "source_line": "語1",
    }
    calls = len(fake.calls)
    assert client.post(f"{url}/0").json()["rows"] == first and len(fake.calls) == calls  # kept, not redone
    assert client.post(f"{url}/2").status_code == 404
    assert "words to include" in fake.calls[2] and "hiragana for Japanese" in fake.calls[2]


def test_own_list_returns_every_line_and_ignores_the_count(client):
    fake = EchoChat()
    use(fake)
    material = "\n".join(f"単語{i}　よみ{i}" for i in range(1, 24))
    plan = start(client, count=5, material=material).json()
    assert (plan["total"], plan["from_file"], plan["provided"], plan["batch_count"]) == (23, True, 23, 3)
    assert fake.calls == []  # no model call is needed to plan a list from a file
    rows = client.post(f"/api/wordlist/sessions/{plan['session_id']}/batches/2").json()["rows"]
    assert [row["word"] for row in rows] == ["単語21", "単語22", "単語23"]
    assert "learner's own notes" in fake.calls[0] and "21. " not in fake.calls[0]  # numbered 1-3 in the batch


def test_own_list_over_the_limit_is_cut_and_reported(client):
    use(EchoChat())
    plan = start(client, material="\n".join(f"word{i}" for i in range(130))).json()
    assert (plan["total"], plan["provided"], plan["limit"], plan["batch_count"]) == (100, 130, 100, 10)
    assert start(client, material="123\n---\n").status_code == 422


def test_skipped_entries_are_asked_for_again(client):
    fake = EchoChat(skip={2})
    use(fake)
    plan = start(client, material="朝 あさ morning\n昼\n夜 よる night").json()
    url = f"/api/wordlist/sessions/{plan['session_id']}/batches/0"
    # In the second request the skipped line is alone and numbered 1, so it is answered.
    rows = client.post(url).json()["rows"]
    assert [(row["word"], row["complete"]) for row in rows] == [("朝", True), ("昼", True), ("夜", True)]
    assert len(fake.calls) == 2 and fake.calls[1].endswith("Lines:\n1. 昼")


def test_entry_skipped_twice_keeps_the_original_line_and_bad_batches_can_be_retried(client):
    fake = EchoChat(skip={1}, broken_batches=1)
    use(fake)
    plan = start(client, material="朝 あさ morning\n昼").json()
    url = f"/api/wordlist/sessions/{plan['session_id']}/batches/0"
    failed = client.post(url)
    assert failed.status_code == 502 and "Continue" in failed.json()["detail"]
    rows = client.post(url).json()["rows"]
    assert [(row["word"], row["complete"], row["translation"]) for row in rows] == [
        ("朝 あさ morning", False, ""),
        ("昼", True, "meaning of 昼"),
    ]


def test_validation(client):
    use(EchoChat())
    assert start(client, count=101).status_code == 422
    assert start(client, count=0).status_code == 422
    assert client.post("/api/wordlist/sessions/nope/batches/0").status_code == 404
    use(EchoChat(words=[]))
    assert start(client).status_code == 502


# ---------- Word export ----------

def test_docx_export_contains_the_table(client):
    docx = pytest.importorskip("docx")
    import io

    body = {
        "title": "Vocabulary list: Japanese",
        "subtitle": "Japanese with explanations in English",
        "header": ["#", "Word", "Pronunciation", "Translation", "Example and notes"],
        "rows": [
            ["1", "精進", "しょうじん", "devotion, diligence", "彼は精進を重ねた。 — He kept working at it."],
            ["2", "錦", "にしき", "brocade", "bad\x0bchar | =formal"],
            ["3", "short row"],
        ],
    }
    response = client.post("/api/wordlist/export/docx", json=body)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    document = docx.Document(io.BytesIO(response.content))
    table = document.tables[0]
    assert [cell.text for cell in table.rows[0].cells] == body["header"]
    assert [cell.text for cell in table.rows[1].cells] == body["rows"][0]
    assert table.rows[2].cells[4].text == "badchar | =formal"  # control character removed
    assert [cell.text for cell in table.rows[3].cells] == ["3", "short row", "", "", ""]
    assert document.paragraphs[0].text == "Vocabulary list: Japanese"
    section = document.sections[0]
    assert section.page_width > section.page_height  # landscape

    assert client.post("/api/wordlist/export/docx", json={**body, "rows": []}).status_code == 422


def test_examples_and_notes_can_be_left_out(client):
    fake = EchoChat()
    use(fake)
    plan = start(client, material="朝 あさ morning\n夜", include_examples=False).json()
    assert plan["include_examples"] is False
    rows = client.post(f"/api/wordlist/sessions/{plan['session_id']}/batches/0").json()["rows"]
    prompt = fake.calls[0]
    assert "no example sentences" in prompt
    assert '"example"' not in prompt and '"remarks"' not in prompt
    # The fake model adds examples anyway; they are dropped because they were not asked for.
    assert [(r["word"], r["translation"], r["example"], r["example_translation"], r["remarks"], r["complete"]) for r in rows] == [
        ("朝", "meaning of 朝", "", "", "", True),
        ("夜", "meaning of 夜", "", "", "", True),
    ]

    use(EchoChat())
    with_examples = start(client, material="朝").json()
    assert with_examples["include_examples"] is True  # the default
