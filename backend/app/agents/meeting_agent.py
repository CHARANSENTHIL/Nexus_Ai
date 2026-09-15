"""Live Meeting & Audio Note-Taking Assistant for Nexus AI.

Transcribes recorded audio meetings and extracts structured executive minutes:
- Executive Summary
- Key Discussion Topics
- Strategic Decisions Made
- Action Items Matrix (Task, Owner, Deadline)
"""
import os
import re
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MEETING_MODEL = os.getenv("MEETING_MODEL", "phi4-mini:latest")
MINUTES_DIR = Path("D:/nexus_ai/meeting_minutes")
MINUTES_DIR.mkdir(parents=True, exist_ok=True)


class MeetingAgent:
    """Agent for meeting audio transcription and executive minutes extraction."""

    def __init__(self, ollama_url: str = OLLAMA_BASE_URL, model: str = MEETING_MODEL):
        self.ollama_url = ollama_url
        self.model = model

    async def process_meeting(
        self,
        audio_path: Optional[str] = None,
        transcript_text: Optional[str] = None,
        meeting_title: Optional[str] = None
    ) -> Dict[str, Any]:
        """Transcribes meeting audio or processes raw transcript into Executive Minutes."""
        logger.info(f"[MeetingAgent] Processing meeting '{meeting_title or 'Executive Session'}'...")

        raw_text = transcript_text or ""
        if audio_path and os.path.exists(audio_path) and not raw_text:
            from app.voice.transcriber import transcriber
            trans_res = await transcriber.transcribe_file(audio_path)
            if trans_res.get("success"):
                raw_text = trans_res.get("text", "")
            else:
                return {"success": False, "error": f"Audio transcription failed: {trans_res.get('error')}"}

        if not raw_text.strip():
            return {"success": False, "error": "No audio or transcript provided to analyze."}

        # 1. Synthesize Executive Minutes using local LLM
        minutes_md = await self._synthesize_minutes(raw_text, meeting_title)

        # 2. Save Minutes File
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        title_safe = re.sub(r"[^a-zA-Z0-9_]", "_", meeting_title or "Meeting")[:30]
        out_file = MINUTES_DIR / f"{title_safe}_{timestamp}.md"
        out_file.write_text(minutes_md, encoding="utf-8")

        return {
            "success": True,
            "meeting_title": meeting_title or "Executive Meeting",
            "file_path": str(out_file),
            "transcript_length": len(raw_text),
            "minutes": minutes_md
        }

    async def _synthesize_minutes(self, transcript: str, title: Optional[str]) -> str:
        """Prompts LLM to structure transcript into crisp executive minutes."""
        prompt = (
            f"You are a Chief of Staff. Synthesize the following meeting transcript into crisp, official Executive Meeting Minutes.\n\n"
            f"Meeting Title: {title or 'Executive Sync'}\n"
            f"Transcript:\n```\n{transcript[:3000]}\n```\n\n"
            f"Format requirements:\n"
            f"# 📋 Executive Meeting Minutes: {title or 'Executive Sync'}\n"
            f"**Date**: {datetime.now().strftime('%B %d, %Y')}\n\n"
            f"## 1. Executive Summary\n"
            f"## 2. Key Discussion Topics\n"
            f"## 3. Decisions Reached\n"
            f"## 4. Action Items & Next Steps\n"
            f"- [ ] **[Action Item]** | Owner: [Name/Role] | Deadline: [Timeline]\n\n"
            f"Make it professional, structured, and actionable."
        )

        for m in [self.model, "phi4-mini:latest", "qwen3:4b"]:
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{self.ollama_url}/api/generate",
                        json={"model": m, "prompt": prompt, "stream": False}
                    )
                    if resp.status_code == 200:
                        return resp.json().get("response", "").strip()
            except Exception:
                continue

        return f"# Executive Meeting Minutes\n\n{transcript}"

    summarize_meeting = process_meeting


meeting_agent = MeetingAgent()
