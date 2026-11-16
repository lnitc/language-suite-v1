"""Feature 13: grammar drills.

Two kinds of exercise on a grammar point the learner chooses (or one the
teacher picks for the level):
  - fill in the blank: a sentence with a gap to complete;
  - correct the mistake: a sentence with one grammar mistake to rewrite.

Marked like vocabulary. The model writes each item together with its
accepted answers, plain code checks the learner's answers against them,
and at the end the model gives a second opinion on the answers the code
marked wrong (a different but correct answer is accepted), with a short
comment on each real mistake.
"""

from __future__ import annotations

import re
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from ..context import feedback_language
from ..providers.base import ChatProvider, ProviderError
from ..providers.factory import get_chat_provider
from ..textutils import normalize, parse_json
from .dictation import DIFFICULTIES

router = APIRouter(prefix="/api/grammar", tags=["grammar"])

DEFAULT_SYSTEM_PROMPT = "You are an experienced grammar teacher who writes clear, correct exercises."
MAX_SESSIONS = 50
MAX_ITEMS = 10
ITEMS_PER_CALL = 5
BLANK = "____"
_BLANK = re.compile(r"_{2,}|[＿]{2,}|（\s*）|\(\s*\)")
KINDS = {
    "gap": "Fill in the blank",
    "fix": "Correct the mistake",
}


@dataclass
class Item:
    kind: str  # "gap" or "fix"
    sentence: str  # gap: with ____ where the answer goes; fix: the sentence with the mistake
    answers: list[str]  # gap: what fits the blank; fix: correct versions of the sentence
    hint: str
    explanation: str


@dataclass
class Session:
    language: str
    difficulty: str
    topic: str
    exercise: str  # "gap", "fix" or "mixed"
    count: int
    system_prompt: str
    session_prompt: str
    items: list[Item] = field(default_factory=list)
    result: dict | None = None


_sessions: OrderedDict[str, Session] = OrderedDict()


class StartRequest(BaseModel):
    language: str = Field(min_length=1, max_length=60)
    difficulty: Literal[
        "beginner", "elementary", "intermediate", "upper_intermediate", "advanced"
    ] = "intermediate"
    topic: str = Field(default="", max_length=200)  # the grammar point; empty: the teacher chooses
    exercise: Literal["gap", "fix", "mixed"] = "mixed"
    count: int = Field(default=5, ge=1, le=MAX_ITEMS)
    system_prompt: str = Field(default="", max_length=2000)
    session_prompt: str = Field(default="", max_length=2000)


class SubmitRequest(BaseModel):
    answers: list[Annotated[str, StringConstraints(max_length=600)]] = Field(max_length=MAX_ITEMS)


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found. Please start a new one.")
    return session


def _one_line(text: object) -> str:
    return " ".join(str(text or "").replace("**", "").split())


def _parse_item(entry: object, allowed: tuple[str, ...]) -> Item | None:
    """Accepts an item only if it can be marked: a usable sentence and answers."""
    if not isinstance(entry, dict):
        return None
    kind = str(entry.get("type") or "").strip().lower()
    kind = {"blank": "gap", "fill": "gap", "correction": "fix", "error": "fix"}.get(kind, kind)
    sentence = _one_line(entry.get("sentence"))
    answers = entry.get("answers")
    if isinstance(answers, str):
        answers = [answers]
    answers = [_one_line(a) for a in (answers if isinstance(answers, list) else []) if _one_line(a)]
    if kind not in allowed or not sentence or not answers:
        return None
    if kind == "gap":
        sentence, blanks = _BLANK.subn(BLANK, sentence)
        if blanks != 1:  # exactly one gap, so there is exactly one thing to mark
            return None
    else:
        answers = [a for a in answers if normalize(a) != normalize(sentence)]
        if not answers:  # the "mistake" sentence is the same as its correction
            return None
    return Item(
        kind=kind,
        sentence=sentence,
        answers=answers[:6],
        hint=_one_line(entry.get("hint"))[:80] if kind == "gap" else "",
        explanation=_one_line(entry.get("explanation")),
    )


async def _write_items(session: Session, count: int, chat: ChatProvider) -> list[Item]:
    allowed = ("gap", "fix") if session.exercise == "mixed" else (session.exercise,)
    parts = [
        f"Write {count} grammar exercise items in {session.language} for a learner at level "
        f"{DIFFICULTIES[session.difficulty].split(':')[0]}.",
        (
            f"Grammar point to practise: {session.topic}."
            if session.topic
            else "Choose grammar points that learners at this level typically need to practise, and vary them."
        ),
    ]
    if session.session_prompt:
        parts.append(f"Learner's instructions for this session: {session.session_prompt}")
    kinds = []
    if "gap" in allowed:
        kinds.append(
            '- "gap" (fill in the blank): "sentence" is a natural sentence with exactly one '
            f'blank written as {BLANK} where the grammar point belongs. "answers" lists every '
            'form that correctly fills the blank (usually one, sometimes two or three). "hint" '
            "is what the learner needs in order to answer, such as the dictionary form of the "
            'verb in brackets, or "" if none is needed.'
        )
    if "fix" in allowed:
        kinds.append(
            '- "fix" (correct the mistake): "sentence" is a sentence with exactly one grammar '
            'mistake of the kind learners really make. "answers" lists the whole corrected '
            "sentence, and other equally correct versions if there are any."
        )
    parts.append(
        "Kinds of item"
        + (" (use both kinds, about half each)" if len(allowed) == 2 else "")
        + ":\n" + "\n".join(kinds)
    )
    parts.append(
        "Rules: the vocabulary must suit the level, so that only the grammar is hard. Each "
        "item must have a clear answer that a careful learner can find. Every sentence is "
        'different. "explanation" states the rule that decides the answer, in one or two '
        "sentences, written in " + feedback_language() + " unless the system prompt asks for another language."
    )
    if session.items:
        parts.append(
            "These sentences already exist. Write different ones:\n"
            + "\n".join(f"- {item.sentence}" for item in session.items)
        )
    parts.append(
        'Reply with JSON only: {"items": [{"type": "gap", "sentence": "...", "answers": ["..."], '
        '"hint": "...", "explanation": "..."}]}.'
    )
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    raw = await chat.chat(messages, json_mode=True, temperature=0.7)
    try:
        entries = parse_json(raw).get("items", [])
    except ValueError:
        entries = []
    seen = {normalize(item.sentence) for item in session.items}
    items = []
    for entry in entries if isinstance(entries, list) else []:
        item = _parse_item(entry, allowed)
        if item and normalize(item.sentence) not in seen and len(items) < count:
            seen.add(normalize(item.sentence))
            items.append(item)
    return items


