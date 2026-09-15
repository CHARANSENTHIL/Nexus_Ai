"""GitHub & Dev Documentation Tools for Nexus AI."""
import asyncio
import concurrent.futures
import logging
from typing import Dict, Any, Optional
from langchain_core.tools import tool

from app.agents.github_hub_agent import github_hub_agent

logger = logging.getLogger(__name__)


@tool
def generate_git_changelog(repo_path: str = "D:\\nexus_ai", max_commits: int = 15) -> Dict[str, Any]:
    """
    Analyzes recent Git commits and branch diffs, synthesizing an official Markdown changelog / release notes.
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
                    github_hub_agent.generate_changelog(repo_path=repo_path, max_commits=max_commits)
                ).result()
        else:
            return asyncio.run(github_hub_agent.generate_changelog(repo_path=repo_path, max_commits=max_commits))
    except Exception as e:
        logger.error(f"[GitHubTools] generate_git_changelog error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@tool
def draft_developer_social_post(repo_path: str = "D:\\nexus_ai", platform: str = "linkedin") -> Dict[str, Any]:
    """
    Drafts an engaging LinkedIn or Twitter/X post celebrating recent coding accomplishments from git history.
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
                    github_hub_agent.draft_dev_social_post(repo_path=repo_path, platform=platform)
                ).result()
        else:
            return asyncio.run(github_hub_agent.draft_dev_social_post(repo_path=repo_path, platform=platform))
    except Exception as e:
        logger.error(f"[GitHubTools] draft_developer_social_post error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
