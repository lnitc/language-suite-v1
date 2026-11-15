"""Feature 11: shadowing (listen and repeat).

The learner hears a sentence, says it, and sees which words the speech
recognition understood. It is the closest this app can come to pronunciation
practice: the app cannot hear *how* a word was said, only whether the ear
(speech to text) could make it out.

  - The model writes the sentences (or picks them from the learner's material).
  - The browser speaks each one and records the learner repeating it.
  - Plain code compares what was recognised with the sentence.
  - At the end the model gives tips for the words that were not recognised.
"""

from __future__ import annotations

import uuid
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..context import feedback_language
from ..providers.base import ChatProvider, ProviderError
from ..providers.factory import get_chat_provider
from ..textutils import compare, parse_json
from .dictation import DIFFICULTIES
from .speech import clean_language_code

router = APIRouter(prefix="/api/shadowing", tags=["shadowing"])

DEFAULT_SYSTEM_PROMPT = "You are a patient pronunciation and speaking coach."
MAX_SESSIONS = 50
MAX_SENTENCES = 10
MAX_MATERIAL_CHARS = 8000
_PUNCTUATION = " .,!?;:…\"'()[]。、！？「」『』（）"


@dataclass
class Sentence:
    text: str
    attempts: int = 0
    best: dict | None = None  # the best attempt so far: its marking


@dataclass
class Session:
    language: str
    difficulty: str
    system_prompt: str
    language_code: str
    sentences: list[Sentence]
    result: dict | None = field(default=None)


_sessions: OrderedDict[str, Session] = OrderedDict()


class StartRequest(BaseModel):
    language: str = Field(min_length=1, max_length=60)
    difficulty: Literal[
        "beginner", "elementary", "intermediate", "upper_intermediate", "advanced"
    ] = "intermediate"
    count: int = Field(default=5, ge=1, le=MAX_SENTENCES)
    system_prompt: str = Field(default="", max_length=2000)
    session_prompt: str = Field(default="", max_length=2000)
    material: str = Field(default="", max_length=200_000)  # the learner's own text, if any


class AttemptRequest(BaseModel):
    index: int = Field(ge=0, lt=MAX_SENTENCES)
    text: str = Field(default="", max_length=2000)  # what the speech recognition heard


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found. Please start a new one.")
    return session


def _percent(marking: dict) -> int:
    return round(100 * marking["correct"] / marking["total"]) if marking["total"] else 0


@router.post("/sessions")
async def start_session(
    req: StartRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    material = req.material.strip()[:MAX_MATERIAL_CHARS]
    if material:
        task = (
            f"From the learner's material below, take {req.count} sentences in {req.language} "
            "that are good for listen-and-repeat practice. Copy them exactly as they are "
            "written, in their original order. If a sentence is very long, use a shorter "
            "one instead, or only its main clause.\n"
            f"--- material ---\n{material}\n--- end material ---"
        )
    else:
        task = (
            f"Write {req.count} separate sentences in {req.language} for listen-and-repeat "
            f"(shadowing) practice. Level: {DIFFICULTIES[req.difficulty]}. Each sentence "
            "should be natural spoken language, short enough to remember and repeat in "
            "one breath, and together they should cover a variety of sounds and rhythms."
        )
    parts = [task]
    if req.session_prompt.strip():
        parts.append(f"Learner's instructions for this session: {req.session_prompt.strip()}")
    parts.append(
        "The sentences are read aloud and then compared word by word with what the "
        "learner says: no lists, no abbreviations, no symbols, and spell numbers out in words."
    )
    parts.append(
        'Reply with JSON only: {"language_code": "...", "sentences": ["...", "..."]}. '
        '"language_code" is the BCP-47 code of the sentences, such as "en-US" or "ja-JP".'
    )
    messages = [
        {"role": "system", "content": req.system_prompt.strip() or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    try:
        data = parse_json(await chat.chat(messages, json_mode=True, temperature=0.8))
    except ValueError:
        data = {}
    entries = data.get("sentences", [])
    texts = [
        " ".join(entry.split())[:300]
        for entry in (entries if isinstance(entries, list) else [])
        if isinstance(entry, str) and entry.strip()
    ][: req.count]
    if not texts:
        raise ProviderError(
            "The model did not return usable sentences. Please try again; "
            "if it keeps happening, try a different model."
        )
    session = Session(
        language=req.language.strip(),
        difficulty=req.difficulty,
        system_prompt=req.system_prompt.strip(),
        language_code=clean_language_code(data.get("language_code")),
        sentences=[Sentence(text) for text in texts],
    )
    session_id = uuid.uuid4().hex
    _sessions[session_id] = session
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return {"session_id": session_id, "language_code": session.language_code, "sentences": texts}


@router.post("/sessions/{session_id}/attempts")
async def record_attempt(session_id: str, req: AttemptRequest) -> dict:
    """Marks one attempt. No model is involved: the recognised words are
    compared with the sentence by plain code."""
    session = _get_session(session_id)
    if req.index >= len(session.sentences):
        raise HTTPException(404, "No such sentence.")
    sentence = session.sentences[req.index]
    marking = compare(sentence.text, " ".join(req.text.split()))
    sentence.attempts += 1
    if sentence.best is None or _percent(marking) > _percent(sentence.best):
        sentence.best = marking
    session.result = None  # a new attempt changes the summary
    return {
        "index": req.index,
        "attempt": sentence.attempts,
        "percent": _percent(marking),
        "best_percent": _percent(sentence.best),
        "expected": marking["expected"],
        "heard": marking["typed"],
        "joiner": marking["joiner"],
    }


async def _tips(session: Session, missed: list[str], chat: ChatProvider) -> str:
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"A learner of {session.language} repeated sentences aloud, and speech "
                "recognition could not make out the words or characters listed below "
                "(most often missed first). You did not hear the learner, so do not "
                "guess what they said. Explain briefly what is usually hard about saying "
                "these (sounds, stress, length, linking between words) and give two or "
                "three practical exercises. Plain text, no markdown, at most 120 words. "
                "Write in " + feedback_language() + " unless the system prompt asks for another language.\n\n"
                + ", ".join(missed)
            ),
        },
    ]
    try:
        return (await chat.chat(messages, temperature=0.4)).replace("**", "").strip()
    except ProviderError:
        return ""  # the summary stands without the tips


@router.post("/sessions/{session_id}/finish")
async def finish(
    session_id: str, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = _get_session(session_id)
    if session.result is not None:
        return session.result

    rows, missed = [], Counter()
    for number, sentence in enumerate(session.sentences, start=1):
        words = [
            token["text"].strip(_PUNCTUATION) or token["text"]
            for token in (sentence.best or {}).get("expected", [])
            if not token["ok"]
        ]
        missed.update(words)
        rows.append(
            {
                "number": number,
                "text": sentence.text,
                "attempts": sentence.attempts,
                "best_percent": _percent(sentence.best) if sentence.best else None,
                "missed": words,
            }
        )
    practised = [row["best_percent"] for row in rows if row["best_percent"] is not None]
    top_missed = [word for word, _ in missed.most_common(15)]
    session.result = {
        "language": session.language,
        "average": round(sum(practised) / len(practised)) if practised else None,
        "practised": len(practised),
        "sentences": rows,
        "missed_words": top_missed,
        "tips": await _tips(session, top_missed, chat) if top_missed else "",
    }
    return session.result
