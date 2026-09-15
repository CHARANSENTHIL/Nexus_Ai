"""Autonomous GitHub & Dev Documentation Hub Agent for Nexus AI.

Inspects local git repositories, analyzes commit histories and diffs,
generates changelogs, release notes, and social dev updates (LinkedIn / Twitter).
"""
import os
import re
import sys
import logging
import asyncio
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEV_MODEL = os.getenv("DEV_MODEL", "phi4-mini:latest")


class GitHubHubAgent:
    """Agent for git inspection, automated release notes, and developer communication."""

    def __init__(self, ollama_url: str = OLLAMA_BASE_URL, model: str = DEV_MODEL):
        self.ollama_url = ollama_url
        self.model = model

    async def generate_changelog(
        self,
        repo_path: str = "D:\\nexus_ai",
        max_commits: int = 15
    ) -> Dict[str, Any]:
        """Generates a structured changelog and release notes from git commit history."""
        target_dir = Path(repo_path)
        if not target_dir.exists():
            return {"success": False, "error": f"Repository path not found: {repo_path}"}

        # 1. Fetch git logs and diffs
        git_log = await self._run_git(["log", f"-n", str(max_commits), "--pretty=format:%h - %an: %s (%cr)"], target_dir)
        git_status = await self._run_git(["status", "-s"], target_dir)
        git_branch = await self._run_git(["branch", "--show-current"], target_dir)

        if not git_log:
            return {"success": False, "error": "No git history found in repository."}

        # 2. Synthesize Changelog using local LLM
        prompt = (
            f"You are a Technical Lead and Release Engineer. "
            f"Analyze the following git commit log for branch '{git_branch.strip()}':\n\n"
            f"```\n{git_log}\n```\n\n"
            f"Uncommitted Changes:\n```\n{git_status}\n```\n\n"
            f"Generate an official Release Notes / Changelog categorized into:\n"
            f"- 🚀 New Features\n"
            f"- 🔧 Improvements & Refactors\n"
            f"- 🐛 Bug Fixes & Stability\n"
            f"- 📦 Architectural Changes\n\n"
            f"Make it crisp, professional, and formatted in clean GitHub markdown."
        )

        changelog_text = await self._call_llm(prompt)
        return {
            "success": True,
            "branch": git_branch.strip() or "main",
            "commits_analyzed": max_commits,
            "changelog": changelog_text,
            "raw_log": git_log[:500]
        }

    async def draft_dev_social_post(
        self,
        repo_path: str = "D:\\nexus_ai",
        platform: str = "linkedin"
    ) -> Dict[str, Any]:
        """Drafts an engaging social post highlighting recent development accomplishments."""
        target_dir = Path(repo_path)
        git_log = await self._run_git(["log", "-n", "8", "--oneline"], target_dir)

        prompt = (
            f"You are a high-profile AI engineer and developer advocate. "
            f"Write an engaging, insightful {platform.upper()} post summarizing recent coding milestones based on these git commits:\n\n"
            f"```\n{git_log}\n```\n\n"
            f"Include relevant hashtags (#AI #Python #SoftwareEngineering), bold points, and an inspiring developer takeaway."
        )

        post_text = await self._call_llm(prompt)
        return {
            "success": True,
            "platform": platform,
            "post_content": post_text
        }

    async def _run_git(self, args: List[str], cwd: Path) -> str:
        """Runs git command asynchronously."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "git", *args,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            return stdout_b.decode("utf-8", errors="replace").strip()
        except Exception as e:
            logger.warning(f"[GitHubHubAgent] git {' '.join(args)} error: {e}")
            return ""

    async def _call_llm(self, prompt: str) -> str:
        for m in [self.model, "phi4-mini:latest", "qwen3:4b"]:
            try:
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(
                        f"{self.ollama_url}/api/generate",
                        json={"model": m, "prompt": prompt, "stream": False}
                    )
                    if resp.status_code == 200:
                        return resp.json().get("response", "").strip()
            except Exception:
                continue
        return "Failed to generate LLM summary for git repository."


github_hub_agent = GitHubHubAgent()
