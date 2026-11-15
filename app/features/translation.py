"""Feature 9: written translation.

The teacher writes a text in the source language (or the learner brings a
text and a translation of their own), the learner types or uploads the
translation, and the teacher rates it, gives feedback and corrections, and
writes an ideal translation.

Marked like an essay, in two model calls: a structured review, then the
ideal translation as plain text. The ideal translation is checked by the
code for being in the right language, as in the interpreter feature.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..providers.base import ChatProvider, ProviderError
from ..providers.factory import get_chat_provider
from ..textutils import normalize, parse_json
from .dictation import DIFFICULTIES
from .essay import MAX_SCORE, _plain
from .handwriting import HandwritingRequest, transcribe_handwriting
from .interpreter import script_of

router = APIRouter(prefix="/api/translation", tags=["translation"])

DEFAULT_SYSTEM_PROMPT = "You are an experienced translator and translation teacher."
MAX_SESSIONS = 50
# Limits for the source text and for the translation, each. Above the
# recommended length the page warns; above the maximum it refuses. They are
# lower than for an essay: the model reads two texts and writes a third.
RECOMMENDED_CHARS = 1500
MAX_CHARS = 3000
# Length of a text written by the teacher: words, or characters for
# languages written without spaces.
LENGTHS = {"short": (60, 120), "medium": (120, 250), "long": (200, 400)}
CRITERIA = (
    ("accuracy", "Accuracy", "is the meaning of the source carried over correctly, without mistranslations"),
    ("completeness", "Completeness", "is everything translated, with nothing left out and nothing added"),
    ("naturalness", "Naturalness", "does it read like a text written in the target language: word order, style, register"),
    ("language", "Grammar and vocabulary", "grammar, word choice and spelling in the target language"),
)


@dataclass
class Session:
    source_language: str
    target_language: str
    difficulty: str
    system_prompt: str
    session_prompt: str
    source_text: str = ""  # empty until the learner supplies one, in "own text" mode
    own_text: bool = False
    # Kept for one pair of texts, so a reworked translation is marked afresh
    # and a failed second step can be repeated without redoing the first.
    marked: tuple[str, str] = ("", "")
    review: dict | None = None
    result: dict | None = None


_sessions: OrderedDict[str, Session] = OrderedDict()


class StartRequest(BaseModel):
    source_language: str = Field(min_length=1, max_length=60)
    target_language: str = Field(min_length=1, max_length=60)
    difficulty: Literal[
        "beginner", "elementary", "intermediate", "upper_intermediate", "advanced"
    ] = "intermediate"
    length: Literal["short", "medium", "long"] = "medium"
    system_prompt: str = Field(default="", max_length=2000)
    session_prompt: str = Field(default="", max_length=2000)
    with_text: bool = True  # False: the learner brings a text and its translation


class SubmitRequest(BaseModel):
    translation: str = Field(max_length=MAX_CHARS * 4)  # real limits are checked below, with clear messages
    source_text: str = Field(default="", max_length=MAX_CHARS * 4)  # only in "own text" mode


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found. Please start a new one.")
    return session


def _tidy(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


async def _write_source_text(session: Session, length: str, chat: ChatProvider) -> str:
    words, characters = LENGTHS[length]
    parts = [
        f"Write a text in {session.source_language} for a translation exercise: the "
        f"learner will translate it into {session.target_language}. "
        f"Level: {DIFFICULTIES[session.difficulty]}.",
        f"Length: about {words} words. If {session.source_language} is written without "
        f"spaces between words (like Japanese or Chinese), about {characters} characters instead.",
    ]
    if session.session_prompt:
        parts.append(f"Learner's instructions for this session: {session.session_prompt}")
    parts.append(
        "Write one coherent passage (for example part of an article, a letter, a story "
        "or a description) with varied sentence structures and a few expressions that "
        "are interesting to translate at this level. Plain text in paragraphs, no "
        "title, no markdown, no translation, no comments. Reply with the text only."
    )
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    text = _plain(await chat.chat(messages, temperature=0.9))
    if len(text) < 20:
        raise ProviderError("The model returned no usable text. Please try again.")
    return text[:MAX_CHARS]


@router.post("/sessions")
async def start_session(
    req: StartRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = Session(
        source_language=req.source_language.strip(),
        target_language=req.target_language.strip(),
        difficulty=req.difficulty,
        system_prompt=req.system_prompt.strip(),
        session_prompt=req.session_prompt.strip(),
        own_text=not req.with_text,
    )
    if req.with_text:
        session.source_text = await _write_source_text(session, req.length, chat)
    session_id = uuid.uuid4().hex
    _sessions[session_id] = session
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return {
        "session_id": session_id,
        "source_text": session.source_text,
        "recommended_chars": RECOMMENDED_CHARS,
        "max_chars": MAX_CHARS,
    }


@router.post("/sessions/{session_id}/handwriting")
async def read_handwriting(
    session_id: str,
    req: HandwritingRequest,
    chat: ChatProvider = Depends(get_chat_provider),
) -> dict:
    """Reads a handwritten translation from photos, for the learner to check."""
    session = _get_session(session_id)
    text = await transcribe_handwriting(chat, session.target_language, req.images, "translation")
    return {"text": text}


def _texts(session: Session, source: str, translation: str) -> str:
    return (
        f"--- source text ({session.source_language}) ---\n{source}\n--- end of source text ---\n\n"
        f"--- learner's translation ({session.target_language}) ---\n{translation}\n--- end of translation ---"
    )


async def _review(session: Session, source: str, translation: str, chat: ChatProvider) -> dict:
    level = DIFFICULTIES[session.difficulty].split(":")[0]
    criteria = "\n".join(f'- "{key}": {label} ({hint})' for key, label, hint in CRITERIA)
    shape = ", ".join(f'"{key}": {{"score": 3, "comment": "..."}}' for key, _, _ in CRITERIA)
    context = (
        f" What the learner said about it: {session.session_prompt}"
        if session.own_text and session.session_prompt
        else ""
    )
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Review this translation from {session.source_language} into "
                f"{session.target_language}, made by a learner at level {level}.{context}\n\n"
                f"{_texts(session, source, translation)}\n\n"
                f"Rate each criterion from 1 (weak) to {MAX_SCORE} (excellent), judged "
                "against what can be expected at this level, with a one-sentence comment:\n"
                f"{criteria}\n\n"
                'Then write "feedback": what is good, the main weaknesses, and two or three '
                "concrete tips for translating better, in at most 150 words. Then list in "
                '"corrections" the most important problems, at most eight: "source" is the '
                'phrase of the source text concerned, "yours" is how the learner translated '
                'it (or "" if they left it out), "better" is a better translation of that '
                f'phrase in {session.target_language}, "explanation" is one short sentence. '
                "If something in the translation is marked [?], it could not be read from "
                "handwriting: do not treat it as a mistake.\n\n"
                "Write comments, feedback and explanations in English unless the system "
                "prompt asks for another language.\n\n"
                f'Reply with JSON only: {{"scores": {{{shape}}}, "feedback": "...", '
                '"corrections": [{"source": "...", "yours": "...", "better": "...", "explanation": "..."}]}'
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
        row = {name: " ".join(str(entry.get(name) or "").split()) for name in ("source", "yours", "better", "explanation")}
        if row["better"] and row["better"] != row["yours"]:
            corrections.append(row)
    rated = [row["score"] for row in scores if row["score"] is not None]
    return {
        "scores": scores,
        "total": sum(rated),
        "max_total": MAX_SCORE * len(rated),
        "feedback": _plain(str(data["feedback"])),
        "corrections": corrections[:8],
    }


def wrong_language(ideal: str, source: str, translation: str) -> bool:
    """True if the "ideal translation" looks like the source language.

    The code cannot read languages. It can tell writing systems apart, using
    the learner's own translation as the sample of the target language, and
    it can notice an "ideal" that is almost a copy of the source text.
    """
    source_script, target_script = script_of(source), script_of(translation)
    if source_script and target_script and source_script != target_script:
        return script_of(ideal) != target_script
    return SequenceMatcher(None, normalize(source), normalize(ideal), autojunk=False).ratio() > 0.7


async def _ideal_translation(session: Session, source: str, translation: str, chat: ChatProvider) -> str:
    request = (
        f"Below are a source text in {session.source_language} and a learner's translation "
        f"into {session.target_language}.\n\n{_texts(session, source, translation)}\n\n"
        f"Write the ideal translation of the source text into {session.target_language}: "
        "accurate, complete and natural, as a skilled translator would write it. Where the "
        "learner's wording is already good, keep it, so that they can see what to change. "
        f"Write {session.target_language} only: do not repeat the source text. Plain text, "
        "no markdown, no comments. Reply with the translation only."
    )
    system = {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT}
    ideal = _plain(await chat.chat([system, {"role": "user", "content": request}], temperature=0.3))
    if ideal and wrong_language(ideal, source, translation):
        # Ask once more, with nothing to confuse the two languages: only the source text.
        retry = (
            f"Translate the following text from {session.source_language} into "
            f"{session.target_language}. Your whole answer must be in {session.target_language}. "
            f"Plain text, the translation only.\n\n{source}"
        )
        second = _plain(await chat.chat([system, {"role": "user", "content": retry}], temperature=0.2))
        certain = script_of(source) != script_of(translation)  # only writing systems give certainty
        if second and not (certain and wrong_language(second, source, translation)):
            ideal = second
        elif certain:
            ideal = ""
    if not ideal:
        raise ProviderError(
            "The model did not return an ideal translation in the right language. "
            "Please press the button again."
        )
    return ideal


def _check_length(text: str, what: str) -> None:
    if len(text) > MAX_CHARS:
        raise HTTPException(
            422,
            f"The {what} has {len(text)} characters. The most this app can review at "
            f"once is {MAX_CHARS}. Please shorten it or check it in two parts.",
        )


@router.post("/sessions/{session_id}/submit")
async def submit(
    session_id: str, req: SubmitRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = _get_session(session_id)
    source = _tidy(req.source_text) if session.own_text else session.source_text
    translation = _tidy(req.translation)
    if len(source) < 5:
        raise HTTPException(422, "Please enter the source text as well as your translation.")
    if len(translation) < 5:
        raise HTTPException(422, "The translation is too short to review.")
    _check_length(source, "source text")
    _check_length(translation, "translation")

    if session.marked != (source, translation):  # new or reworked texts
        session.marked, session.review, session.result = (source, translation), None, None
    if session.result is not None:
        return session.result
    if session.review is None:
        session.review = await _review(session, source, translation, chat)
    ideal = await _ideal_translation(session, source, translation, chat)  # if this fails, the review is kept
    session.result = {
        "source_language": session.source_language,
        "target_language": session.target_language,
        "source_text": source,
        "translation": translation,
        "over_recommended": max(len(source), len(translation)) > RECOMMENDED_CHARS,
        **session.review,
        "ideal": ideal,
    }
    return session.result
