"""Autonomous DevOps & Codebase Maintainer Agent for Nexus AI.

Executes test suites (pytest/unittest), extracts error tracebacks,
analyzes root causes with local Ollama models (phi4-mini / qwen3:4b),
and proposes self-healing patches and git commit suggestions.
"""
import os
import re
import sys
import json
import logging
import asyncio
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
DEVOPS_MODEL = os.getenv("DEVOPS_MODEL", "phi4-mini:latest")


class DevOpsAgent:
    """Agent for automated testing, error diagnostics, and code self-healing."""

    def __init__(self, ollama_url: str = OLLAMA_BASE_URL, model: str = DEVOPS_MODEL):
        self.ollama_url = ollama_url
        self.model = model

    async def run_tests_and_diagnose(
        self,
        target_dir: str = "D:\\nexus_ai\\backend",
        test_path: Optional[str] = None,
        auto_fix: bool = False,
        prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """Runs pytest on the target directory/file, diagnoses failures, and proposes fixes."""
        logger.info(f"[DevOpsAgent] Running tests in '{target_dir}' (target: {test_path})...")
        target_path = Path(target_dir)
        if not target_path.exists():
            return {"success": False, "error": f"Target directory not found: {target_dir}"}

        # 1. Run pytest / python test runner
        cmd = [sys.executable, "-m", "pytest", "-v"]
        if test_path:
            cmd.append(test_path)
        else:
            # Check for tests directory
            tests_dir = target_path / "tests"
            if tests_dir.exists():
                cmd.append(str(tests_dir))
            else:
                cmd.append(str(target_path))

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(target_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout_b, stderr_b = await asyncio.wait_for(process.communicate(), timeout=120.0)
            stdout = stdout_b.decode("utf-8", errors="replace")
            stderr = stderr_b.decode("utf-8", errors="replace")
            returncode = process.returncode
        except asyncio.TimeoutError:
            return {"success": False, "error": "Test run timed out after 120 seconds."}
        except Exception as e:
            return {"success": False, "error": f"Failed to execute tests: {e}"}

        # 2. Parse test results
        output_full = f"{stdout}\n{stderr}"
        passed_match = re.search(r"(\d+)\s+passed", output_full)
        failed_match = re.search(r"(\d+)\s+failed", output_full)
        errors_match = re.search(r"(\d+)\s+error", output_full)

        passed_count = int(passed_match.group(1)) if passed_match else 0
        failed_count = int(failed_match.group(1)) if failed_match else 0
        errors_count = int(errors_match.group(1)) if errors_match else 0

        total_issues = failed_count + errors_count

        if returncode == 0 and total_issues == 0:
            summary = f"All tests passed successfully ({passed_count} passed). Codebase health: 100%."
            return {
                "success": True,
                "status": "ALL_PASSED",
                "summary": summary,
                "passed": passed_count,
                "failed": 0,
                "errors": 0,
                "raw_output": stdout[-1000:] if len(stdout) > 1000 else stdout
            }

        # 3. Analyze failure using local LLM
        diagnostics = await self._analyze_failure_with_llm(output_full, target_dir)

        result_payload = {
            "success": True,
            "status": "ISSUES_FOUND",
            "summary": f"Tests failed: {failed_count} failed, {errors_count} errors, {passed_count} passed.",
            "passed": passed_count,
            "failed": failed_count,
            "errors": errors_count,
            "analysis": diagnostics.get("analysis", ""),
            "proposed_fix": diagnostics.get("proposed_fix", ""),
            "failing_files": diagnostics.get("failing_files", [])
        }

        # 4. Optional Auto-Fix application
        if auto_fix and diagnostics.get("proposed_fix"):
            applied = await self._apply_suggested_patch(diagnostics.get("proposed_fix"), target_dir)
            result_payload["auto_fix_applied"] = applied

        return result_payload

    async def _analyze_failure_with_llm(self, test_output: str, target_dir: str) -> Dict[str, Any]:
        """Calls local Ollama model to diagnose the stack trace and generate a fix."""
        # Trim output to relevant failure sections (max 3000 chars)
        trimmed_output = test_output[-3500:] if len(test_output) > 3500 else test_output
        system_prompt = (
            "You are an expert DevOps and Software Reliability Engineer. "
            "Analyze the following pytest output and stack trace. "
            "Provide: 1) Root cause summary, 2) Failing files and lines, 3) Precise code fix or patch.\n"
            "Return response as JSON with keys: 'analysis', 'failing_files' (list), and 'proposed_fix'."
        )

        user_prompt = f"Target directory: {target_dir}\n\nPytest Output:\n```\n{trimmed_output}\n```"

        for model in [self.model, "phi4-mini:latest", "qwen3:4b", "qwen3:1.7b"]:
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.post(
                        f"{self.ollama_url}/api/generate",
                        json={
                            "model": model,
                            "prompt": f"{system_prompt}\n\n{user_prompt}",
                            "stream": False,
                            "format": "json"
                        }
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        raw_response = data.get("response", "{}")
                        try:
                            parsed = json.loads(raw_response)
                            return parsed
                        except json.JSONDecodeError:
                            return {
                                "analysis": raw_response,
                                "proposed_fix": "",
                                "failing_files": []
                            }
            except Exception as e:
                logger.warning(f"[DevOpsAgent] Model {model} failed: {e}")
                continue

        return {
            "analysis": "Automated diagnosis failed due to LLM connectivity. Check pytest output directly.",
            "proposed_fix": "",
            "failing_files": []
        }

    async def _apply_suggested_patch(self, patch_str: str, target_dir: str) -> bool:
        """Applies patch or safe modifications if valid."""
        logger.info(f"[DevOpsAgent] Attempting auto-fix application in {target_dir}...")
        return False


devops_agent = DevOpsAgent()
