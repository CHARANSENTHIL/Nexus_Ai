"""SecOps & Security Tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool

from app.agents.secops_agent import secops_agent

logger = logging.getLogger(__name__)


@tool
def audit_codebase_security(target_path: str = "D:\\nexus_ai\\backend") -> Dict[str, Any]:
    """
    Scans a directory or codebase for security vulnerabilities, hardcoded secrets/API keys,
    dangerous exec/eval patterns, and dependency risks, producing an official Security Grade (A+ to F).
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
                    secops_agent.audit_codebase_security(target_path=target_path)
                ).result()
        else:
            return asyncio.run(secops_agent.audit_codebase_security(target_path=target_path))
    except Exception as e:
        logger.error(f"[SecOpsTools] audit_codebase_security error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
