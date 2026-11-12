"""Feature 3: interpreter simulation (consecutive interpreting).

The model writes a text in the source language. It is spoken in batches of
a few sentences; after each batch the learner says their interpretation,
which the ear turns into text. At the end the model gives an ideal version
and a comment for every batch.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StringConstraints

from ..providers.base import ChatProvider, ProviderError
from ..providers.factory import get_chat_provider
from ..textutils import parse_json
from .dictation import DIFFICULTIES
from .speech import clean_language_code

router = APIRouter(prefix="/api/interpreter", tags=["interpreter"])

DEFAULT_SYSTEM_PROMPT = "You are an experienced interpreter trainer."
MAX_SESSIONS = 50


@dataclass
class Session:
    source_language: str
    target_language: str
    system_prompt: str
    batches: list[str]
    result: dict | None = None


_sessions: OrderedDict[str, Session] = OrderedDict()


class StartRequest(BaseModel):
    source_language: str = Field(min_length=1, max_length=60)
    target_language: str = Field(min_length=1, max_length=60)
    difficulty: Literal[
        "beginner", "elementary", "intermediate", "upper_intermediate", "advanced"
    ] = "intermediate"
    sentences_per_batch: int = Field(default=2, ge=1, le=5)
    batch_count: int = Field(default=4, ge=1, le=10)
    system_prompt: str = Field(default="", max_length=2000)
    session_prompt: str = Field(default="", max_length=2000)


class SubmitRequest(BaseModel):
    interpretations: list[Annotated[str, StringConstraints(max_length=4000)]] = Field(max_length=20)


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found. Please start a new one.")
    return session


@router.post("/sessions")
async def start_session(
    req: StartRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    total = req.sentences_per_batch * req.batch_count
    parts = [
        f"Write one coherent text in {req.source_language}, as exactly {total} sentences, "
        f"for consecutive interpreting practice into {req.target_language}. It should "
        "sound like a real speaker: a talk, an announcement, a meeting or an interview answer.",
        f"Level: {DIFFICULTIES[req.difficulty]}.",
    ]
    if req.session_prompt.strip():
        parts.append(f"Learner's instructions for this session: {req.session_prompt.strip()}")
    parts.append(
        "The sentences will be read aloud: no lists, no abbreviations, no symbols, "
        "and spell numbers out in words."
    )
    parts.append(
        'Reply with JSON only: {"source_language_code": "...", "target_language_code": '
        '"...", "sentences": ["...", "..."]}. The codes are BCP-47 codes such as '
        '"en-US" or "ja-JP". Each entry of "sentences" is exactly one sentence.'
    )
    messages = [
        {"role": "system", "content": req.system_prompt.strip() or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    raw = await chat.chat(messages, json_mode=True, temperature=0.8)
    try:
        data = parse_json(raw)
    except ValueError:
        data = {}
    entries = data.get("sentences", [])
    sentences = [
        " ".join(entry.split())[:400]
        for entry in (entries if isinstance(entries, list) else [])
        if isinstance(entry, str) and entry.strip()
    ][:total]
    if not sentences:
        raise ProviderError(
            "The model did not return a usable text. Please try again; "
            "if it keeps happening, try a different model."
        )
    size = req.sentences_per_batch
    batches = [" ".join(sentences[i : i + size]) for i in range(0, len(sentences), size)]

    session_id = uuid.uuid4().hex
    _sessions[session_id] = Session(
        source_language=req.source_language.strip(),
        target_language=req.target_language.strip(),
        system_prompt=req.system_prompt.strip(),
        batches=batches,
    )
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return {
        "session_id": session_id,
        # The browser speaks the batches, so it needs the text. Not shown on screen.
        "batches": batches,
        "source_language_code": clean_language_code(data.get("source_language_code")),
        "target_language_code": clean_language_code(data.get("target_language_code")),
    }


@router.post("/sessions/{session_id}/submit")
async def submit(
    session_id: str, req: SubmitRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = _get_session(session_id)
    if session.result is not None:
        return session.result

    count = len(session.batches)
    said = [" ".join(text.split()) for text in (req.interpretations + [""] * count)[:count]]
    blocks = [
        f"Batch {i}\nOriginal ({session.source_language}): {original}\n"
        f"Learner's interpretation ({session.target_language}): {spoken or '(nothing said)'}"
        for i, (original, spoken) in enumerate(zip(session.batches, said), start=1)
    ]
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"A learner practised consecutive interpreting from {session.source_language} "
                f"into {session.target_language}. Their interpretations come from speech "
                "recognition, so ignore punctuation and allow for small recognition slips.\n\n"
                + "\n\n".join(blocks)
                + '\n\nReply with JSON only: {"batches": [{"ideal": "...", "comment": "..."}], '
                f'"overall": "..."}}. Give exactly {count} entries in "batches", in order. '
                f'"ideal" is a natural, accurate {session.target_language} interpretation of '
                'the original. "comment" is one to three sentences on meaning errors, '
                'omissions, additions and language mistakes, or praise if it was good. '
                '"overall" is a short summary with two or three tips. Write comments and '
                "the summary in English unless the system prompt asks for another language."
            ),
        },
    ]
    raw = await chat.chat(messages, json_mode=True, temperature=0.3)
    try:
        data = parse_json(raw)
    except ValueError:
        raise ProviderError(
            "The model did not return usable feedback. Please press the button again."
        ) from None
    reviews = data.get("batches", [])
    reviews = reviews if isinstance(reviews, list) else []

    rows = []
    for i, (original, spoken) in enumerate(zip(session.batches, said)):
        review = reviews[i] if i < len(reviews) and isinstance(reviews[i], dict) else {}
        rows.append(
            {
                "number": i + 1,
                "original": original,
                "interpretation": spoken,
                "ideal": str(review.get("ideal", "")).strip(),
                "comment": str(review.get("comment", "")).strip(),
            }
        )
    session.result = {
        "source_language": session.source_language,
        "target_language": session.target_language,
        "batches": rows,
        "overall": str(data.get("overall", "")).strip(),
    }
    return session.result
