"""
Speech-to-Text (STT) Audio Transcriber for Nexus AI.
Supports Telegram voice notes (.ogg, .oga), WAV, MP3 audio files, and microphone inputs.
Uses bundled imageio-ffmpeg / soundfile for bulletproof conversion and SpeechRecognition with Google & Whisper engines.
"""
import os
import io
import sys
import logging
import tempfile
import subprocess
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class AudioTranscriber:
    """Universal audio transcriber with bundled ffmpeg and robust audio conversion."""

    def __init__(self):
        self._recognizer = None

    def _get_recognizer(self):
        if self._recognizer is None:
            import speech_recognition as sr
            self._recognizer = sr.Recognizer()
            self._recognizer.energy_threshold = 300
            self._recognizer.dynamic_energy_threshold = True
        return self._recognizer

    def convert_to_wav(self, input_path: str) -> str:
        """
        Converts any audio file (.ogg, .oga, .mp3, .m4a) to a 16kHz mono PCM WAV file.
        Uses bundled imageio-ffmpeg or soundfile.
        """
        out_wav = tempfile.mktemp(suffix=".wav")

        # 1. Try imageio_ffmpeg (bundled binary on Windows)
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            cmd = f'"{ffmpeg_exe}" -y -i "{input_path}" -ar 16000 -ac 1 -c:a pcm_s16le "{out_wav}"'
            res = subprocess.run(cmd, shell=True, capture_output=True, timeout=12)
            if res.returncode == 0 and os.path.exists(out_wav) and os.path.getsize(out_wav) > 100:
                return out_wav
        except Exception as e:
            logger.debug(f"[Transcriber] imageio-ffmpeg conversion note: {e}")

        # 2. Try soundfile
        try:
            import soundfile as sf
            data, samplerate = sf.read(input_path)
            sf.write(out_wav, data, samplerate, format="WAV", subtype="PCM_16")
            if os.path.exists(out_wav) and os.path.getsize(out_wav) > 100:
                return out_wav
        except Exception as se:
            logger.debug(f"[Transcriber] soundfile conversion note: {se}")

        # 3. Try standard ffmpeg in PATH
        try:
            cmd = f'ffmpeg -y -i "{input_path}" -ar 16000 -ac 1 -c:a pcm_s16le "{out_wav}"'
            res = subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
            if res.returncode == 0 and os.path.exists(out_wav) and os.path.getsize(out_wav) > 100:
                return out_wav
        except Exception:
            pass

        return input_path

    async def transcribe_file(self, file_path: str, language: str = "en-US") -> Dict[str, Any]:
        """
        Transcribes an audio file on disk to text.
        """
        import speech_recognition as sr

        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            return {"success": False, "error": f"Audio file not found or empty: {file_path}", "text": ""}

        wav_path = None
        try:
            # Convert non-wav formats (e.g. Telegram .oga/.ogg) to 16kHz PCM WAV
            if not file_path.lower().endswith(".wav"):
                wav_path = self.convert_to_wav(file_path)
                target_path = wav_path
            else:
                target_path = file_path

            recognizer = self._get_recognizer()
            with sr.AudioFile(target_path) as source:
                audio_data = recognizer.record(source)

            # 1. Primary: Google Speech Recognition (free, fast, no API key required)
            try:
                text = recognizer.recognize_google(audio_data, language=language)
                if text:
                    logger.info(f"[Transcriber] 🎙️ Successfully transcribed: '{text}'")
                    return {"success": True, "text": text, "engine": "google"}
            except sr.UnknownValueError:
                return {"success": False, "error": "Could not understand audio (inaudible or silence).", "text": ""}
            except Exception as ge:
                logger.warning(f"[Transcriber] Google speech note: {ge}")

            # 2. Fallback: Local Whisper if installed
            try:
                text = recognizer.recognize_whisper(audio_data, model="base")
                if text:
                    return {"success": True, "text": text, "engine": "whisper"}
            except Exception as we:
                logger.debug(f"[Transcriber] Whisper fallback note: {we}")

            return {"success": False, "error": "Speech recognition engine was unable to transcribe audio.", "text": ""}

        except Exception as e:
            logger.error(f"[Transcriber] Transcription error: {e}", exc_info=True)
            return {"success": False, "error": str(e), "text": ""}
        finally:
            if wav_path and os.path.exists(wav_path) and wav_path != file_path:
                try:
                    os.remove(wav_path)
                except Exception:
                    pass


# Singleton instance
transcriber = AudioTranscriber()
