"""Pretend model, voice and speech-recognition server for the browser tests.

It answers the same web addresses as an OpenAI-compatible service (which is
also what Ollama offers), so the app can be pointed at it with LLM_BASE_URL,
TTS_BASE_URL and STT_BASE_URL. The answers are fixed, which makes the tests
repeatable and lets them run without Ollama, a GPU, a microphone or the
internet.

Each rule below is a phrase from one of the app's prompts and the answer to
give when a prompt contains it. The first matching rule wins, so the order
matters. If a prompt in the app is reworded, the matching phrase here must
be updated too (the test for that feature will fail and point to it).
"""

from __future__ import annotations

import asyncio
import io
import json
import math
import re
import struct
import wave

from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

app = FastAPI(title="Pretend services for the browser tests")
counters: dict[str, int] = {}


def _next(name: str) -> int:
    counters[name] = counters.get(name, 0) + 1
    return counters[name]


def _number(pattern: str, text: str, default: int = 1) -> int:
    found = re.search(pattern, text)
    return int(found.group(1)) if found else default


# ---------- answers that depend on the prompt ----------

def grammar_items(text: str) -> str:
    count = _number(r"Write (\d+) grammar", text)
    start = text.count("\n- ")  # sentences that already exist
    items = []
    for i in range(start + 1, start + count + 1):
        if i % 2:
            items.append({"type": "gap", "sentence": f"I ____ to school {i} days ago.", "answers": ["went"],
                          "hint": "(go)", "explanation": "'Ago' needs the past simple; go is irregular: went."})
        else:
            items.append({"type": "fix", "sentence": f"She don't like coffee number {i}.",
                          "answers": [f"She doesn't like coffee number {i}.", f"She does not like coffee number {i}."],
                          "explanation": "With he, she and it the negative is doesn't."})
    return json.dumps({"items": items})


def grammar_verdicts(text: str) -> str:
    return json.dumps({"verdicts": [
        {"number": int(number), "correct": False, "comment": "This form does not exist; check the irregular verb."}
        for number in re.findall(r"Item (\d+) \(", text)
    ]})


def reading_questions(text: str) -> str:
    count = _number(r"Write (\d+) multiple-choice", text)
    start = text.count("\n- Question")
    return json.dumps({"questions": [
        {"question": f"Question {start + i}: When was the bridge built?",
         "options": ["A hundred years ago", "Ten years ago", "Last year", "Fifty years ago"],
         "answer": 1, "explanation": "The first sentence says it was built a hundred years ago."}
        for i in range(1, count + 1)
    ]})


def reading_explanations(text: str) -> str:
    return json.dumps({"explanations": [
        {"number": int(number), "why_wrong": "The text gives a different time: reread the first sentence."}
        for number in re.findall(r"Question (\d+):", text)
    ]})


def wordlist_words(text: str) -> str:
    return json.dumps({"words": [f"word{i}" for i in range(1, _number(r"List (\d+) words", text) + 1)]})


def wordlist_entries(text: str) -> str:
    lines = re.findall(r"^(\d+)\. (.+)$", text.split("Lines:\n")[1], flags=re.M)
    return json.dumps({"entries": [
        {"n": int(number), "word": line.split()[0], "pronunciation": "wɜːd", "translation": "meaning",
         "example": "This is a word.", "example_translation": "Translated example.", "remarks": ""}
        for number, line in lines
    ]})


def shadowing_sentences(text: str) -> str:
    sentences = ["I am fine, thank you.", "She sells sea shells by the sea shore.", "The weather is rather warm today."]
    return json.dumps({"language_code": "en-US", "sentences": sentences[: _number(r"(?:Write|take) (\d+)", text, 3)]})


READING_TEXT = "# The old bridge\n\n" + "\n\n".join(
    ["This town has an old bridge that was built a hundred years ago. Many people cross it every day."] * 3
)
ESSAY_REVIEW = {
    "scores": {"content": {"score": 4, "comment": "You answer all three points."},
               "organization": {"score": 3, "comment": "Add paragraphs."},
               "vocabulary": {"score": 3, "comment": "Simple but correct."},
               "grammar": {"score": 2, "comment": "Past tense needs work."}},
    "feedback": "Good ideas and a clear memory.\n\nWork on irregular past forms.",
    "corrections": [
        {"original": "I goed to the mountain", "corrected": "I went to the mountains", "explanation": "'go' is irregular: went."},
        {"original": "My favorit season is autum", "corrected": "My favourite season is autumn", "explanation": "Spelling."},
    ],
}
TRANSLATION_REVIEW = {
    "scores": {"accuracy": {"score": 4, "comment": "The meaning is right."},
               "completeness": {"score": 3, "comment": "The last sentence is missing."},
               "naturalness": {"score": 3, "comment": "A little stiff."},
               "language": {"score": 2, "comment": "Past tense of adjectives."}},
    "feedback": "Good start.\n\nTip: i-adjectives change in the past tense.",
    "corrections": [{"source": "It was a lot of fun", "yours": "楽しいでした", "better": "とても楽しかったです",
                     "explanation": "Past of 楽しい is 楽しかった."}],
}
SPEECH_REVIEW = {
    "language_code": "en-US",
    "scores": {"content": {"score": 4, "comment": "A clear message."},
               "structure": {"score": 2, "comment": "It stops without a closing."},
               "language": {"score": 3, "comment": "Mostly correct."},
               "impact": {"score": 3, "comment": "Friendly but brief."}},
    "feedback": "A friendly start.\n\nAdd one example and a closing sentence.",
    "corrections": [{"original": "I am fine thank you", "better": "I'm doing well, thank you",
                     "explanation": "More natural in a speech."}],
}
IDEAL_TRANSLATION = "先週末、動物園に行きました。午後は雨でしたが、とても楽しかったです。"

