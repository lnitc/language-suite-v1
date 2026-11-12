"""Ear: local speech recognition with Whisper, via the faster-whisper package.

Optional. Install with ``pip install -r requirements-voice.txt``. The model
is downloaded on first use and then kept on disk by faster-whisper.
"""

from __future__ import annotations

import asyncio
import io
import threading

from .base import ProviderError

_models: dict = {}
_lock = threading.Lock()

SAMPLE_RATE = 16000  # what Whisper expects
MIN_SAMPLES = SAMPLE_RATE // 5  # 0.2 seconds


def decode_recording(audio: bytes):
    """Browser recording (webm, ogg, wav, ...) -> mono 16 kHz samples for Whisper.

    Done here with PyAV directly, rather than by faster-whisper's own
    decoder, which breaks with some PyAV versions.
    """
    import av
    import numpy as np

    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    chunks = []
    with av.open(io.BytesIO(audio), mode="r") as container:
        for frame in container.decode(audio=0):
            chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(frame))
        chunks.extend(out.to_ndarray().reshape(-1) for out in resampler.resample(None))
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32) / 32768.0


class FasterWhisperTranscription:
    def __init__(self, *, model: str = "small", device: str = "cpu") -> None:
        self._model = model
        self._device = device

    def _load(self):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ProviderError(
                "Local speech recognition is not installed. In your project "
                "folder run: pip install -r requirements-voice.txt (or set "
                "STT_PROVIDER=openai_compatible to use a speech server)."
            ) from exc
        key = (self._model, self._device)
        with _lock:  # load once, even if two requests arrive together
            if key not in _models:
                try:
                    _models[key] = WhisperModel(
                        self._model,
                        device=self._device,
                        compute_type="int8" if self._device == "cpu" else "float16",
                    )
                except Exception as exc:
                    raise ProviderError(
                        f"Could not load the Whisper model '{self._model}' on "
                        f"'{self._device}'. The first use downloads it, which "
                        "needs an internet connection. Check STT_MODEL and "
                        "STT_DEVICE in your .env file."
                    ) from exc
            return _models[key]

    def _run(self, audio: bytes, language: str | None) -> str:
        model = self._load()
        try:
            samples = decode_recording(audio)
        except Exception as exc:
            raise ProviderError(
                "The recording could not be read. Please record again; if it "
                "keeps happening, try Chrome or Edge."
            ) from exc
        if samples.shape[0] < MIN_SAMPLES:
            return ""  # too short to contain a word
        try:
            segments, _ = model.transcribe(samples, language=language, vad_filter=True)
            return " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as exc:
            raise ProviderError(
                "Speech recognition failed on this recording. The cause is "
                "shown in the window where the app is running."
            ) from exc

    async def transcribe(
        self,
        audio: bytes,
        *,
        language: str | None = None,
        content_type: str = "audio/webm",
    ) -> str:
        # Whisper is CPU-heavy: run it off the event loop so the app stays responsive.
        return await asyncio.to_thread(self._run, audio, language)
