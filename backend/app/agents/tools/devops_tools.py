"""DevOps & codebase tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool

from app.agents.devops_agent import devops_agent

logger = logging.getLogger(__name__)


@tool
def test_and_repair_codebase(
    target_dir: str = "D:\\nexus_ai\\backend",
    test_path: Optional[str] = None,
    auto_fix: bool = False,
    prompt: Optional[str] = None
) -> Dict[str, Any]:
    """
    Runs pytest test suites, parses error tracebacks, diagnoses root causes using local LLM,
    and returns diagnostic reports with suggested code fixes.
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
                    devops_agent.run_tests_and_diagnose(
                        target_dir=target_dir,
                        test_path=test_path,
                        auto_fix=auto_fix,
                        prompt=prompt
                    )
                ).result()
        else:
            return asyncio.run(
                devops_agent.run_tests_and_diagnose(
                    target_dir=target_dir,
                    test_path=test_path,
                    auto_fix=auto_fix,
                    prompt=prompt
                )
            )
    except Exception as e:
        logger.error(f"[DevOpsTools] test_and_repair_codebase failed: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
