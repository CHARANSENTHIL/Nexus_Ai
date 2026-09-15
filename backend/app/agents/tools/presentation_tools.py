"""Presentation generation tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Any, Dict, Optional
from langchain_core.tools import tool

from app.agents.presentation_agent import presentation_agent

logger = logging.getLogger(__name__)


@tool
def create_presentation(prompt: str, filename: Optional[str] = None) -> Dict[str, Any]:
    """
    Creates a modern 16:9 widescreen presentation deck based on a topic or outline prompt.
    Generates responsive HTML5/CSS3 slides and PPTX compatible export.
    Returns the file path, slide count, and presentation details.
    """
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, presentation_agent.create_presentation(prompt, filename)).result()
        else:
            return asyncio.run(presentation_agent.create_presentation(prompt, filename))
    except Exception as e:
        logger.error(f"[presentation_tools] create_presentation error: {e}", exc_info=True)
        return {"success": False, "error": f"Failed to create presentation: {e}"}
