"""
Real-time Local Microphone Listener for Nexus AI.
Uses sounddevice & soundfile to record audio without requiring PyAudio/C++ build tools.
"""
import os
import asyncio
import logging
import tempfile
from typing import Optional, Callable
from app.voice.transcriber import transcriber
from app.voice.tts import tts_engine
from app.agents.planner import IntentRouter
from app.computer_use.interface import computer

logger = logging.getLogger(__name__)


class VoiceCommandListener:
    """Microphone voice command listener with wake-word detection and fast execution."""

    def __init__(self, wake_words=("nexus", "hey nexus", "jarvis")):
        self.wake_words = [w.lower() for w in wake_words]
        self.is_listening = False
        self._stop_event = asyncio.Event()

    async def record_mic_audio(self, duration: float = 5.0, sample_rate: int = 16000) -> Optional[str]:
        """
        Records from default microphone using sounddevice and exports to a temporary WAV file.
        """
        try:
            import sounddevice as sd
            import soundfile as sf
            import numpy as np

            logger.info(f"[VoiceListener] 🎙️ Recording from microphone ({duration}s)...")
            recording = await asyncio.to_thread(
                sd.rec,
                int(duration * sample_rate),
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
            )
            await asyncio.to_thread(sd.wait)

            # Check if volume is above noise threshold
            max_amp = np.max(np.abs(recording)) if len(recording) > 0 else 0
            if max_amp < 100:
                logger.debug("[VoiceListener] Audio too quiet / silence detected.")
                return None

            tmp_wav = tempfile.mktemp(suffix=".wav")
            await asyncio.to_thread(sf.write, tmp_wav, recording, sample_rate, format="WAV", subtype="PCM_16")
            return tmp_wav
        except Exception as e:
            logger.warning(f"[VoiceListener] sounddevice recording error: {e}")
            return None

    async def listen_once_from_mic(self, duration: float = 5.0) -> Optional[str]:
        """
        Records audio from PC microphone and transcribes it to text.
        """
        wav_path = await self.record_mic_audio(duration=duration)
        if not wav_path or not os.path.exists(wav_path):
            return None

        try:
            res = await transcriber.transcribe_file(wav_path)
            if res.get("success"):
                text = res.get("text", "").strip()
                logger.info(f"[VoiceListener] 🎙️ Heard: '{text}'")
                return text
            return None
        finally:
            if wav_path and os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception:
                    pass

    async def process_voice_command(self, text: str) -> str:
        """
        Takes raw spoken text, strips wake-word, and executes the requested command.
        """
        cleaned = text.lower().strip()
        for w in self.wake_words:
            if cleaned.startswith(w):
                cleaned = cleaned[len(w):].strip(", ").strip()
                break

        if not cleaned:
            return "Yes? I am listening."

        logger.info(f"[VoiceListener] ⚡ Executing voice command: '{cleaned}'")

        # 1. Fast Path
        subtasks = IntentRouter.detect(cleaned)
        if subtasks:
            for st in subtasks:
                tool_name = st.get("tool", "")
                tool_input = st.get("tool_input", {})
                from app.agents.planner import _build_tool_registry, _format_tool_result
                registry = _build_tool_registry()
                fn = registry.get(tool_name)
                if fn:
                    res = await asyncio.to_thread(fn, **tool_input) if isinstance(tool_input, dict) else await asyncio.to_thread(fn, tool_input)
                    out = _format_tool_result(tool_name, res)
                    await tts_engine.speak_async(out[:150])
                    return out

        # 2. Conversational / Complex Path
        from app.agents.chat_agent import chat_agent
        reply = await chat_agent.generate_response(cleaned)
        await tts_engine.speak_async(reply[:200])
        return reply


# Singleton instance
voice_listener = VoiceCommandListener()
