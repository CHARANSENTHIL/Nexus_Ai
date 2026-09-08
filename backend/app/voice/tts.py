"""
Text-to-Speech (TTS) Voice Engine for Nexus AI.
Uses native Windows SAPI5 / pyttsx3 for zero-latency local voice output,
and exports audio files (.wav, .mp3) for Telegram voice responses.
"""
import os
import sys
import logging
import asyncio
import tempfile
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class TextToSpeech:
    """Zero-latency local TTS engine with audio export capabilities."""

    def __init__(self):
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            try:
                import pyttsx3
                self._engine = pyttsx3.init()
                # Set reasonable speaking speed (175 wpm) and full volume
                self._engine.setProperty("rate", 180)
                self._engine.setProperty("volume", 1.0)

                # Select a natural voice if available (e.g. David / Zira on Windows)
                voices = self._engine.getProperty("voices")
                if voices:
                    for v in voices:
                        if "zira" in v.name.lower() or "david" in v.name.lower():
                            self._engine.setProperty("voice", v.id)
                            break
            except Exception as e:
                logger.warning(f"[TTS] Engine init error: {e}")
                self._engine = None
        return self._engine

    def speak(self, text: str) -> bool:
        """
        Speaks text out loud synchronously through the PC speakers.
        """
        clean_text = self._sanitize_text(text)
        if not clean_text:
            return False

        try:
            engine = self._get_engine()
            if engine:
                engine.say(clean_text)
                engine.runAndWait()
                return True
        except Exception as e:
            logger.error(f"[TTS] Speech playback error: {e}")
        return False

    async def speak_async(self, text: str):
        """Non-blocking async speak."""
        await asyncio.to_thread(self.speak, text)

    def text_to_audio_file(self, text: str, output_format: str = "wav") -> Optional[str]:
        """
        Renders text into an audio file (.wav) for sending over Telegram or Web APIs.
        """
        clean_text = self._sanitize_text(text)
        if not clean_text:
            return None

        out_file = tempfile.mktemp(suffix=f".{output_format}")
        try:
            engine = self._get_engine()
            if engine:
                engine.save_to_file(clean_text, out_file)
                engine.runAndWait()
                if os.path.exists(out_file) and os.path.getsize(out_file) > 100:
                    return out_file
        except Exception as e:
            logger.error(f"[TTS] Audio file generation error: {e}")
        return None

    def _sanitize_text(self, text: str) -> str:
        """Strip markdown emojis and symbols for clear pronunciation."""
        import re
        t = re.sub(r"[*_`#~\[\]\(\)>]", "", text)
        t = re.sub(r"https?://\S+", "link", t)
        return t.strip()


# Singleton instance
tts_engine = TextToSpeech()
