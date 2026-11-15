"""Feature 12: speech (public speaking).

Like the essay, but spoken. The teacher sets a speech assignment (or the
learner brings a topic of their own), the learner records the speech, the
ear turns it into a transcript that the learner can check, and the teacher
rates it, gives feedback and corrections, and writes a sample script of an
ideal speech.

The app cannot hear delivery (voice, intonation, pronunciation). What it
can measure is time: how long the speech lasted against the target, and the
speaking pace. Those numbers are computed by the code and given to the
model, so that its comments on length and pace are grounded.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..context import feedback_language
from ..providers.base import ChatProvider, ProviderError
from ..providers.factory import get_chat_provider
from ..textutils import _CHAR_SCRIPTS, parse_json
from .dictation import DIFFICULTIES
from .essay import MAX_SCORE, _plain
from .speech import clean_language_code

router = APIRouter(prefix="/api/speaking", tags=["speaking"])

DEFAULT_SYSTEM_PROMPT = "You are an experienced, encouraging public speaking coach."
MAX_SESSIONS = 50
MAX_TRANSCRIPT_CHARS = 6000
MINUTES = (1, 2, 3)
EXTRA_SECONDS = 60  # the recording may run this far over the target before it is stopped
# A comfortable speaking pace, used to size the sample script.
WORDS_PER_MINUTE = 130
CHARACTERS_PER_MINUTE = 300  # for languages written without spaces
CRITERIA = (
    ("content", "Content and message", "does it do what the task asks; is there a clear message, with reasons or examples"),
    ("structure", "Structure", "an opening that gets attention, main points in a clear order, signposting, a closing that lands"),
    ("language", "Language", "grammar, vocabulary, and a natural spoken style"),
    ("impact", "Impact on the audience", "is it engaging, persuasive and suited to the listeners"),
)
# For the microphone and the voice when the model has not told us the code.
_LANGUAGE_CODES = {
    "english": "en-US", "japanese": "ja-JP", "日本語": "ja-JP", "spanish": "es-ES", "french": "fr-FR",
    "german": "de-DE", "italian": "it-IT", "portuguese": "pt-PT", "brazilian portuguese": "pt-BR",
    "chinese": "zh-CN", "mandarin": "zh-CN", "korean": "ko-KR", "russian": "ru-RU", "arabic": "ar-SA",
    "hindi": "hi-IN", "dutch": "nl-NL", "swedish": "sv-SE", "norwegian": "nb-NO", "danish": "da-DK",
    "finnish": "fi-FI", "polish": "pl-PL", "czech": "cs-CZ", "turkish": "tr-TR", "greek": "el-GR",
    "hebrew": "he-IL", "thai": "th-TH", "vietnamese": "vi-VN", "indonesian": "id-ID",
    "ukrainian": "uk-UA", "hungarian": "hu-HU", "romanian": "ro-RO",
}


def language_code_for(name: str) -> str:
    """The usual code for a language name, or "" if the name is not in the list."""
    key = " ".join(name.lower().split())
    return _LANGUAGE_CODES.get(key) or _LANGUAGE_CODES.get(key.split(" ")[0], "") if key else ""


@dataclass
class Session:
    language: str
    difficulty: str
    minutes: int
    system_prompt: str
    session_prompt: str
    language_code: str
    assignment: str = ""
    # Kept for one transcript, so a new recording is marked afresh and a
    # failed second step can be repeated without redoing the first.
    marked: tuple[str, int] = ("", 0)
    review: dict | None = None
    result: dict | None = None


_sessions: OrderedDict[str, Session] = OrderedDict()


class StartRequest(BaseModel):
    language: str = Field(min_length=1, max_length=60)
    difficulty: Literal[
        "beginner", "elementary", "intermediate", "upper_intermediate", "advanced"
    ] = "intermediate"
    minutes: Literal[1, 2, 3] = 2
    system_prompt: str = Field(default="", max_length=2000)
    session_prompt: str = Field(default="", max_length=2000)
    with_assignment: bool = True  # False: the learner already has a topic


class SubmitRequest(BaseModel):
    transcript: str = Field(max_length=MAX_TRANSCRIPT_CHARS * 3)  # the real limit is checked below
    seconds: int = Field(default=0, ge=0, le=3600)  # how long the recording lasted


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found. Please start a new one.")
    return session


def _level(session: Session) -> str:
    return DIFFICULTIES[session.difficulty].split(":")[0]


def pace(text: str, seconds: int) -> dict:
    """Words (or characters, for languages written without spaces) and the rate per minute."""
    by_character = bool(_CHAR_SCRIPTS.search(text))
    count = sum(1 for char in text if char.isalnum()) if by_character else len(text.split())
    return {
        "unit": "characters" if by_character else "words",
        "count": count,
        "per_minute": round(count * 60 / seconds) if seconds >= 5 else None,
    }


def _clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


async def _write_assignment(session: Session, chat: ChatProvider) -> str:
    parts = [
        f"Set one public speaking assignment for a learner of {session.language}: a speech "
        f"of about {session.minutes} minute{'s' if session.minutes > 1 else ''}. "
        f"Learner level: {DIFFICULTIES[session.difficulty]}."
    ]
    if session.session_prompt:
        parts.append(f"Learner's instructions for this session: {session.session_prompt}")
    parts.append(
        f"Write the assignment in {session.language}, in wording the learner can understand "
        "at this level. Give the topic, the situation and who the audience is, the goal of "
        "the speech (to inform, to persuade, to thank, to introduce), and two or three "
        "points to cover. Plain text only, no markdown, at most 90 words. Reply with the "
        "assignment only."
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
        minutes=req.minutes,
        system_prompt=req.system_prompt.strip(),
        session_prompt=req.session_prompt.strip(),
        language_code=language_code_for(req.language),
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
        "language_code": session.language_code,
        "target_seconds": req.minutes * 60,
        "max_seconds": req.minutes * 60 + EXTRA_SECONDS,
    }


def _task_context(session: Session) -> str:
    if session.assignment:
        return f"The assignment was:\n{session.assignment}"
    if session.session_prompt:
        return (
            "The learner chose the topic themselves, without an assignment from you. "
            f"What they said about it: {session.session_prompt}"
        )
    return "The learner chose the topic themselves, without an assignment from you."


def _timing(session: Session, speed: dict, seconds: int) -> str:
    if speed["per_minute"] is None:
        return f"The speech was meant to last about {session.minutes} minute(s)."
    return (
        f"The speech was meant to last about {_clock(session.minutes * 60)} and lasted "
        f"{_clock(seconds)}, at about {speed['per_minute']} {speed['unit']} per minute "
        "(measured by the app)."
    )


async def _review(session: Session, transcript: str, timing: str, chat: ChatProvider) -> dict:
    criteria = "\n".join(f'- "{key}": {label} ({hint})' for key, label, hint in CRITERIA)
    shape = ", ".join(f'"{key}": {{"score": 3, "comment": "..."}}' for key, _, _ in CRITERIA)
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Review this speech given in {session.language} by a learner at level "
                f"{_level(session)}. {_task_context(session)}\n\n{timing}\n\n"
                "Below is a transcript made by speech recognition. You did not hear the "
                "speech: do not comment on pronunciation, voice or intonation, nor on "
                "punctuation, capital letters or spelling, and keep in mind that an odd "
                "word may be a recognition error.\n\n"
                f"--- transcript ---\n{transcript}\n--- end of transcript ---\n\n"
                f"Rate each criterion from 1 (weak) to {MAX_SCORE} (excellent), judged "
                "against what can be expected at this level, with a one-sentence comment:\n"
                f"{criteria}\n\n"
                'Then write "feedback": what worked, the main weaknesses, a remark on the '
                "length and pace using the numbers above, and two or three concrete tips "
                "for speaking in public, in at most 160 words. Then list in \"corrections\" "
                'the most important language problems, at most eight: "original" is the '
                'learner\'s sentence or phrase, "better" is how to say it, "explanation" '
                "is one short sentence.\n\n"
                "Write comments, feedback and explanations in " + feedback_language() + " unless the system "
                f"prompt asks for another language; quote and correct in {session.language}.\n\n"
                f'Reply with JSON only: {{"language_code": "...", "scores": {{{shape}}}, '
                '"feedback": "...", "corrections": [{"original": "...", "better": "...", '
                f'"explanation": "..."}}]}}. "language_code" is the BCP-47 code of {session.language}, '
                'such as "en-US" or "ja-JP".'
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
        row = {name: " ".join(str(entry.get(name) or "").split()) for name in ("original", "better", "explanation")}
        if row["original"] and row["better"] and row["original"] != row["better"]:
            corrections.append(row)
    rated = [row["score"] for row in scores if row["score"] is not None]
    return {
        "language_code": session.language_code or clean_language_code(data.get("language_code")),
        "scores": scores,
        "total": sum(rated),
        "max_total": MAX_SCORE * len(rated),
        "feedback": _plain(str(data["feedback"])),
        "corrections": corrections[:8],
    }


async def _sample_script(session: Session, transcript: str, chat: ChatProvider) -> str:
    words, characters = session.minutes * WORDS_PER_MINUTE, session.minutes * CHARACTERS_PER_MINUTE
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Below is the transcript of a speech in {session.language} by a learner at "
                f"level {_level(session)}. {_task_context(session)}\n\n"
                f"--- transcript ---\n{transcript}\n--- end of transcript ---\n\n"
                "Write a sample script of an ideal speech on the same topic. Keep the "
                "learner's own ideas where they work. Give it an opening that gets "
                "attention, two or three clear points, and a closing that stays in the "
                "mind. Write it to be spoken: natural spoken sentences, nothing that is "
                "hard to say aloud. Aim one step above the learner's level, so that they "
                f"can learn from it. Length: about {words} words, or about {characters} "
                f"characters if {session.language} is written without spaces between words, "
                f"so that it lasts about {session.minutes} minute(s). Write in "
                f"{session.language} only. Plain text in short paragraphs, no markdown, no "
                "stage directions, no title. Reply with the script only."
            ),
        },
    ]
    script = _plain(await chat.chat(messages, temperature=0.5))
    if not script:
        raise ProviderError("The model returned no sample script. Please press the button again.")
    return script


@router.post("/sessions/{session_id}/submit")
async def submit(
    session_id: str, req: SubmitRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = _get_session(session_id)
    transcript = "\n".join(" ".join(line.split()) for line in req.transcript.strip().splitlines() if line.strip())
    if len(transcript) < 10:
        raise HTTPException(422, "There is too little speech to review. Please record a longer speech.")
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        raise HTTPException(
            422,
            f"The transcript has {len(transcript)} characters. The most this app can review "
            f"at once is {MAX_TRANSCRIPT_CHARS}. Please record a shorter speech.",
        )

    if session.marked != (transcript, req.seconds):  # a new recording, or an edited transcript
        session.marked, session.review, session.result = (transcript, req.seconds), None, None
    if session.result is not None:
        return session.result
    speed = pace(transcript, req.seconds)
    if session.review is None:
        session.review = await _review(session, transcript, _timing(session, speed, req.seconds), chat)
    sample = await _sample_script(session, transcript, chat)  # if this fails, the review above is kept
    session.result = {
        "language": session.language,
        "assignment": session.assignment,
        "transcript": transcript,
        "seconds": req.seconds,
        "target_seconds": session.minutes * 60,
        "pace": speed,
        **session.review,
        "sample": sample,
    }
    return session.result
