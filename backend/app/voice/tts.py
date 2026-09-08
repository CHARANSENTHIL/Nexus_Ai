"""
Text-to-Speech (TTS) Voice Engine for Nexus AI.
Uses native Windows SAPI5 (pyttsx3 / PowerShell SpeechSynthesizer) for zero-latency local voice output,
and exports audio files (.wav) for Telegram voice responses.
"""
import os
import sys
import logging
import asyncio
import tempfile
import subprocess
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class TextToSpeech:
    """Zero-latency local TTS engine with COM safety and audio export."""

    def __init__(self):
        self._engine = None

    def _init_com(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass

    def _get_engine(self):
        self._init_com()
        if self._engine is None:
            try:
                import pyttsx3
                self._engine = pyttsx3.init()
                self._engine.setProperty("rate", 180)
                self._engine.setProperty("volume", 1.0)

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

        # 1. Try pyttsx3
        try:
            engine = self._get_engine()
            if engine:
                engine.say(clean_text)
                engine.runAndWait()
                return True
        except Exception as e:
            logger.warning(f"[TTS] pyttsx3 playback note: {e}")

        # 2. Native Windows PowerShell Speech fallback
        if sys.platform == "win32":
            try:
                escaped = clean_text.replace("'", "''").replace('"', '`"')
                cmd = f'powershell -Command "Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.Rate = 1; $synth.Speak(\'{escaped}\');"'
                subprocess.run(cmd, shell=True, timeout=10)
                return True
            except Exception as pe:
                logger.error(f"[TTS] PowerShell speech fallback error: {pe}")

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

        # 1. Try pyttsx3
        try:
            engine = self._get_engine()
            if engine:
                engine.save_to_file(clean_text, out_file)
                engine.runAndWait()
                if os.path.exists(out_file) and os.path.getsize(out_file) > 100:
                    return out_file
        except Exception as e:
            logger.debug(f"[TTS] pyttsx3 save_to_file note: {e}")

        # 2. Native Windows PowerShell SAPI audio export fallback
        if sys.platform == "win32":
            try:
                escaped = clean_text.replace("'", "''")
                out_escaped = out_file.replace("'", "''")
                cmd = f'powershell -Command "Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.SetOutputToWaveFile(\'{out_escaped}\'); $synth.Speak(\'{escaped}\'); $synth.Dispose();"'
                subprocess.run(cmd, shell=True, timeout=12)
                if os.path.exists(out_file) and os.path.getsize(out_file) > 100:
                    return out_file
            except Exception as pe:
                logger.error(f"[TTS] PowerShell SAPI export error: {pe}")

        return None

    def _sanitize_text(self, text: str) -> str:
        """Strip markdown emojis and symbols for clear pronunciation."""
        import re
        t = re.sub(r"[*_`#~\[\]\(\)>]", "", text)
        t = re.sub(r"https?://\S+", "link", t)
        return t.strip()


# Singleton instance
tts_engine = TextToSpeech()