# (phrase in the prompt, answer). A callable answer is given the prompt.
RULES: list[tuple[str, object]] = [
    # Grammar drills
    ("grammar exercise items", grammar_items),
    ("did grammar exercises", grammar_verdicts),
    # Speech (public speaking)
    ("public speaking assignment", lambda _: f"Assignment {_next('speech')}: Introduce your home town to a group of visitors."),
    ("Review this speech", json.dumps(SPEECH_REVIEW)),
    ("sample script of an ideal speech", "Good morning, everyone. Let me take you to my home town.\n\nThank you."),
    # Listening comprehension and shadowing
    ("listening comprehension exercise",
     "en-US\nStation announcement\n\nGood morning. Because of heavy rain, the train is ten minutes late.\n\n"
     "Passengers in a hurry can take the bus."),
    ("listen-and-repeat", shadowing_sentences),
    ("could not make out", "The sh and s sounds are close together here.\nSay the sentence slowly first."),
    # Written translation
    ("for a translation exercise",
     lambda _: f"Text {_next('translation')}. I went to the zoo last weekend. It was a lot of fun, although it rained."),
    ("Review this translation", json.dumps(TRANSLATION_REVIEW, ensure_ascii=False)),
    ("Write the ideal translation", IDEAL_TRANSLATION),
    ("Your whole answer must be in", IDEAL_TRANSLATION),
    # Reading comprehension
    ("reading comprehension exercise", READING_TEXT),
    ("multiple-choice comprehension questions", reading_questions),
    ("got some wrong", reading_explanations),
    # Essay
    ("essay-writing assignment", lambda _: f"Assignment {_next('essay')}: Write about your favourite season."),
    ("Review this essay", json.dumps(ESSAY_REVIEW)),
    ("ideal version of this essay", "My favourite season is autumn.\n\nLast year I went to the mountains."),
    # Word list creator
    ("Prepare vocabulary list entries", wordlist_entries),
    ("learner's vocabulary list", wordlist_words),
    # Conversation and job interview
    ("For this first turn only", json.dumps({"language_code": "en-US", "say": "Hello! How are you today?"})),
    ("Write feedback", "What went well\nYou answered clearly.\n\nTip\nUse longer sentences."),
    # Interpreter
    ("consecutive interpreting practice", json.dumps({
        "source_language_code": "en-US", "target_language_code": "ja-JP",
        "sentences": ["Welcome to our factory.", "We make car parts here.", "Please wear a helmet.", "The tour takes one hour."]})),
    ("practised consecutive interpreting", json.dumps({
        "batches": [{"ideal": "工場へようこそ。ここでは自動車部品を作っています。", "comment": "Meaning is right."},
                    {"ideal": "ヘルメットを着用してください。見学は一時間です。", "comment": "You left out the helmet."}],
        "overall": "Good start. Watch omissions."}, ensure_ascii=False)),
    # Dictation
    ("dictation exercise", json.dumps({
        "language_code": "en-US",
        "sentences": ["The cat sat on the mat.", "It was a sunny day!", "We walked to the old bridge."]})),
    # Vocabulary practice
    ("Create a vocabulary exercise", json.dumps({
        "source_language_code": "en-US", "target_language_code": "es-ES",
        "items": [{"word": "dog", "translations": ["perro"]}, {"word": "car", "translations": ["coche", "carro"]},
                  {"word": "house", "translations": ["casa"]}]})),
    ("verdicts", json.dumps({"verdicts": []})),  # second opinions: nothing is accepted
    ("last answer", "Thank you for coming. Goodbye."),
]


def answer_for(prompt: str) -> str:
    for phrase, answer in RULES:
        if phrase in prompt:
            return answer(prompt) if callable(answer) else str(answer)
    # Anything else is a turn in a conversation.
    return f"Interesting, that is good to hear. Tell me more, number {_next('turn')}. What else did you do?"


# ---------- the three services ----------

@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    last = body["messages"][-1]["content"]
    prompt = last if isinstance(last, str) else last[0]["text"]  # a list when photos are attached
    answer = answer_for(prompt)
    if not body.get("stream"):
        return {"choices": [{"message": {"content": answer}}]}

    async def pieces():
        words = answer.split(" ")
        for i, word in enumerate(words):
            await asyncio.sleep(0.02)
            content = word + ("" if i == len(words) - 1 else " ")
            yield "data: " + json.dumps({"choices": [{"delta": {"content": content}}]}) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(pieces(), media_type="text/event-stream")


@app.post("/v1/audio/speech")
async def speech() -> Response:
    """The mouth: a quarter of a second of a quiet tone, whatever the text."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as sound:
        sound.setnchannels(1)
        sound.setsampwidth(2)
        sound.setframerate(8000)
        sound.writeframes(b"".join(struct.pack("<h", int(4000 * math.sin(i / 5))) for i in range(2000)))
    return Response(buffer.getvalue(), media_type="audio/wav")


@app.post("/v1/audio/transcriptions")
async def transcriptions() -> dict:
    """The ear: every recording is "heard" as the same sentence."""
    return {"text": "I am fine thank you."}
