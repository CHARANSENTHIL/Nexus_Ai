"""Skill & Tool Creator Tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool

from app.agents.skill_creator_agent import skill_creator_agent

logger = logging.getLogger(__name__)


@tool
def create_new_tool(
    tool_name: str,
    purpose: str,
    example_usage: Optional[str] = None
) -> Dict[str, Any]:
    """
    Synthesizes a brand new Python tool on-the-fly, validates and tests it,
    and hot-reloads it into the active tool registry so it can be called immediately.
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
                    skill_creator_agent.create_and_register_tool(
                        tool_name=tool_name,
                        purpose=purpose,
                        example_usage=example_usage
                    )
                ).result()
        else:
            return asyncio.run(
                skill_creator_agent.create_and_register_tool(
                    tool_name=tool_name,
                    purpose=purpose,
                    example_usage=example_usage
                )
            )
    except Exception as e:
        logger.error(f"[SkillCreatorTools] create_new_tool failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@tool
def list_custom_tools() -> Dict[str, Any]:
    """Lists all dynamically created custom tools currently available in Nexus AI."""
    try:
        tools = skill_creator_agent.list_all_custom_tools()
        return {"success": True, "count": len(tools), "tools": tools}
    except Exception as e:
        logger.error(f"[SkillCreatorTools] list_custom_tools failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
