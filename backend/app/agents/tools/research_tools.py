"""Deep Research Tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool

from app.agents.deep_research_agent import deep_research_agent

logger = logging.getLogger(__name__)


@tool
def conduct_deep_research(
    topic: str,
    depth: str = "comprehensive"
) -> Dict[str, Any]:
    """
    Conducts autonomous multi-hop deep web research on a complex topic.
    Crawls dozens of sources, cross-references evidence, and generates an executive research dossier.
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
                    deep_research_agent.conduct_deep_research(topic=topic, depth=depth)
                ).result()
        else:
            return asyncio.run(deep_research_agent.conduct_deep_research(topic=topic, depth=depth))
    except Exception as e:
        logger.error(f"[ResearchTools] conduct_deep_research error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
