"""History and mistake review: stored in a temporary database (see conftest.py)."""

import pytest
from fastapi.testclient import TestClient

from app.features import history
from app.main import app
from app.providers.factory import get_chat_provider


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


def save(client, **changes):
    body = {"feature": "vocabulary", "language": "Japanese", "title": "English → Japanese",
            "score": 3, "total": 4, "report": "Language Suite: Vocabulary practice\nScore: 3 / 4"}
    body.update(changes)
    return client.post("/api/history/results", json=body)


def word(prompt, **changes):
    entry = {"prompt": prompt, "your_answer": "neko", "correct": "犬", "note": "",
             "extra": {"source_language": "English", "translations": ["犬", "いぬ"]}}
    entry.update(changes)
    return entry


def test_the_database_is_the_temporary_one(tmp_path):
    assert history.database_path() == tmp_path / "history.db"


def test_results_are_saved_listed_summarised_and_deleted(client):
    first = save(client).json()["id"]
    save(client, score=1, total=4)
    save(client, feature="conversation", language="French", title="", score=None, total=None, report="Script")
    listed = client.get("/api/history/results").json()
    assert listed["count"] == 3 and [row["feature"] for row in listed["results"]] == ["conversation", "vocabulary", "vocabulary"]
    assert listed["results"][0]["percent"] is None and listed["results"][2]["percent"] == 75
    assert listed["languages"] == ["French", "Japanese"] and listed["features"] == ["conversation", "vocabulary"]
    by_feature = {row["feature"]: row for row in listed["summary"]}
    assert (by_feature["vocabulary"]["sessions"], by_feature["vocabulary"]["average"]) == (2, 50)
    assert by_feature["conversation"]["average"] is None
    assert "report" not in listed["results"][0]

    only = client.get("/api/history/results", params={"language": "japanese", "feature": "vocabulary", "limit": 1}).json()
    assert only["count"] == 2 and len(only["results"]) == 1 and [row["feature"] for row in only["summary"]] == ["vocabulary"]

    detail = client.get(f"/api/history/results/{first}").json()
    assert detail["report"].endswith("Score: 3 / 4") and detail["title"] == "English → Japanese"
    assert detail["created_at"].endswith("Z")
    assert client.delete(f"/api/history/results/{first}").json() == {"deleted": 1}
    assert client.get(f"/api/history/results/{first}").status_code == 404
    assert client.delete("/api/history/results").json() == {"deleted": 2}
    assert client.get("/api/history/results").json()["count"] == 0


def test_recent_average_uses_the_latest_five(client):
    for score in (0, 0, 10, 10, 10, 10, 10):
        save(client, score=score, total=10, feature="grammar")
    row = client.get("/api/history/results").json()["summary"][0]
    assert (row["average"], row["recent_average"]) == (71, 100)


def test_a_repeated_mistake_is_counted_and_a_correct_answer_marks_it_learned(client):
    save(client, mistakes=[word("dog"), word("cat", correct="猫")])
    save(client, mistakes=[word("dog", your_answer="inu?")], mastered=["cat", "bird"])
    listed = client.get("/api/history/mistakes").json()
    rows = {row["prompt"]: row for row in listed["mistakes"]}
    assert listed["count"] == 2 and listed["languages"] == ["Japanese"]
    assert (rows["dog"]["times"], rows["dog"]["your_answer"], rows["dog"]["learned"]) == (2, "inu?", False)
    assert rows["dog"]["extra"]["translations"] == ["犬", "いぬ"]
    assert rows["cat"]["learned"] is True and rows["cat"]["times"] == 1

    # Wrong again later: back on the list.
    save(client, mistakes=[word("cat", correct="猫")])
    still = client.get("/api/history/mistakes", params={"learned": "false"}).json()
    assert {row["prompt"] for row in still["mistakes"]} == {"dog", "cat"}
    # The same word in another feature or language is a separate entry.
    save(client, feature="grammar", mistakes=[word("dog")])
    save(client, language="Korean", mistakes=[word("dog")])
    assert client.get("/api/history/mistakes").json()["count"] == 4
    assert client.get("/api/history/mistakes", params={"feature": "grammar"}).json()["count"] == 1
    assert client.get("/api/history/mistakes", params={"language": "korean"}).json()["count"] == 1


def test_mistakes_can_be_marked_and_removed(client):
    save(client, mistakes=[word("dog"), word("cat"), word("bird")])
    ids = {row["prompt"]: row["id"] for row in client.get("/api/history/mistakes").json()["mistakes"]}
    assert client.patch(f"/api/history/mistakes/{ids['dog']}", json={"learned": True}).json()["learned"] is True
    assert client.get("/api/history/mistakes", params={"learned": "true"}).json()["count"] == 1
    assert client.patch("/api/history/mistakes/999", json={"learned": True}).status_code == 404
    assert client.delete(f"/api/history/mistakes/{ids['cat']}").json() == {"deleted": 1}
    assert client.delete("/api/history/mistakes", params={"learned": "true"}).json() == {"deleted": 1}
    assert [row["prompt"] for row in client.get("/api/history/mistakes").json()["mistakes"]] == ["bird"]
    # Deleting results leaves the review list alone.
    client.delete("/api/history/results")
    assert client.get("/api/history/mistakes").json()["count"] == 1
    assert client.delete("/api/history/mistakes").json() == {"deleted": 1}


def test_bad_requests_are_refused(client):
    assert save(client, feature="unknown").status_code == 422
    assert save(client, report="").status_code == 422
    assert save(client, report="x" * 300_001).status_code == 422
    assert save(client, score=3, total=None).status_code == 422
    assert save(client, score=-1).status_code == 422
    assert save(client, mistakes=[word("w")] * 61).status_code == 422
    assert save(client, mistakes=[word("")]).status_code == 422
    assert client.get("/api/history/results", params={"limit": 0}).status_code == 422
    assert client.get("/api/history/results").json()["count"] == 0
    # Text is stored as text: nothing in it is ever run as SQL.
    save(client, language="x'; DROP TABLE results; --", mistakes=[word("'); DELETE FROM mistakes; --")])
    assert client.get("/api/history/results").json()["count"] == 1
    assert client.get("/api/history/mistakes", params={"language": "x'; DROP TABLE results; --"}).json()["count"] == 1


def test_vocabulary_can_practise_given_words_without_the_model(client):
    class NoModel:
        async def chat(self, *args, **kwargs):
            raise AssertionError("the model must not be asked")

    app.dependency_overrides[get_chat_provider] = lambda: NoModel()
    body = {"source_language": "English", "target_language": "Japanese",
            "words": [{"word": "dog", "translations": ["犬", "いぬ"]}, {"word": " Dog ", "translations": ["犬"]},
                      {"word": "cat", "translations": ["猫"]}]}
    started = client.post("/api/vocabulary/sessions", json=body).json()
    assert (started["total"], started["word"], started["source_language_code"]) == (2, "dog", "")
    sid = started["session_id"]
    client.post(f"/api/vocabulary/sessions/{sid}/answers", json={"answer": "いぬ"})
    client.post(f"/api/vocabulary/sessions/{sid}/answers", json={"answer": "猫"})
    assert client.get(f"/api/vocabulary/sessions/{sid}/result").json()["score"] == 2
    body["words"] = [{"word": "  ", "translations": ["x"]}]
    assert client.post("/api/vocabulary/sessions", json=body).status_code == 422
    body["words"] = [{"word": "w", "translations": ["x"]}] * 51
    assert client.post("/api/vocabulary/sessions", json=body).status_code == 422
