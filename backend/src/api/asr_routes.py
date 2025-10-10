"""
ASR (Dictation mode) API routes.
Provides a minimal non-streaming transcription endpoint using Whisper.
"""
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Form
from pydantic import BaseModel

from ..core.config import settings

# Lazy import whisper to avoid import cost when voice is disabled
try:
    import whisper  # type: ignore
except Exception:
    whisper = None  # type: ignore


router = APIRouter(prefix="/api/asr", tags=["asr"])


class TranscribeResponse(BaseModel):
    text: str
    language: Optional[str] = None
    model: str


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
):
    """
    Transcribe an uploaded audio file using Whisper.

    - Accepts webm/opus, wav, mpeg, etc. Whisper uses ffmpeg under the hood.
    - Optional language hint (e.g., "zh", "en"). If not provided, auto-detect.
    """
    if not settings.enable_voice:
        raise HTTPException(status_code=404, detail="ASR disabled")

    if whisper is None:
        raise HTTPException(status_code=500, detail="Whisper not installed. Please install openai-whisper and ffmpeg.")

    if file is None or not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")

    # Persist to a temporary file for whisper to read via ffmpeg
    suffix = os.path.splitext(file.filename)[1] or ".webm"
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        # Load model lazily per request for simplicity (could be cached globally)
        model_name = settings.whisper_model or "base"
        try:
            model = whisper.load_model(model_name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to load whisper model '{model_name}': {e}")

        # Use provided language or settings default
        lang = language or settings.asr_language

        try:
            result = model.transcribe(tmp_path, language=lang, fp16=False)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")

        text = (result or {}).get("text", "").strip()
        detected_lang = (result or {}).get("language")

        if not text:
            raise HTTPException(status_code=400, detail="Empty transcription result")

        return TranscribeResponse(text=text, language=detected_lang or lang, model=model_name)
    finally:
        try:
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass


