"""
Telegram Voice Handler — Transcribes incoming voice notes and executes them through Nexus AI.
"""
import asyncio
import logging
import os
import tempfile
from typing import Optional

import speech_recognition as sr
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class VoiceHandler:
    """Handles Telegram voice messages and audio files."""

    def __init__(self):
        self.recognizer = sr.Recognizer()

    async def transcribe_audio_file(self, file_path: str) -> Optional[str]:
        """Transcribes audio file to text using speech recognition."""
        def _do_transcribe():
            try:
                # Convert OGG to WAV if needed
                wav_path = file_path
                if file_path.lower().endswith((".ogg", ".oga", ".mp3", ".m4a")):
                    from pydub import AudioSegment
                    audio = AudioSegment.from_file(file_path)
                    wav_path = file_path + ".wav"
                    audio.export(wav_path, format="wav")

                with sr.AudioFile(wav_path) as source:
                    audio_data = self.recognizer.record(source)
                    text = self.recognizer.recognize_google(audio_data)
                    return text
            except sr.UnknownValueError:
                logger.info("[VoiceHandler] Speech unrecognized or silent audio")
                return None
            except Exception as e:
                logger.error(f"[VoiceHandler] Audio transcription error: {e}")
                return None
            finally:
                if wav_path != file_path and os.path.exists(wav_path):
                    try:
                        os.remove(wav_path)
                    except Exception:
                        pass

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _do_transcribe)

    async def handle_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Telegram message handler for voice messages."""
        message = update.message
        if not message or (not message.voice and not message.audio):
            return

        user = update.effective_user
        chat_id = update.effective_chat.id

        voice_obj = message.voice or message.audio
        logger.info(f"[VoiceHandler] 🎙️ Processing voice note ({voice_obj.duration}s) from user {user.id}")

        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        temp_dir = tempfile.gettempdir()
        temp_audio_path = os.path.join(temp_dir, f"voice_{voice_obj.file_id}.ogg")

        try:
            # Download audio from Telegram
            file_info = await context.bot.get_file(voice_obj.file_id)
            await file_info.download_to_drive(temp_audio_path)

            # Transcribe
            transcribed_text = await self.transcribe_audio_file(temp_audio_path)

            if transcribed_text and transcribed_text.strip():
                clean_text = transcribed_text.strip()
                logger.info(f"[VoiceHandler] ✅ Transcribed: '{clean_text}'")
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"🎙️ *Voice Note Transcribed:*\n`\"{clean_text}\"`\n\n⚡ Executing command...",
                    parse_mode="Markdown",
                )

                # Route directly into standard message pipeline
                from app.telegram_bot.bot import handle_message
                await handle_message(update, context, text_override=clean_text)
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Couldn't clearly detect speech in the voice message. Please speak clearly or send as text.",
                )
        except Exception as e:
            logger.error(f"[VoiceHandler] Failed to process voice message: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚠️ Voice processing error: {e}",
            )
        finally:
            if os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except Exception:
                    pass


voice_handler = VoiceHandler()
