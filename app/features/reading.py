"""Feature 8: reading comprehension.

The teacher writes a text and multiple-choice questions about it (four
options each). The learner chooses, the code marks the answers, and the
teacher explains the correct answers and why wrong choices were wrong.

Three steps, each its own model call, because a small local model handles
short, focused answers best:
  1. the text (shown at once, so the learner can start reading),
  2. the questions, a few at a time,
  3. after marking, explanations for the learner's wrong choices.
"""

from __future__ import annotations

import random
import re
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..providers.base import ChatProvider, ProviderError
from ..providers.factory import get_chat_provider
from ..textutils import normalize, parse_json
from .dictation import DIFFICULTIES

router = APIRouter(prefix="/api/reading", tags=["reading"])

DEFAULT_SYSTEM_PROMPT = (
    "You are an experienced language teacher who writes exam-style reading "
    "comprehension texts and questions."
)
MAX_SESSIONS = 50
MAX_QUESTIONS = 10
QUESTIONS_PER_CALL = 5
# Target length: words, or characters for languages written without spaces.
# "long" is about one A4 page, like a long passage in a proficiency exam.
LENGTHS = {"short": (150, 300), "medium": (300, 600), "long": (500, 1000)}
# How hard the questions are to answer (separate from how hard the text is).
QUESTION_STYLES = {
    "straightforward": (
        "Question style: straightforward. The correct option may use the same words as "
        "the text, so that a learner who finds the right sentence can answer."
    ),
    "tricky": (
        "Question style: tricky, as in the hardest part of a proficiency exam. Finding "
        "matching words must not be enough to answer:\n"
        "- The correct option must NOT repeat the wording of the text. Say the same "
        "thing differently: synonyms, another grammatical structure, a summary, a "
        "more general or more specific statement, or the idea seen from the other side.\n"
        "- The wrong options SHOULD reuse words and phrases straight from the text, but "
        "say something the text does not say: a changed detail, cause and effect "
        "reversed, the wrong person or time, an exaggeration (always, never, only), "
        "or something true in the text that does not answer the question.\n"
        "- Include questions whose answer is implied by the text and has to be worked "
        "out, not read off.\n"
        "- Make the four options similar in length and tone.\n"
        "- Even so, exactly one option must be clearly right for a careful reader, and "
        "the explanation must show which part of the text proves it."
    ),
}
_OPTION_LABEL = re.compile(r"^\s*(?:[A-Da-d1-4][.)：:、]|[(（][A-Da-d1-4][)）])\s*")
_rng = random.Random()


@dataclass
class Question:
    question: str
    options: list[str]
    correct: int  # index into options
    explanation: str


@dataclass
class Session:
    language: str
    difficulty: str
    system_prompt: str
    question_count: int
    question_style: str
    title: str
    text: str
    questions: list[Question] = field(default_factory=list)
    result: dict | None = None


_sessions: OrderedDict[str, Session] = OrderedDict()


class StartRequest(BaseModel):
    language: str = Field(min_length=1, max_length=60)
    difficulty: Literal[
        "beginner", "elementary", "intermediate", "upper_intermediate", "advanced"
    ] = "intermediate"
    length: Literal["short", "medium", "long"] = "long"
    question_count: int = Field(default=5, ge=1, le=MAX_QUESTIONS)
    question_style: Literal["straightforward", "tricky"] = "straightforward"
    system_prompt: str = Field(default="", max_length=2000)
    session_prompt: str = Field(default="", max_length=2000)


class SubmitRequest(BaseModel):
    # One entry per question: the number of the chosen option (0-3), or null if unanswered.
    answers: list[int | None] = Field(max_length=MAX_QUESTIONS)


def _get_session(session_id: str) -> Session:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found. Please start a new one.")
    return session


def _clean(text: object) -> str:
    return " ".join(str(text or "").replace("**", "").split())


