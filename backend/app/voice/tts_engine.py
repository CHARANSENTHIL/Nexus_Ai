"""Neural Text-to-Speech Engine (Full Duplex Voice JARVIS) for Nexus AI.

Synthesizes high-fidelity neural speech using edge-tts.
Outputs high-compression Opus/OGG or MP3 voice clips for Telegram and local audio playback.
"""
import os
import re
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

VOICE_DIR = Path("D:/nexus_ai/backend/voice_output")
VOICE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_VOICE = "en-US-ChristopherNeural"  # Authoritative, calm JARVIS-style voice


class TTSEngine:
    """Neural text-to-speech synthesis engine."""

    def __init__(self, voice: str = DEFAULT_VOICE):
        self.voice = voice

    async def generate_voice_note(
        self,
        text: str,
        output_filename: Optional[str] = None,
        voice: Optional[str] = None
    ) -> Dict[str, Any]:
        """Generates a high-quality speech audio file from text."""
        import edge_tts

        clean_text = self._clean_for_speech(text)
        if not clean_text:
            return {"success": False, "error": "No speakable text provided."}

        selected_voice = voice or self.voice
        if not output_filename:
            import time
            output_filename = f"voice_reply_{int(time.time())}.ogg"

        output_path = VOICE_DIR / output_filename

        try:
            communicate = edge_tts.Communicate(clean_text, selected_voice)
            await communicate.save(str(output_path))

            logger.info(f"[TTSEngine] Synthesized speech to {output_path} ({len(clean_text)} chars)")
            return {
                "success": True,
                "file_path": str(output_path),
                "voice": selected_voice,
                "text_length": len(clean_text)
            }
        except Exception as e:
            logger.error(f"[TTSEngine] Voice synthesis failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    def _clean_for_speech(self, text: str) -> str:
        """Strips markdown syntax, URLs, code blocks, emojis to ensure smooth, natural speech."""
        # 1. Remove code blocks
        t = re.sub(r"```[\s\S]*?```", " [Code output omitted] ", text)
        # 2. Remove markdown links [text](url) -> text
        t = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", t)
        # 3. Remove URLs
        t = re.sub(r"https?://\S+", "", t)
        # 4. Remove bold/italics markers
        t = re.sub(r"[*_~`#]", "", t)
        # 5. Remove multiple newlines/spaces
        t = re.sub(r"\s+", " ", t).strip()
        # 6. Limit speech length for snappy Telegram voice note replies (max ~600 chars)
        if len(t) > 600:
            t = t[:590] + "..."
        return t


tts_engine = TTSEngine()
