"""Settings, read from environment variables (or a local ".env" file).

Nothing secret is ever hard-coded here: keys come only from the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    llm_base_url: str
    llm_model: str
    llm_api_key: str
    llm_timeout: float
    tts_provider: str
    tts_base_url: str
    tts_model: str
    tts_voice: str
    tts_api_key: str
    tts_timeout: float


def get_settings() -> Settings:
    return Settings(
        llm_provider=os.getenv("LLM_PROVIDER", "openai_compatible"),
        llm_base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/"),
        llm_model=os.getenv("LLM_MODEL", "gemma4:e4b"),
        llm_api_key=os.getenv("LLM_API_KEY", ""),
        llm_timeout=float(os.getenv("LLM_TIMEOUT", "120")),
        tts_provider=os.getenv("TTS_PROVIDER", "browser"),
        tts_base_url=os.getenv("TTS_BASE_URL", "").rstrip("/"),
        tts_model=os.getenv("TTS_MODEL", ""),
        tts_voice=os.getenv("TTS_VOICE", ""),
        tts_api_key=os.getenv("TTS_API_KEY", ""),
        tts_timeout=float(os.getenv("TTS_TIMEOUT", "60")),
    )