@router.post("/sessions")
async def start_session(
    req: StartRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    """Step 1: the text."""
    words, characters = LENGTHS[req.length]
    parts = [
        f"Write a text in {req.language} for a reading comprehension exercise. "
        f"Learner level: {DIFFICULTIES[req.difficulty]}.",
        f"Length: about {words} words. If {req.language} is written without spaces "
        f"between words (like Japanese or Chinese), make it about {characters} characters instead.",
    ]
    if req.session_prompt.strip():
        parts.append(f"Learner's instructions for this session: {req.session_prompt.strip()}")
    parts.append(
        "Write the kind of passage found in the reading part of a language proficiency "
        "exam: an article, essay, story, letter or report. It must contain enough "
        "concrete content (facts, reasons, opinions, a sequence of events, a "
        f"conclusion) for {req.question_count} comprehension questions."
    )
    parts.append(
        "Format: the title on the first line, then an empty line, then the text in "
        "paragraphs separated by empty lines. Plain text, no markdown, no questions, "
        "no comments."
    )
    messages = [
        {"role": "system", "content": req.system_prompt.strip() or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    raw = await chat.chat(messages, temperature=0.9)

    lines = [line.strip().lstrip("#").strip().replace("**", "") for line in raw.strip().strip("`").splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    title, paragraphs = "", []
    if len(lines) > 1 and len(lines[0]) <= 120:
        title = re.sub(r"^(title|タイトル)\s*[:：]\s*", "", lines.pop(0), flags=re.I).strip('"「」')
    for line in lines:
        if line:
            paragraphs.append(line)
    text = "\n\n".join(paragraphs)
    if len(text) < 80:
        raise ProviderError(
            "The model did not return a usable text. Please try again; "
            "if it keeps happening, try a different model."
        )

    session_id = uuid.uuid4().hex
    _sessions[session_id] = Session(
        language=req.language.strip(),
        difficulty=req.difficulty,
        system_prompt=req.system_prompt.strip(),
        question_count=req.question_count,
        question_style=req.question_style,
        title=title,
        text=text,
    )
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)
    return {"session_id": session_id, "title": title, "text": text, "question_count": req.question_count}


def _parse_question(entry: object) -> Question | None:
    """Accepts a question only if it is well-formed: four different options
    and one identifiable correct answer."""
    if not isinstance(entry, dict):
        return None
    question = _clean(entry.get("question"))
    options = entry.get("options")
    if not question or not isinstance(options, list) or len(options) != 4:
        return None
    options = [_OPTION_LABEL.sub("", _clean(option)) for option in options]
    if any(not option for option in options) or len({normalize(o) for o in options}) != 4:
        return None

    answer = entry.get("answer")
    correct = None
    if isinstance(answer, bool):
        return None
    if isinstance(answer, (int, float)) and 1 <= int(answer) <= 4:
        correct = int(answer) - 1
    elif isinstance(answer, str):
        text = answer.strip()
        if text.isdigit() and 1 <= int(text) <= 4:
            correct = int(text) - 1
        elif len(text) == 1 and text.upper() in "ABCD":
            correct = "ABCD".index(text.upper())
        else:  # the model repeated the option's text
            matches = [i for i, option in enumerate(options) if normalize(option) == normalize(_OPTION_LABEL.sub("", text))]
            correct = matches[0] if len(matches) == 1 else None
    if correct is None:
        return None

    # Models tend to put the right answer first: shuffle the options.
    order = list(range(4))
    _rng.shuffle(order)
    return Question(
        question=question,
        options=[options[i] for i in order],
        correct=order.index(correct),
        explanation=_clean(entry.get("explanation")),
    )


async def _write_questions(session: Session, count: int, chat: ChatProvider) -> list[Question]:
    parts = [
        f"Below is a reading text in {session.language} for a learner at level "
        f"{DIFFICULTIES[session.difficulty].split(':')[0]}. Write {count} multiple-choice "
        f"comprehension questions about it, in {session.language}, in wording that suits the level.",
        "Rules:\n"
        "- Each question can be answered from the text alone.\n"
        "- Exactly four options. Exactly one is clearly correct according to the text; "
        "the other three are plausible but wrong.\n"
        '- No options like "all of the above" or "none of the above".\n'
        "- Vary the kind of question: main idea, a detail, a reason, what a word or "
        "phrase means in the text, what can be concluded.\n"
        "- Spread the questions over the whole text.",
        QUESTION_STYLES[session.question_style],
    ]
    if session.questions:
        parts.append(
            "These questions already exist. Ask about other things:\n"
            + "\n".join(f"- {q.question}" for q in session.questions)
        )
    parts.append(
        '"explanation" says why the correct option is right, pointing to the part of '
        "the text that shows it, in one or two sentences. Write explanations in English "
        "unless the system prompt asks for another language."
    )
    parts.append(
        'Reply with JSON only: {"questions": [{"question": "...", "options": ["...", "...", '
        '"...", "..."], "answer": 1, "explanation": "..."}]}. "answer" is the number '
        "(1 to 4) of the correct option."
    )
    parts.append(f"--- text ---\n{session.title}\n\n{session.text}\n--- end of text ---")
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    raw = await chat.chat(messages, json_mode=True, temperature=0.4)
    try:
        entries = parse_json(raw).get("questions", [])
    except ValueError:
        entries = []
    asked = {normalize(q.question) for q in session.questions}
    questions = []
    for entry in entries if isinstance(entries, list) else []:
        question = _parse_question(entry)
        if question and normalize(question.question) not in asked and len(questions) < count:
            asked.add(normalize(question.question))
            questions.append(question)
    return questions


def _public_questions(session: Session) -> list[dict]:
    """The questions as the learner sees them: without the answers."""
    return [
        {"number": i, "question": q.question, "options": q.options}
        for i, q in enumerate(session.questions, start=1)
    ]


@router.post("/sessions/{session_id}/questions")
async def make_questions(
    session_id: str, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    """Step 2: the questions. A few per model call, with up to two extra
    rounds if some were unusable. Calling again continues where it stopped."""
    session = _get_session(session_id)
    rounds = -(-session.question_count // QUESTIONS_PER_CALL) + 2
    for _ in range(rounds):
        missing = session.question_count - len(session.questions)
        if missing <= 0:
            break
        session.questions += await _write_questions(session, min(missing, QUESTIONS_PER_CALL), chat)
    if not session.questions:
        raise ProviderError(
            "The model did not return usable questions for this text. "
            "Press the button to try again."
        )
    return {
        "questions": _public_questions(session),
        "requested": session.question_count,
    }


async def _explain_mistakes(session: Session, rows: list[dict], chat: ChatProvider) -> dict[int, str]:
    """Step 3: why each wrong choice was wrong. Optional: the result stands without it."""
    wrong = [row for row in rows if row["chosen"] is not None and not row["is_correct"]]
    if not wrong:
        return {}
    blocks = [
        f"Question {row['number']}: {row['question']}\n"
        f"The learner chose: {row['options'][row['chosen']]}\n"
        f"The correct answer: {row['options'][row['correct']]}"
        for row in wrong
    ]
    messages = [
        {"role": "system", "content": session.system_prompt or DEFAULT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"A learner of {session.language} answered reading comprehension questions "
                "about the text below and got some wrong. For each one, explain in one or "
                "two sentences why the option they chose is wrong according to the text "
                "(what the text really says, or what they probably misread). Be kind and "
                "specific. Write in English unless the system prompt asks for another language.\n\n"
                + "\n\n".join(blocks)
                + '\n\nReply with JSON only: {"explanations": [{"number": 1, "why_wrong": "..."}]}, '
                "using the question numbers above.\n\n"
                f"--- text ---\n{session.title}\n\n{session.text}\n--- end of text ---"
            ),
        },
    ]
    try:
        entries = parse_json(await chat.chat(messages, json_mode=True, temperature=0.2)).get("explanations", [])
    except (ProviderError, ValueError):
        return {}
    found: dict[int, str] = {}
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, dict):
            try:
                found[int(entry.get("number"))] = _clean(entry.get("why_wrong"))
            except (TypeError, ValueError):
                continue
    return found


@router.post("/sessions/{session_id}/submit")
async def submit(
    session_id: str, req: SubmitRequest, chat: ChatProvider = Depends(get_chat_provider)
) -> dict:
    session = _get_session(session_id)
    if not session.questions:
        raise HTTPException(409, "The questions are not ready yet.")
    if session.result is not None:
        return session.result

    answers = (req.answers + [None] * len(session.questions))[: len(session.questions)]
    rows = []
    for number, (question, chosen) in enumerate(zip(session.questions, answers), start=1):
        chosen = chosen if chosen is not None and 0 <= chosen < 4 else None
        rows.append(
            {
                "number": number,
                "question": question.question,
                "options": question.options,
                "correct": question.correct,
                "chosen": chosen,
                "is_correct": chosen == question.correct,
                "explanation": question.explanation,
                "why_wrong": "",
            }
        )
    for number, why in (await _explain_mistakes(session, rows, chat)).items():
        if 1 <= number <= len(rows) and not rows[number - 1]["is_correct"]:
            rows[number - 1]["why_wrong"] = why

    session.result = {
        "language": session.language,
        "question_style": session.question_style,
        "title": session.title,
        "text": session.text,
        "score": sum(row["is_correct"] for row in rows),
        "total": len(rows),
        "questions": rows,
    }
    return session.result
