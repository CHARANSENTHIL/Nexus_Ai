"""Meeting Tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool

from app.agents.meeting_agent import meeting_agent

logger = logging.getLogger(__name__)


@tool
def summarize_meeting_audio(
    audio_path: Optional[str] = None,
    transcript_text: Optional[str] = None,
    meeting_title: Optional[str] = None
) -> Dict[str, Any]:
    """
    Transcribes audio meeting clips or analyzes meeting notes, producing official Executive Minutes
    with summaries, decisions reached, and an action items matrix.
    """
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    meeting_agent.process_meeting(
                        audio_path=audio_path,
                        transcript_text=transcript_text,
                        meeting_title=meeting_title
                    )
                ).result()
        else:
            return asyncio.run(
                meeting_agent.process_meeting(
                    audio_path=audio_path,
                    transcript_text=transcript_text,
                    meeting_title=meeting_title
                )
            )
    except Exception as e:
        logger.error(f"[MeetingTools] summarize_meeting_audio error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
