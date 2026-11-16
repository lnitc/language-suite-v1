"""History and mistake review.

Finished results are kept in a small SQLite database on this computer
(by default "data/history.db", which git ignores), so that the learner can
look at earlier sessions, see progress, and review what went wrong.

Two tables:
  - results: one row per finished session, with the score and the report
    text (the same text as the "Download result" file);
  - mistakes: single things the learner got wrong (a word, a grammar item,
    a corrected sentence). The same mistake made again is counted, not
    stored twice.

The app is built for one learner per installation: there are no accounts.
Nothing here is sent anywhere, and no model is involved.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints

router = APIRouter(prefix="/api/history", tags=["history"])

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAX_REPORT_CHARS = 300_000
MAX_MISTAKES_PER_RESULT = 60

Feature = Literal[
    "conversation", "interview", "interpreter", "speech", "shadowing", "listening",
    "vocabulary", "dictation", "essay", "translation", "reading", "grammar",
]
Short = Annotated[str, StringConstraints(max_length=2000)]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    feature TEXT NOT NULL,
    language TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    score REAL,
    total REAL,
    report TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS results_by_date ON results (created_at);
CREATE TABLE IF NOT EXISTS mistakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    feature TEXT NOT NULL,
    language TEXT NOT NULL COLLATE NOCASE,
    prompt TEXT NOT NULL,
    your_answer TEXT NOT NULL DEFAULT '',
    correct TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    extra TEXT NOT NULL DEFAULT '{}',
    times INTEGER NOT NULL DEFAULT 1,
    learned INTEGER NOT NULL DEFAULT 0,
    UNIQUE (feature, language, prompt)
);
"""


def database_path() -> Path:
    """Where the history is kept. HISTORY_DB in ".env" can move it."""
    path = Path(os.getenv("HISTORY_DB", "") or "data/history.db")
    return path if path.is_absolute() else PROJECT_ROOT / path


def _connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    return connection


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Mistake(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)  # the word, question or sentence
    your_answer: Short = ""
    correct: Short = ""
    note: Short = ""  # the rule or explanation
    extra: dict = Field(default_factory=dict)  # what a feature needs to practise it again


class SaveRequest(BaseModel):
    feature: Feature
    language: str = Field(min_length=1, max_length=130)
    title: str = Field(default="", max_length=200)
    score: float | None = Field(default=None, ge=0)
    total: float | None = Field(default=None, gt=0)
    report: str = Field(min_length=1, max_length=MAX_REPORT_CHARS)
    mistakes: list[Mistake] = Field(default_factory=list, max_length=MAX_MISTAKES_PER_RESULT)
    # Things answered correctly this time: a matching earlier mistake counts as learned.
    mastered: list[Short] = Field(default_factory=list, max_length=MAX_MISTAKES_PER_RESULT)


class LearnedRequest(BaseModel):
    learned: bool


def _percent(score: float | None, total: float | None) -> int | None:
    if score is None or not total:
        return None
    return round(min(score / total, 1) * 100)


def _result_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "feature": row["feature"],
        "language": row["language"],
        "title": row["title"],
        "score": row["score"],
        "total": row["total"],
        "percent": _percent(row["score"], row["total"]),
    }


def _mistake_row(row: sqlite3.Row) -> dict:
    try:
        extra = json.loads(row["extra"])
    except ValueError:
        extra = {}
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "feature": row["feature"],
        "language": row["language"],
        "prompt": row["prompt"],
        "your_answer": row["your_answer"],
        "correct": row["correct"],
        "note": row["note"],
        "extra": extra if isinstance(extra, dict) else {},
        "times": row["times"],
        "learned": bool(row["learned"]),
    }


@router.post("/results")
def save_result(req: SaveRequest) -> dict:
    if req.score is not None and req.total is None:
        raise HTTPException(422, "A score needs a total.")
    language = req.language.strip()
    now = _now()
    with closing(_connect()) as db, db:
        result_id = db.execute(
            "INSERT INTO results (created_at, feature, language, title, score, total, report) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, req.feature, language, req.title.strip(), req.score, req.total, req.report),
        ).lastrowid
        for mistake in req.mistakes:
            extra = json.dumps(mistake.extra, ensure_ascii=False)
            if len(extra) > 4000:
                extra = "{}"
            # Made before: count it again, and it is no longer "learned".
            db.execute(
                "INSERT INTO mistakes (created_at, updated_at, feature, language, prompt, "
                "your_answer, correct, note, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (feature, language, prompt) DO UPDATE SET "
                "updated_at = excluded.updated_at, your_answer = excluded.your_answer, "
                "correct = excluded.correct, note = excluded.note, extra = excluded.extra, "
                "times = times + 1, learned = 0",
                (now, now, req.feature, language, mistake.prompt.strip(), mistake.your_answer.strip(),
                 mistake.correct.strip(), mistake.note.strip(), extra),
            )
        for prompt in req.mastered:
            db.execute(
                "UPDATE mistakes SET learned = 1, updated_at = ? "
                "WHERE feature = ? AND language = ? AND prompt = ? AND learned = 0",
                (now, req.feature, language, prompt.strip()),
            )
    return {"id": result_id}


