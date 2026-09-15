"""App Architect Tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool

from app.agents.app_architect_agent import app_architect_agent

logger = logging.getLogger(__name__)


@tool
def build_autonomous_application(
    prompt: str,
    app_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Autonomously provisions and builds a full software/Python application:
    Creates dedicated folder, creates isolated virtual environment (.venv),
    installs all necessary pip packages inside the venv, synthesizes complete source code (main.py, config, README),
    and creates single-click launch scripts.
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
                    app_architect_agent.build_application(prompt=prompt, app_name=app_name)
                ).result()
        else:
            return asyncio.run(app_architect_agent.build_application(prompt=prompt, app_name=app_name))
    except Exception as e:
        logger.error(f"[AppArchitectTools] build_autonomous_application error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
