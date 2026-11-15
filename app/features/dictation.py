"""Feature 5: dictation (typed).

Flow: the model writes a short text as separate sentences, each sentence is
spoken (by the browser's voices or a speech server), the learner types what
they hear, plain code marks every word, and the model writes the feedback.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, StringConstraints

from ..providers.base import ChatProvider, ProviderError, TextToSpeech
from ..providers.factory import get_chat_provider, get_speech_provider
from ..context import feedback_language
from ..textutils import compare, parse_json, split_by_sentence
from .handwriting import HandwritingRequest, transcribe_handwriting
from .speech import clean_language_code

router = APIRouter(prefix="/api/dictation", tags=["dictation"])

DEFAULT_SYSTEM_PROMPT = "You are a careful, encouraging language teacher."
MAX_SESSIONS = 50
MAX_SENTENCE_CHARS = 400
MAX_MATERIAL_CHARS = 8000
SENTENCE_COUNTS = {"short": 3, "medium": 6, "long": 10}
DIFFICULTIES = {
    "beginner": "Beginner (CEFR A1): very short sentences, only the most common words",
    "elementary": "Elementary (CEFR A2): short sentences, everyday vocabulary",
    "intermediate": "Intermediate (CEFR B1): medium-length sentences, common vocabulary",
    "upper_intermediate": "Upper-intermediate (CEFR B2): longer sentences, wider vocabulary",
    "advanced": "Advanced (CEFR C1): complex sentences, rich vocabulary",
}


@dataclass
class Session:
    language: str
    language_code: str
    difficulty: str
    system_prompt: str
    sentences: list[str]
    audio: dict[int, bytes] = field(default_factory=dict)
    result: dict | None = None


_sessions: OrderedDict[str, Session] = OrderedDict()


class StartRequest(BaseModel):
    language: str = Field(min_length=1, max_length=60)
    difficulty: Literal[
        "beginner", "elementary", "intermediate", "upper_intermediate", "advanced"
    ] = "intermediate"
    length: Literal["short", "medium", "long"] = "medium"
    system_prompt: str = Field(default="", max_length=2000)
    session_prompt: str = Field(default="", max_length=2000)
    material: str = Field(default="", max_length=200_000)


class SubmitRequest(BaseModel):
    # Typed dictation: one answer per sentence.
    answers: list[Annotated[str, StringConstraints(max_length=2000)]] = Field(
        default_factory=list, max_length=50
    )
    # Handwritten dictation: the whole text as read from the photo.
    full_text: str | None = Field(default=None, max_length=20000)


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found. Please start a new one.")
    return session


async def _generate_text(req: StartRequest, chat: ChatProvider) -> tuple[list[str], str]:
    count = SENTENCE_COUNTS[req.length]
    parts = [
        f"Write one short, coherent text in {req.language} for a dictation exercise, "
        f"as exactly {count} sentences.",
        f"Level: {DIFFICULTIES[req.difficulty]}.",
    ]
    if req.session_prompt.strip():
        parts.append(f"Learner's instructions for this session: {req.session_prompt.strip()}")
    material = req.material.strip()[:MAX_MATERIAL_CHARS]
    if material:
        parts.append(
            "The learner uploaded the material below. If it is a list of words or "
            "phrases, use as many of them as fit naturally in the text. If it is a "
            "text, base the dictation on its content and vocabulary, in your own "
            f"sentences at the requested level. Entries not in {req.language} "
            f"should be used in their {req.language} form.\n"
            f"--- material ---\n{material}\n--- end material ---"
        )
    parts.append(
        "The sentences will be read aloud, so use natural spoken-style prose: "
        "no lists, no abbreviations, no symbols, and spell numbers out in words."
    )
    parts.append(
        'Reply with JSON only, in this shape: {"language_code": "...", '
        '"sentences": ["...", "..."]}. "language_code" is the BCP-47 code of the '
        'text, such as "en-US", "ja-JP" or "es-ES". Each entry of "sentences" is '
        "exactly one sentence."
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
        " ".join(str(entry).split())[:MAX_SENTENCE_CHARS]
        for entry in (entries if isinstance(entries, list) else [])
        if isinstance(entry, str) and entry.strip()
    ][:count]
    if not sentences:
        raise ProviderError(
            "The model did not return a usable dictation text. Please try again; "
            "if it keeps happening, try a different model."
        )
    return sentences, clean_language_code(data.get("language_code"))


async def _teacher_feedback(
    session: Session, rows: list[dict], chat: ChatProvider
) -> str | None:
    mistakes = [row for row in rows if row["correct"] < row["total"]]
    if not mistakes:
        return "Perfect dictation: every word matches the original. Try a harder level or a longer text next time."
    lines = [
        f"{row['number']}. Original: {row['original']}\n"
        f"   Learner: {row['typed'] or '(nothing typed)'}"
        for row in mistakes
    ]
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"A learner did a dictation in {session.language} "
                f"({DIFFICULTIES[session.difficulty]}). Below are the sentences "
                "where what they typed differs from the original. Punctuation and "
                "capital letters were not checked, so do not comment on them.\n\n"
                + "\n".join(lines)
                + "\n\nGive short, specific feedback, speaking to the learner "
                "directly: first the patterns behind the mistakes (for example "
                "spelling, word endings, sounds that were misheard, missing "
                "words), then two or three concrete tips. Plain text without "
                "markdown, at most 150 words. Write in " + feedback_language() + " unless the system "
                "prompt asks for another language."
            ),
        },
    ]
    try:
        return (await chat.chat(messages, temperature=0.4)).strip() or None
    except ProviderError:
        return None  # The marking still stands without the teacher's comment.


@router.post("/sessions")
async def start_session(
    req: StartRequest,
    chat: ChatProvider = Depends(get_chat_provider),
    tts: TextToSpeech | None = Depends(get_speech_provider),
) -> dict:
    sentences, language_code = await _generate_text(req, chat)
    session_id = uuid.uuid4().hex
    _sessions[session_id] = Session(
        language=req.language.strip(),
        language_code=language_code,
        difficulty=req.difficulty,
        system_prompt=req.system_prompt.strip(),
        sentences=sentences,
    )
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)

    speech: dict = {"mode": "server" if tts else "browser", "language_code": language_code}
    if tts is None:
        # The browser speaks, so it needs the text. It is never shown on screen.
        speech["texts"] = sentences
    return {"session_id": session_id, "total": len(sentences), "speech": speech}


@router.get("/sessions/{session_id}/audio/{index}")
async def sentence_audio(
    session_id: str,
    index: int,
    tts: TextToSpeech | None = Depends(get_speech_provider),
) -> Response:
    session = _get_session(session_id)
    if tts is None:
        raise HTTPException(404, "Server speech is off (TTS_PROVIDER is 'browser').")
    if not 0 <= index < len(session.sentences):
        raise HTTPException(404, "No such sentence.")
    if index not in session.audio:  # generated once, so "repeat" is instant
        session.audio[index] = await tts.synthesize(
            session.sentences[index], language=session.language_code or None
        )
    return Response(
        content=session.audio[index],
        media_type=tts.media_type,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/sessions/{session_id}/handwriting")
async def read_handwriting(
    session_id: str,
    req: HandwritingRequest,
    chat: ChatProvider = Depends(get_chat_provider),
) -> dict:
    """Reads the learner's handwriting from photos. Returns the text for the
    learner to check before it is marked.

    The model is not told the original text, so it cannot "see" what the
    learner was supposed to write and quietly repair mistakes.
    """
    session = _get_session(session_id)
    return {"text": await transcribe_handwriting(chat, session.language, req.images, "dictation")}


@router.post("/sessions/{session_id}/submit")
async def submit(
    session_id: str,
    req: SubmitRequest,
    chat: ChatProvider = Depends(get_chat_provider),
) -> dict:
    session = _get_session(session_id)
    if session.result is not None:
        return session.result

    if req.full_text is not None:
        answers = split_by_sentence(session.sentences, req.full_text)
    else:
        answers = (req.answers + [""] * len(session.sentences))[: len(session.sentences)]
    rows = []
    for number, (original, typed) in enumerate(zip(session.sentences, answers), start=1):
        typed = " ".join(typed.split())
        rows.append({"number": number, "original": original, "typed": typed, **compare(original, typed)})

    correct = sum(row["correct"] for row in rows)
    total = sum(row["total"] for row in rows)
    session.result = {
        "correct": correct,
        "total": total,
        "accuracy": round(100 * correct / total) if total else 0,
        "language": session.language,
        "sentences": rows,
        "feedback": await _teacher_feedback(session, rows, chat),
    }
    return session.result
