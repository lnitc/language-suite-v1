"""Feature 7: essay writing.

The teacher sets an assignment (or the learner brings an essay of their
own), the learner types or uploads the essay, and the teacher rates it,
gives feedback and corrections, and writes an ideal version.

The marking is two model calls: a structured review (scores, feedback,
corrections), then the ideal version as plain text. A small local model
handles two focused answers more reliably than one very long one.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..providers.base import ChatProvider, ProviderError
from ..providers.factory import get_chat_provider
from ..textutils import parse_json
from .dictation import DIFFICULTIES
from .handwriting import HandwritingRequest, transcribe_handwriting

router = APIRouter(prefix="/api/essay", tags=["essay"])

DEFAULT_SYSTEM_PROMPT = "You are an experienced, encouraging writing teacher."
MAX_SESSIONS = 50
# Above the recommended length the page warns; above the maximum it refuses.
RECOMMENDED_CHARS = 2000
MAX_CHARS = 5000
CRITERIA = (
    ("content", "Content and task", "does it answer the assignment; are the ideas clear and developed"),
    ("organization", "Organisation", "structure, paragraphs, logical flow, linking words"),
    ("vocabulary", "Vocabulary", "range, precision and naturalness of word choice"),
    ("grammar", "Grammar and accuracy", "grammar, spelling, punctuation"),
)
MAX_SCORE = 5


@dataclass
class Session:
    language: str
    difficulty: str
    system_prompt: str
    session_prompt: str
    assignment: str = ""
    # Kept per essay text, so a rewritten essay is marked afresh and a failed
    # second step can be repeated without redoing the first.
    reviewed_text: str = ""
    review: dict | None = None
    result: dict | None = None


_sessions: OrderedDict[str, Session] = OrderedDict()


class StartRequest(BaseModel):
    language: str = Field(min_length=1, max_length=60)
    difficulty: Literal[
        "beginner", "elementary", "intermediate", "upper_intermediate", "advanced"
    ] = "intermediate"
    system_prompt: str = Field(default="", max_length=2000)
    session_prompt: str = Field(default="", max_length=2000)
    with_assignment: bool = True  # False: the learner brings a finished essay


class SubmitRequest(BaseModel):
    text: str = Field(max_length=MAX_CHARS * 4)  # the real limit is checked below, with a clear message


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found. Please start a new one.")
    return session


def _level(session: Session) -> str:
    return DIFFICULTIES[session.difficulty].split(":")[0]


def _plain(text: str) -> str:
    """Model text for display: no markdown symbols, tidy blank lines."""
    lines = [line.strip().lstrip("#>").strip().replace("**", "").replace("__", "") for line in text.strip().splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if line or (cleaned and cleaned[-1]):
            cleaned.append(line)
    return "\n".join(cleaned).strip().strip("`").strip()


async def _write_assignment(session: Session, chat: ChatProvider) -> str:
    parts = [
        f"Set one essay-writing assignment for a learner of {session.language}. "
        f"Learner level: {DIFFICULTIES[session.difficulty]}."
    ]
    if session.session_prompt:
        parts.append(f"Learner's instructions for this session: {session.session_prompt}")
    parts.append(
        f"Write the assignment in {session.language}, in wording the learner can "
        "understand at this level. Give the topic or question, two or three points "
        "to cover, and a suggested length that suits the level (never more than "
        f"about {RECOMMENDED_CHARS} characters of essay). Plain text only, no "
        "markdown, at most 90 words. Reply with the assignment only."
    )
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    assignment = _plain(await chat.chat(messages, temperature=0.9))
    if not assignment:
        raise ProviderError("The model returned no assignment. Please try again.")
    return assignment[:1500]


@router.post("/sessions")
async def start_session(
    req: StartRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = Session(
        language=req.language.strip(),
        difficulty=req.difficulty,
        system_prompt=req.system_prompt.strip(),
        session_prompt=req.session_prompt.strip(),
    )
    if req.with_assignment:
        session.assignment = await _write_assignment(session, chat)
    session_id = uuid.uuid4().hex
    _sessions[session_id] = session
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return {
        "session_id": session_id,
        "assignment": session.assignment,
        "recommended_chars": RECOMMENDED_CHARS,
        "max_chars": MAX_CHARS,
    }


@router.post("/sessions/{session_id}/handwriting")
async def read_handwriting(
    session_id: str,
    req: HandwritingRequest,
    chat: ChatProvider = Depends(get_chat_provider),
) -> dict:
    """Reads a handwritten essay from photos, for the learner to check."""
    session = _get_session(session_id)
    return {"text": await transcribe_handwriting(chat, session.language, req.images, "essay")}


def _task_context(session: Session) -> str:
    if session.assignment:
        return f"The assignment was:\n{session.assignment}"
    if session.session_prompt:
        return (
            "The learner wrote this essay on their own, without an assignment from you. "
            f"What they said about it: {session.session_prompt}"
        )
    return "The learner wrote this essay on their own, without an assignment from you."


async def _review(session: Session, essay: str, chat: ChatProvider) -> dict:
    criteria = "\n".join(f'- "{key}": {label} ({hint})' for key, label, hint in CRITERIA)
    shape = ", ".join(f'"{key}": {{"score": 3, "comment": "..."}}' for key, _, _ in CRITERIA)
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Review this essay written in {session.language} by a learner at level "
                f"{_level(session)}. {_task_context(session)}\n\n"
                f"--- essay ---\n{essay}\n--- end of essay ---\n\n"
                f"Rate each criterion from 1 (weak) to {MAX_SCORE} (excellent), judged "
                "against what can be expected at this level, with a one-sentence comment:\n"
                f"{criteria}\n\n"
                'Then write "feedback": what is good, the main weaknesses, and two or three '
                "concrete tips, in at most 150 words. Then list in \"corrections\" the most "
                "important mistakes, at most eight: \"original\" is the exact sentence or "
                'phrase from the essay, "corrected" is the fixed version, "explanation" is '
                "one short sentence. If something in the essay is marked [?], it could not "
                "be read from handwriting: do not treat it as a mistake.\n\n"
                "Write comments, feedback and explanations in English unless the system "
                f"prompt asks for another language; quote and correct in {session.language}.\n\n"
                f'Reply with JSON only: {{"scores": {{{shape}}}, "feedback": "...", '
                '"corrections": [{"original": "...", "corrected": "...", "explanation": "..."}]}'
            ),
        },
    ]
    raw = await chat.chat(messages, json_mode=True, temperature=0.2)
    try:
        data = parse_json(raw)
    except ValueError:
        data = {}
    scores_in = data.get("scores")
    if not isinstance(scores_in, dict) or not str(data.get("feedback") or "").strip():
        raise ProviderError(
            "The model did not return a usable review. Please press the button again."
        )

    scores = []
    for key, label, _ in CRITERIA:
        entry = scores_in.get(key)
        entry = entry if isinstance(entry, dict) else {"score": entry}
        try:
            score = max(1, min(MAX_SCORE, round(float(entry.get("score")))))
        except (TypeError, ValueError):
            score = None  # shown as "not rated"; left out of the total
        scores.append({"name": label, "score": score, "comment": _plain(str(entry.get("comment") or ""))})

    corrections = []
    entries = data.get("corrections")
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict):
            continue
        row = {name: " ".join(str(entry.get(name) or "").split()) for name in ("original", "corrected", "explanation")}
        if row["original"] and row["corrected"] and row["original"] != row["corrected"]:
            corrections.append(row)
    rated = [row["score"] for row in scores if row["score"] is not None]
    return {
        "scores": scores,
        "total": sum(rated),
        "max_total": MAX_SCORE * len(rated),
        "feedback": _plain(str(data["feedback"])),
        "corrections": corrections[:8],
    }


async def _ideal_version(session: Session, essay: str, chat: ChatProvider) -> str:
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Below is an essay in {session.language} by a learner at level "
                f"{_level(session)}. {_task_context(session)}\n\n"
                f"--- essay ---\n{essay}\n--- end of essay ---\n\n"
                "Write the ideal version of this essay: keep the learner's own ideas and "
                "overall structure where they work, correct every mistake, and improve the "
                "wording and flow. Aim one step above the learner's level, so that they can "
                "learn from it, and keep about the same length. Write in "
                f"{session.language} only. Plain text, no markdown, no title unless the "
                "learner wrote one. Reply with the essay only, without comments."
            ),
        },
    ]
    ideal = _plain(await chat.chat(messages, temperature=0.4))
    if not ideal:
        raise ProviderError("The model returned no ideal version. Please press the button again.")
    return ideal


@router.post("/sessions/{session_id}/submit")
async def submit(
    session_id: str, req: SubmitRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = _get_session(session_id)
    essay = "\n".join(line.rstrip() for line in req.text.strip().splitlines())
    if len(essay) < 20:
        raise HTTPException(422, "The essay is too short to review. Please write a little more.")
    if len(essay) > MAX_CHARS:
        raise HTTPException(
            422,
            f"The essay has {len(essay)} characters. The most this app can review at "
            f"once is {MAX_CHARS}. Please shorten it or check it in two parts.",
        )

    if session.reviewed_text != essay:  # a new or rewritten essay
        session.reviewed_text, session.review, session.result = essay, None, None
    if session.result is not None:
        return session.result
    if session.review is None:
        session.review = await _review(session, essay, chat)
    ideal = await _ideal_version(session, essay, chat)  # if this fails, the review above is kept
    session.result = {
        "language": session.language,
        "assignment": session.assignment,
        "essay": essay,
        "characters": len(essay),
        "over_recommended": len(essay) > RECOMMENDED_CHARS,
        **session.review,
        "ideal": ideal,
    }
    return session.result
