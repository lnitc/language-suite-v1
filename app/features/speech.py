"""Shared speech endpoints: the ear (microphone to text) and the mouth."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..providers.base import SpeechToText, TextToSpeech
from ..providers.factory import get_speech_provider, get_transcription_provider

router = APIRouter(prefix="/api/speech", tags=["speech"])

MAX_AUDIO_BYTES = 25 * 1024 * 1024
_LANGUAGE_CODE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8}){0,2}$")


def clean_language_code(code: object) -> str:
    """Keep a BCP-47 code such as "ja-JP" only if it looks like one."""
    code = str(code or "").strip()
    return code if _LANGUAGE_CODE.match(code) else ""


def _recognition_language(code: str) -> str | None:
    """Whisper-style hint: the two-letter part of "ja-JP", or None to detect."""
    primary = clean_language_code(code).split("-")[0].lower()
    return primary if len(primary) == 2 else None


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1500)
    language_code: str = Field(default="", max_length=20)


@router.post("/transcribe")
async def transcribe(
    request: Request,
    language: str = "",
    stt: SpeechToText = Depends(get_transcription_provider),
) -> dict:
    """Body: the raw recording. Returns the recognised text."""
    audio = await request.body()
    if not audio:
        raise HTTPException(400, "The recording was empty. Please try again.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "The recording is too long. Please speak in shorter turns.")
    content_type = request.headers.get("content-type", "audio/webm").split(";")[0].strip()
    text = await stt.transcribe(
        audio, language=_recognition_language(language), content_type=content_type
    )
    return {"text": text.strip()}


@router.post("/synthesize")
async def synthesize(
    req: SynthesizeRequest,
    tts: TextToSpeech | None = Depends(get_speech_provider),
) -> Response:
    if tts is None:
        raise HTTPException(404, "Server speech is off (TTS_PROVIDER is 'browser').")
    audio = await tts.synthesize(
        req.text, language=clean_language_code(req.language_code) or None
    )
    return Response(content=audio, media_type=tts.media_type, headers={"Cache-Control": "no-store"})