@router.get("/results")
def list_results(
    feature: str = "",
    language: str = "",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    where, values = [], []
    if feature:
        where.append("feature = ?")
        values.append(feature)
    if language:
        where.append("language = ? COLLATE NOCASE")
        values.append(language)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with closing(_connect()) as db:
        count = db.execute(f"SELECT COUNT(*) FROM results{clause}", values).fetchone()[0]
        rows = db.execute(
            "SELECT id, created_at, feature, language, title, score, total FROM results"
            f"{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
            [*values, limit, offset],
        ).fetchall()
        # Progress: per feature, how many sessions, and the average of all
        # scored sessions next to the average of the latest five.
        summary = []
        for group in db.execute(
            f"SELECT feature, COUNT(*) AS sessions, MAX(created_at) AS latest FROM results{clause} "
            "GROUP BY feature ORDER BY latest DESC",
            values,
        ).fetchall():
            scored = [
                _percent(row["score"], row["total"])
                for row in db.execute(
                    "SELECT score, total FROM results WHERE feature = ? AND score IS NOT NULL"
                    + (" AND language = ? COLLATE NOCASE" if language else "")
                    + " ORDER BY id DESC",
                    [group["feature"], *([language] if language else [])],
                ).fetchall()
            ]
            recent = scored[:5]
            summary.append(
                {
                    "feature": group["feature"],
                    "sessions": group["sessions"],
                    "latest": group["latest"],
                    "average": round(sum(scored) / len(scored)) if scored else None,
                    "recent_average": round(sum(recent) / len(recent)) if recent else None,
                }
            )
        languages = [row[0] for row in db.execute("SELECT DISTINCT language FROM results ORDER BY language")]
        features = [row[0] for row in db.execute("SELECT DISTINCT feature FROM results ORDER BY feature")]
    return {
        "count": count,
        "results": [_result_row(row) for row in rows],
        "summary": summary,
        "languages": languages,
        "features": features,
    }


@router.get("/results/{result_id}")
def get_result(result_id: int) -> dict:
    with closing(_connect()) as db:
        row = db.execute("SELECT * FROM results WHERE id = ?", (result_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "This result is no longer in the history.")
    return {**_result_row(row), "report": row["report"]}


@router.delete("/results/{result_id}")
def delete_result(result_id: int) -> dict:
    with closing(_connect()) as db, db:
        deleted = db.execute("DELETE FROM results WHERE id = ?", (result_id,)).rowcount
    return {"deleted": deleted}


@router.delete("/results")
def delete_all_results() -> dict:
    with closing(_connect()) as db, db:
        deleted = db.execute("DELETE FROM results").rowcount
    return {"deleted": deleted}


@router.get("/mistakes")
def list_mistakes(
    feature: str = "",
    language: str = "",
    learned: bool | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    where, values = [], []
    if feature:
        where.append("feature = ?")
        values.append(feature)
    if language:
        where.append("language = ?")
        values.append(language)
    if learned is not None:
        where.append("learned = ?")
        values.append(int(learned))
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    with closing(_connect()) as db:
        count = db.execute(f"SELECT COUNT(*) FROM mistakes{clause}", values).fetchone()[0]
        rows = db.execute(
            f"SELECT * FROM mistakes{clause} ORDER BY updated_at DESC, id DESC LIMIT ?", [*values, limit]
        ).fetchall()
        languages = [row[0] for row in db.execute("SELECT DISTINCT language FROM mistakes ORDER BY language")]
        features = [row[0] for row in db.execute("SELECT DISTINCT feature FROM mistakes ORDER BY feature")]
    return {
        "count": count,
        "mistakes": [_mistake_row(row) for row in rows],
        "languages": languages,
        "features": features,
    }


@router.patch("/mistakes/{mistake_id}")
def mark_mistake(mistake_id: int, req: LearnedRequest) -> dict:
    with closing(_connect()) as db, db:
        changed = db.execute(
            "UPDATE mistakes SET learned = ? WHERE id = ?", (int(req.learned), mistake_id)
        ).rowcount
    if not changed:
        raise HTTPException(404, "This entry is no longer in the list.")
    return {"id": mistake_id, "learned": req.learned}


@router.delete("/mistakes/{mistake_id}")
def delete_mistake(mistake_id: int) -> dict:
    with closing(_connect()) as db, db:
        deleted = db.execute("DELETE FROM mistakes WHERE id = ?", (mistake_id,)).rowcount
    return {"deleted": deleted}


@router.delete("/mistakes")
def delete_mistakes(learned: bool | None = None) -> dict:
    """Empties the list; with learned=true only the entries marked as learned."""
    with closing(_connect()) as db, db:
        if learned is None:
            deleted = db.execute("DELETE FROM mistakes").rowcount
        else:
            deleted = db.execute("DELETE FROM mistakes WHERE learned = ?", (int(learned),)).rowcount
    return {"deleted": deleted}
