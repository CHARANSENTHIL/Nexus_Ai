"""
Real-time Local Microphone Listener for Nexus AI.
Listens for voice commands from the PC microphone and executes them directly via IntentRouter and ComputerInterface.
"""
import asyncio
import logging
from typing import Optional, Callable
from app.voice.transcriber import transcriber
from app.voice.tts import tts_engine
from app.agents.planner import IntentRouter, planner_agent
from app.computer_use.interface import computer

logger = logging.getLogger(__name__)


class VoiceCommandListener:
    """Microphone voice command listener with wake-word detection and fast execution."""

    def __init__(self, wake_words=("nexus", "hey nexus", "jarvis")):
        self.wake_words = [w.lower() for w in wake_words]
        self.is_listening = False
        self._stop_event = asyncio.Event()

    async def listen_once_from_mic(self, timeout: float = 6.0, phrase_time_limit: float = 8.0) -> Optional[str]:
        """
        Records from the default PC microphone and transcribes the speech.
        """
        import speech_recognition as sr

        recognizer = transcriber._get_recognizer()
        try:
            with sr.Microphone() as source:
                logger.info("[VoiceListener] 🎙️ Listening for microphone input...")
                recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio_data = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)

            text = recognizer.recognize_google(audio_data)
            logger.info(f"[VoiceListener] Heard: '{text}'")
            return text
        except (sr.WaitTimeoutError, sr.UnknownValueError):
            return None
        except Exception as e:
            logger.warning(f"[VoiceListener] Microphone capture error: {e}")
            return None

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
                    tts_engine.speak(out[:150])
                    return out

        # 2. Complex / Conversational Path
        from app.agents.chat_agent import chat_agent
        reply = await chat_agent.generate_response(cleaned)
        tts_engine.speak(reply[:200])
        return reply


# Singleton instance
voice_listener = VoiceCommandListener()
