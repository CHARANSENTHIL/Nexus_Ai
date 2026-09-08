"""
FastAPI Router for Voice Commands and Audio Interaction.
"""
import os
import tempfile
import logging
from typing import Optional, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, status
from fastapi.responses import FileResponse

from app.voice.transcriber import transcriber
from app.voice.tts import tts_engine
from app.voice.listener import voice_listener
from app.agents.planner import IntentRouter
from app.computer_use.interface import computer

logger = logging.getLogger(__name__)

router = APIRouter()


class SpeakRequest(BaseModel):
    text: str
    export_audio: bool = False


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """
    Upload an audio file (.ogg, .wav, .mp3, .m4a) to transcribe it into text.
    """
    suffix = os.path.splitext(file.filename or "audio.ogg")[1] or ".ogg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        res = await transcriber.transcribe_file(tmp_path)
        return res
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@router.post("/command")
async def voice_command(file: UploadFile = File(...)):
    """
    Upload a voice note command, transcribe it, and execute it autonomously on the PC.
    """
    suffix = os.path.splitext(file.filename or "audio.ogg")[1] or ".ogg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        trans_res = await transcriber.transcribe_file(tmp_path)
        if not trans_res.get("success"):
            return {
                "success": False,
                "error": trans_res.get("error", "Failed to transcribe voice audio"),
                "text": "",
            }

        text = trans_res.get("text", "")
        result = await voice_listener.process_voice_command(text)
        return {
            "success": True,
            "transcribed_text": text,
            "execution_result": result,
        }
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


@router.post("/speak")
async def speak_text(req: SpeakRequest):
    """
    Speak text out loud on PC or return a generated .wav audio file.
    """
    if req.export_audio:
        audio_file = tts_engine.text_to_audio_file(req.text)
        if audio_file and os.path.exists(audio_file):
            return FileResponse(audio_file, media_type="audio/wav", filename="speech.wav")
        raise HTTPException(status_code=500, detail="Failed to synthesize speech audio file")

    await tts_engine.speak_async(req.text)
    return {"success": True, "message": "Spoken through PC speakers"}


@router.post("/mic-listen")
async def trigger_mic_listening():
    """
    Trigger the PC microphone to listen for a single voice command.
    """
    text = await voice_listener.listen_once_from_mic()
    if not text:
        return {"success": False, "message": "No voice detected or timeout"}

    result = await voice_listener.process_voice_command(text)
    return {
        "success": True,
        "transcribed_text": text,
        "execution_result": result,
    }
