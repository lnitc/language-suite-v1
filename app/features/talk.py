"""Features 1 and 2: conversation partner and job interview rehearsal.

Both are the same engine: a spoken, turn-by-turn chat with a role (teacher
or interviewer), followed by written feedback. The browser records the
learner, the ear turns it into text, and this module produces each reply.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..providers.base import ChatProvider, ProviderError
from ..providers.factory import get_chat_provider
from ..context import current_warnings, feedback_language
from ..textutils import parse_json
from .dictation import DIFFICULTIES
from .speech import clean_language_code

router = APIRouter(prefix="/api/talk", tags=["talk"])
logger = logging.getLogger("uvicorn.error")

MAX_SESSIONS = 50
MAX_MATERIAL_CHARS = 8000
MAX_LEARNER_TURNS = 60
INTERVIEW_STYLES = {
    "kind": "a kind interviewer: warm and encouraging, common and straightforward questions",
    "medium": "a balanced interviewer: professional and neutral, a mix of common and probing questions",
    "strict": "a strict interviewer: demanding and sceptical, difficult questions, presses on weak answers",
}
ROLES = {
    "conversation": {
        "default_system": "You are a friendly, patient language teacher.",
        "partner": "Teacher",
        "learner": "Learner",
    },
    "interview": {
        "default_system": "You are an experienced job interviewer.",
        "partner": "Interviewer",
        "learner": "Candidate",
    },
}
SPOKEN_RULES = (
    "Everything you write is read aloud by a speech engine, so write plain "
    "spoken sentences only: no markdown, no lists, no emoji, nothing in "
    "brackets, no stage directions. The other person's words reach you "
    "through speech recognition, so ignore odd punctuation and obvious "
    "recognition slips."
)


@dataclass
class Session:
    kind: str
    language: str
    system_prompt: str
    question_count: int
    history: list[dict]
    language_code: str = ""
    learner_turns: int = 0
    done: bool = False
    transcript: list[dict] = field(default_factory=list)
    feedback: str | None = None


_sessions: OrderedDict[str, Session] = OrderedDict()


class StartRequest(BaseModel):
    kind: Literal["conversation", "interview"]
    language: str = Field(min_length=1, max_length=60)
    difficulty: str = Field(max_length=30)
    system_prompt: str = Field(default="", max_length=2000)
    session_prompt: str = Field(default="", max_length=2000)
    material: str = Field(default="", max_length=200_000)
    image: str = Field(default="", max_length=8_000_000)  # data URL
    question_count: int = Field(default=5, ge=1, le=20)


class TurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found. Please start a new one.")
    return session


def clean_spoken(text: str) -> str:
    """Remove markdown leftovers so the speech engine does not read symbols."""
    text = re.sub(r"[*_#`>]+", "", text)
    return " ".join(text.split())[:1500]


def _system_prompt(req: StartRequest) -> str:
    role = ROLES[req.kind]
    parts = [req.system_prompt.strip() or role["default_system"]]
    if req.kind == "conversation":
        parts.append(
            f"You are having a spoken practice conversation with a learner of {req.language}. "
            f"Speak only {req.language}. Learner level: {DIFFICULTIES[req.difficulty]}; "
            "fit your vocabulary and sentence length to it. Keep each reply to one to "
            "three short sentences and end with a question or prompt that keeps the "
            "learner talking. Do not correct mistakes during the conversation unless "
            "the learner asks; written feedback comes at the end."
        )
    else:
        parts.append(
            f"You are conducting a spoken mock job interview in {req.language}. "
            f"Speak only {req.language}. You are {INTERVIEW_STYLES[req.difficulty]}. "
            f"The interview has exactly {req.question_count} questions. Ask one question "
            "at a time and keep each turn short. Do not give feedback or advice during "
            "the interview; written feedback comes at the end."
        )
    parts.append(SPOKEN_RULES)
    if req.session_prompt.strip():
        parts.append(f"Instructions for this session: {req.session_prompt.strip()}")
    material = req.material.strip()[:MAX_MATERIAL_CHARS]
    if material:
        parts.append(f"Material provided for this session:\n--- material ---\n{material}\n--- end material ---")
    return "\n\n".join(parts)


def _opening_instruction(req: StartRequest) -> str:
    if req.kind == "conversation":
        return "(The session starts now. Greet the learner briefly and open the conversation.)"
    return (
        "(The interview starts now. Greet the candidate in one sentence and ask "
        f"question 1 of {req.question_count}.)"
    )


@router.post("/sessions")
async def start_session(
    req: StartRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    allowed = DIFFICULTIES if req.kind == "conversation" else INTERVIEW_STYLES
    if req.difficulty not in allowed:
        raise HTTPException(422, f"Unknown difficulty '{req.difficulty}'.")
    if req.image and not req.image.startswith("data:image/"):
        raise HTTPException(422, "The uploaded image could not be read.")

    opening = _opening_instruction(req)
    first_content: str | list = opening
    if req.image:
        first_content = [
            {"type": "text", "text": opening + " The attached image is part of the session material."},
            {"type": "image_url", "image_url": {"url": req.image}},
        ]
    history = [
        {"role": "system", "content": _system_prompt(req)},
        {"role": "user", "content": first_content},
    ]

    # Only this first call asks for JSON (to learn the language code for the
    # voices). The instruction is not kept in the history.
    json_note = {
        "role": "user",
        "content": (
            'For this first turn only, reply with JSON: {"language_code": "...", "say": "..."}. '
            f'"language_code" is the BCP-47 code for {req.language}, such as "en-US" or '
            '"ja-JP". "say" is your spoken opening line.'
        ),
    }
    raw = await chat.chat(history + [json_note], json_mode=True, temperature=0.7)
    try:
        data = parse_json(raw)
        say, code = clean_spoken(str(data.get("say", ""))), clean_language_code(data.get("language_code"))
    except ValueError:
        say, code = clean_spoken(raw), ""
    if not say or say.startswith("{"):
        raise ProviderError(
            "The model did not return a usable opening line. Please try again; "
            "if it keeps happening, try a different model."
        )

    history.append({"role": "assistant", "content": say})
    session = Session(
        kind=req.kind,
        language=req.language.strip(),
        system_prompt=req.system_prompt.strip(),
        question_count=req.question_count,
        history=history,
        language_code=code,
        transcript=[{"speaker": ROLES[req.kind]["partner"], "text": say}],
    )
    session_id = uuid.uuid4().hex
    _sessions[session_id] = session
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return {
        "session_id": session_id,
        "reply": say,
        "language_code": code,
        "done": False,
        "question_count": req.question_count if req.kind == "interview" else None,
    }


def _prepare_turn(session: Session, text: str) -> tuple[list[dict], bool, int]:
    """The messages for the model, whether this turn ends the session, and its number."""
    turn = session.learner_turns + 1
    # A stage direction for this call only; the history keeps the clean text.
    note, finishing = "", False
    if session.kind == "interview":
        if turn >= session.question_count:
            finishing = True
            note = (
                "[To the interviewer: that was the last answer. Thank the candidate "
                "in one or two sentences and say goodbye. Ask nothing more.]"
            )
        else:
            note = (
                f"[To the interviewer: now ask question {turn + 1} of "
                f"{session.question_count}. You may react briefly to the answer first.]"
            )
    elif turn >= MAX_LEARNER_TURNS:
        finishing = True
        note = "[To the teacher: time is up. Say a short, friendly goodbye.]"
    call = session.history + [{"role": "user", "content": f"{text}\n\n{note}" if note else text}]
    return call, finishing, turn


def _commit_turn(session: Session, text: str, reply: str, turn: int, finishing: bool) -> None:
    """Saved only after success, so a failed turn can simply be repeated."""
    roles = ROLES[session.kind]
    session.history += [
        {"role": "user", "content": text},
        {"role": "assistant", "content": reply},
    ]
    session.transcript += [
        {"speaker": roles["learner"], "text": text},
        {"speaker": roles["partner"], "text": reply},
    ]
    session.learner_turns = turn
    session.done = finishing


@router.post("/sessions/{session_id}/turns")
async def take_turn(
    session_id: str, req: TurnRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = _get_session(session_id)
    if session.done:
        raise HTTPException(409, "This session is finished. Ask for the feedback.")
    text = " ".join(req.text.split())
    call, finishing, turn = _prepare_turn(session, text)
    reply = clean_spoken(await chat.chat(call, temperature=0.7))
    if not reply:
        raise ProviderError("The model gave an empty reply. Please try that turn again.")
    _commit_turn(session, text, reply, turn, finishing)
    return {"reply": reply, "done": session.done, "turn": turn}


# Where a spoken sentence ends: after . ! ? … followed by a space, or right
# after the full-width 。！？ of Japanese and Chinese (unless a closing quote follows).
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|(?<=[。！？])(?![」』）。！？])")


def split_sentences(buffer: str) -> tuple[list[str], str]:
    """Complete sentences in the buffer, and the unfinished rest."""
    pieces = _SENTENCE_END.split(buffer)
    return [piece for piece in pieces[:-1] if piece.strip()], pieces[-1]


async def _reply_pieces(chat: ChatProvider, call: list[dict]):
    """The reply as it is written, if the provider can stream; otherwise all at once."""
    if hasattr(chat, "chat_stream"):
        async for piece in chat.chat_stream(call, temperature=0.7):
            yield piece
    else:
        yield await chat.chat(call, temperature=0.7)


@router.post("/sessions/{session_id}/turns/stream")
async def take_turn_stream(
    session_id: str, req: TurnRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> StreamingResponse:
    """Like take_turn, but sends each sentence as soon as the model has
    written it, so the voice can start before the whole reply is ready.

    The response is one JSON object per line: {"sentence": "..."} for each
    sentence, then {"done": ..., "turn": ..., "reply": "..."} at the end, or
    {"error": "..."} if the turn failed (it is then not saved).
    """
    session = _get_session(session_id)
    if session.done:
        raise HTTPException(409, "This session is finished. Ask for the feedback.")
    text = " ".join(req.text.split())
    call, finishing, turn = _prepare_turn(session, text)

    def line(data: dict) -> str:
        return json.dumps(data, ensure_ascii=False) + "\n"

    async def lines():
        whole, buffer = "", ""
        try:
            async for piece in _reply_pieces(chat, call):
                whole += piece
                buffer += piece
                sentences, buffer = split_sentences(buffer)
                for sentence in sentences:
                    if spoken := clean_spoken(sentence):
                        yield line({"sentence": spoken})
            if spoken := clean_spoken(buffer):
                yield line({"sentence": spoken})
            reply = clean_spoken(whole)
            if not reply:
                raise ProviderError("The model gave an empty reply. Please try that turn again.")
            _commit_turn(session, text, reply, turn, finishing)
            yield line({"done": session.done, "turn": turn, "reply": reply, "warning": next(iter(current_warnings()), "")})
        except ProviderError as error:
            logger.error("%s", error, exc_info=error.__cause__ or error)
            yield line({"error": str(error)})

    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})


def _feedback_request(session: Session) -> str:
    if session.kind == "conversation":
        return (
            f"Below is a practice conversation in {session.language} between a teacher "
            "and a learner. Write feedback for the learner with these parts: what went "
            "well; the most important language mistakes, each as the learner's sentence "
            "followed by a better version and a one-line reason; a few useful words or "
            "phrases for this topic; one tip for next time."
        )
    return (
        f"Below is a mock job interview in {session.language}. Write feedback for the "
        "candidate with these parts: overall impression; for each answer that was weak "
        "or problematic, what the problem was and how to answer that question better, "
        "with a short example answer; language mistakes worth fixing, with corrections; "
        "the three most important tips for the real interview."
    )


@router.post("/sessions/{session_id}/finish")
async def finish(
    session_id: str, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = _get_session(session_id)
    session.done = True
    if session.feedback is None:
        if session.learner_turns == 0:
            session.feedback = "Nothing was said in this session, so there is nothing to review yet."
        else:
            lines = "\n".join(f"{row['speaker']}: {row['text']}" for row in session.transcript)
            messages = [
                {
                    "role": "system",
                    "content": session.system_prompt or ROLES[session.kind]["default_system"],
                },
                {
                    "role": "user",
                    "content": (
                        _feedback_request(session)
                        + " The learner's lines come from speech recognition: do not "
                        "comment on pronunciation, punctuation or capital letters, and "
                        "keep in mind that an odd word may be a recognition error. "
                        "Plain text with short headings and line breaks, no markdown "
                        "symbols, at most 300 words. Write in " + feedback_language() + " unless the system "
                        "prompt asks for another language.\n\n--- transcript ---\n"
                        + lines
                    ),
                },
            ]
            feedback = (await chat.chat(messages, temperature=0.4)).strip()
            if not feedback:
                raise ProviderError("The model returned no feedback. Please try again.")
            session.feedback = feedback
    return {"feedback": session.feedback, "transcript": session.transcript}