@router.post("/sessions")
async def start_session(
    req: StartRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = Session(
        language=req.language.strip(),
        difficulty=req.difficulty,
        topic=_one_line(req.topic),
        exercise=req.exercise,
        count=req.count,
        system_prompt=req.system_prompt.strip(),
        session_prompt=req.session_prompt.strip(),
    )
    # A few items per model call, with up to two extra rounds for unusable ones.
    for _ in range(-(-req.count // ITEMS_PER_CALL) + 2):
        missing = req.count - len(session.items)
        if missing <= 0:
            break
        session.items += await _write_items(session, min(missing, ITEMS_PER_CALL), chat)
    if not session.items:
        raise ProviderError(
            "The model did not return usable exercises. Please try again; "
            "if it keeps happening, try a different model."
        )
    session_id = uuid.uuid4().hex
    _sessions[session_id] = session
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return {
        "session_id": session_id,
        "requested": req.count,
        "items": [
            {"number": n, "kind": item.kind, "task": KINDS[item.kind], "sentence": item.sentence, "hint": item.hint}
            for n, item in enumerate(session.items, start=1)
        ],
    }


async def _second_opinion(session: Session, rows: list[dict], chat: ChatProvider) -> None:
    """For answers the code marked wrong: is it really wrong, and why?"""
    doubtful = [row for row in rows if row["status"] == "wrong" and not row["comment"]]
    if not doubtful:
        return
    blocks = []
    for row in doubtful:
        if row["kind"] == "gap":
            blocks.append(
                f"Item {row['number']} (fill in the blank): {row['sentence']}"
                + (f" Hint: {row['hint']}." if row["hint"] else "")
                + f"\nExpected in the blank: {' / '.join(row['correct_answers'])}"
                f"\nThe learner wrote in the blank: {row['your_answer']}"
            )
        else:
            blocks.append(
                f"Item {row['number']} (correct the mistake): {row['sentence']}"
                f"\nExpected: {' / '.join(row['correct_answers'])}"
                f"\nThe learner wrote: {row['your_answer']}"
            )
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"A learner of {session.language} did grammar exercises. The answers below "
                "do not match the expected ones. For each, decide whether the learner's "
                "answer is nevertheless correct: for a blank, it must fit the sentence in "
                "grammar and meaning (and the hint, if there is one); for a correction, the "
                "learner's sentence must be grammatically correct, keep the meaning, and no "
                "longer contain the mistake. Ignore capital letters and punctuation. Be "
                'strict when unsure. For each wrong answer, "comment" says in one sentence '
                "what is wrong with what the learner wrote; for a correct one it is \"\". "
                "Write comments in " + feedback_language() + " unless the system prompt asks for another language.\n\n"
                + "\n\n".join(blocks)
                + '\n\nReply with JSON only: {"verdicts": [{"number": 1, "correct": true, "comment": ""}]}, '
                "using the item numbers above."
            ),
        },
    ]
    try:
        verdicts = parse_json(await chat.chat(messages, json_mode=True, temperature=0.0)).get("verdicts", [])
    except (ProviderError, ValueError):
        return  # no second opinion: the exact-match result stands
    by_number = {row["number"]: row for row in doubtful}
    for verdict in verdicts if isinstance(verdicts, list) else []:
        if not isinstance(verdict, dict):
            continue
        try:
            row = by_number.get(int(verdict.get("number")))
        except (TypeError, ValueError):
            continue
        if row is None:
            continue
        if verdict.get("correct") is True:
            row["status"] = "accepted"
        else:
            row["comment"] = _one_line(verdict.get("comment"))


@router.post("/sessions/{session_id}/submit")
async def submit(
    session_id: str, req: SubmitRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = _get_session(session_id)
    if session.result is not None:
        return session.result

    answers = (req.answers + [""] * len(session.items))[: len(session.items)]
    rows = []
    for number, (item, answer) in enumerate(zip(session.items, answers), start=1):
        answer = _one_line(answer)
        status, comment = "wrong", ""
        if not answer:
            status = "skipped"
        elif normalize(answer) in {normalize(a) for a in item.answers}:
            status = "correct"
        elif item.kind == "fix" and normalize(answer) == normalize(item.sentence):
            comment = "You left the sentence as it was; the mistake is still there."
        rows.append(
            {
                "number": number,
                "kind": item.kind,
                "task": KINDS[item.kind],
                "sentence": item.sentence,
                "hint": item.hint,
                "your_answer": answer,
                "correct_answers": item.answers,
                "status": status,
                "explanation": item.explanation,
                "comment": comment,
            }
        )
    await _second_opinion(session, rows, chat)
    session.result = {
        "language": session.language,
        "topic": session.topic,
        "score": sum(row["status"] in ("correct", "accepted") for row in rows),
        "total": len(rows),
        "items": rows,
    }
    return session.result
