"""Council of Experts Tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool

from app.agents.council_agent import council_agent

logger = logging.getLogger(__name__)


@tool
def deliberate_with_council(topic: str) -> Dict[str, Any]:
    """
    Spawns a 3-agent Council of Experts (The Visionary, The Skeptic, The Pragmatist)
    to debate complex engineering, business, or architecture decisions and produce a Consensus Decision Matrix.
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
                    council_agent.deliberate(topic=topic)
                ).result()
        else:
            return asyncio.run(council_agent.deliberate(topic=topic))
    except Exception as e:
        logger.error(f"[CouncilTools] deliberate_with_council error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
