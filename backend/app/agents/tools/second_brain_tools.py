"""Second Brain Tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional, List
from langchain_core.tools import tool

from app.agents.second_brain_agent import second_brain_agent

logger = logging.getLogger(__name__)


@tool
def capture_thought_or_note(
    text: str,
    category: str = "auto"
) -> Dict[str, Any]:
    """
    Captures a thought, task, idea, journal entry, or reminder into the persistent Obsidian Second Brain vault.
    Automatically indexes wikilinks and organizes by category.
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
                    second_brain_agent.capture(text=text, category=category)
                ).result()
        else:
            return asyncio.run(second_brain_agent.capture(text=text, category=category))
    except Exception as e:
        logger.error(f"[SecondBrainTools] capture_thought_or_note error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@tool
def query_second_brain(query: str) -> Dict[str, Any]:
    """
    Searches the Second Brain knowledge vault for notes, ideas, tasks, and memories matching a keyword or topic.
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
                    second_brain_agent.query_vault(query=query)
                ).result()
        else:
            return asyncio.run(second_brain_agent.query_vault(query=query))
    except Exception as e:
        logger.error(f"[SecondBrainTools] query_second_brain error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
