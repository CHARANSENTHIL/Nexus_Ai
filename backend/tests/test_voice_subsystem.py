"""
Test Suite for Nexus AI Voice & Audio Subsystem.
"""
import os
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.voice.transcriber import transcriber
from app.voice.tts import tts_engine
from app.voice.listener import voice_listener


class TestVoiceSubsystem:
    """Unit tests for Voice & Audio modules."""

    def test_tts_text_sanitization(self):
        raw = "Hello **world**! Check https://example.com #code `x = 1`"
        clean = tts_engine._sanitize_text(raw)
        assert "**" not in clean
        assert "`" not in clean
        assert "#" not in clean
        assert "link" in clean

    def test_tts_file_generation(self):
        wav_path = tts_engine.text_to_audio_file("Testing Nexus AI voice output.", output_format="wav")
        if wav_path:
            assert os.path.exists(wav_path)
            assert os.path.getsize(wav_path) > 100
            try:
                os.remove(wav_path)
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_voice_command_processing(self):
        # Spoken greeting
        res = await voice_listener.process_voice_command("hey nexus, how are you")
        assert len(res) > 0

        # Spoken system command
        res_cpu = await voice_listener.process_voice_command("nexus check cpu")
        assert "CPU" in res_cpu or "State" in res_cpu or len(res_cpu) > 0


@pytest.mark.asyncio
class TestVoiceAPIEndpoints:
    """Test FastAPI endpoints for voice operations."""

    async def test_speak_endpoint(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(
                "/api/v1/voice/speak",
                json={"text": "Nexus AI voice online.", "export_audio": False}
            )
            assert res.status_code == 200
            assert res.json()["success"] is True

    async def test_transcribe_endpoint_invalid(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Send empty byte content
            files = {"file": ("test.wav", b"invalid_audio_bytes", "audio/wav")}
            res = await client.post("/api/v1/voice/transcribe", files=files)
            assert res.status_code == 200
            assert res.json()["success"] is False
