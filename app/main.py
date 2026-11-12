"""Language Suite: application entry point.

Run with:  python -m uvicorn app.main:app --port 8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .features import vocabulary
from .providers.base import ProviderError

app = FastAPI(title="Language Suite")


@app.exception_handler(ProviderError)
async def provider_error_handler(_: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/api/health")
async def health() -> dict:
    """Shows which model is configured. Never returns the API key."""
    settings = get_settings()
    return {
        "status": "ok",
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "llm_key_set": bool(settings.llm_api_key),
    }


app.include_router(vocabulary.router)

# The browser UI. Mounted last so it does not shadow the API routes.
app.mount(
    "/",
    StaticFiles(directory=Path(__file__).parent / "static", html=True),
    name="static",
)
