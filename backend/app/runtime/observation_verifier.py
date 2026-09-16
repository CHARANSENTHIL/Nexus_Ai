"""
Observation Verifier — Deep Deterministic & Semantic verification after every tool action.
Implements the Action -> Observation -> Verification loop (preventing 'assume success' errors).
"""
import os
import ast
import psutil
import logging
import asyncio
from pathlib import Path
from typing import Any, Dict, Optional, List

from app.runtime.task_models import VerificationResult

logger = logging.getLogger(__name__)


class ObservationVerifier:
    """
    Executes domain-specific deterministic and multi-stage semantic verification checks following action execution.
    """

    async def verify(
        self,
        strategy: Optional[str],
        tool_name: str,
        tool_input: Dict[str, Any],
        raw_result: Any
    ) -> VerificationResult:
        """
        Runs the appropriate verification strategy for the completed action.
        """
        strat = (strategy or self._infer_strategy(tool_name)).lower()

        if strat == "file_exists":
            return self._verify_file_exists(tool_input, raw_result)
        elif strat == "file_deleted":
            return self._verify_file_deleted(tool_input, raw_result)
        elif strat == "process_killed":
            return self._verify_process_killed(tool_input, raw_result)
        elif strat == "process_running":
            return self._verify_process_running(tool_input, raw_result)
        elif strat == "code_syntax":
            return self._verify_code_syntax(tool_input, raw_result)
        elif strat == "code_semantic":
            return self._verify_code_semantic(tool_input, raw_result)
        elif strat == "browser_navigated":
            return await self._verify_browser_navigated(tool_input, raw_result)
        elif strat == "browser_dom_semantic":
            return await self._verify_browser_dom_semantic(tool_input, raw_result)
        elif strat == "endpoint_health":
            return await self._verify_endpoint_health(tool_input, raw_result)
        else:
            return self._verify_general_success(raw_result)

    def _infer_strategy(self, tool_name: str) -> str:
        name = tool_name.lower()
        if "delete_file" in name or "remove_file" in name:
            return "file_deleted"
        elif "create" in name or "write" in name or "copy" in name or "download" in name or "presentation" in name or "blender" in name:
            return "file_exists"
        elif "kill_process" in name or "stop_process" in name:
            return "process_killed"
        elif "open_app" in name or "launch" in name or "start" in name:
            return "process_running"
        elif "diff" in name or "patch" in name or "code" in name:
            return "code_syntax"
        elif "url" in name or "browse" in name or "navigate" in name:
            return "browser_navigated"
        return "general"

    def _verify_file_exists(self, tool_input: Dict[str, Any], raw_result: Any) -> VerificationResult:
        target_path = None
        for k in ("destination", "path", "file_path", "filename", "output_path", "target_file"):
            if k in tool_input and tool_input[k]:
                target_path = str(tool_input[k])
                break

        if not target_path and isinstance(raw_result, dict):
            for k in ("file_path", "destination", "saved_path", "path"):
                if k in raw_result and raw_result[k]:
                    target_path = str(raw_result[k])
                    break

        if target_path:
            p = Path(target_path)
            if p.exists() and p.is_file() and p.stat().st_size > 0:
                return VerificationResult(
                    passed=True,
                    strategy_used="file_exists",
                    details=f"File verified on disk: '{target_path}' ({p.stat().st_size} bytes)",
                    metrics={"file_size": p.stat().st_size}
                )
            elif p.exists() and p.is_dir():
                return VerificationResult(
                    passed=True,
                    strategy_used="file_exists",
                    details=f"Directory verified on disk: '{target_path}'"
                )
            return VerificationResult(
                passed=False,
                strategy_used="file_exists",
                details=f"Target file missing or 0 bytes: '{target_path}'"
            )

        return self._verify_general_success(raw_result)

    def _verify_file_deleted(self, tool_input: Dict[str, Any], raw_result: Any) -> VerificationResult:
        target_path = tool_input.get("path") or tool_input.get("file_path")
        if target_path:
            if not Path(target_path).exists():
                return VerificationResult(
                    passed=True,
                    strategy_used="file_deleted",
                    details=f"File verified deleted: '{target_path}'"
                )
            return VerificationResult(
                passed=False,
                strategy_used="file_deleted",
                details=f"File still exists on disk after delete attempt: '{target_path}'"
            )
        return self._verify_general_success(raw_result)

    def _verify_process_killed(self, tool_input: Dict[str, Any], raw_result: Any) -> VerificationResult:
        pid = tool_input.get("pid")
        if pid:
            exists = psutil.pid_exists(int(pid))
            if not exists:
                return VerificationResult(
                    passed=True,
                    strategy_used="process_killed",
                    details=f"Process {pid} verified terminated."
                )
            return VerificationResult(
                passed=False,
                strategy_used="process_killed",
                details=f"Process {pid} is still running."
            )
        return self._verify_general_success(raw_result)

    def _verify_process_running(self, tool_input: Dict[str, Any], raw_result: Any) -> VerificationResult:
        app_name = (tool_input.get("app_name") or tool_input.get("name") or "").lower()
        if app_name:
            for p in psutil.process_iter(["name"]):
                try:
                    if app_name in (p.info["name"] or "").lower():
                        return VerificationResult(
                            passed=True,
                            strategy_used="process_running",
                            details=f"Process '{app_name}' verified running (PID {p.pid})."
                        )
                except Exception:
                    pass
        return self._verify_general_success(raw_result)

    def _verify_code_syntax(self, tool_input: Dict[str, Any], raw_result: Any) -> VerificationResult:
        target_file = tool_input.get("file_path") or tool_input.get("target_file")
        if target_file and str(target_file).endswith(".py") and Path(target_file).exists():
            try:
                ast.parse(Path(target_file).read_text(encoding="utf-8"))
                return VerificationResult(
                    passed=True,
                    strategy_used="code_syntax",
                    details=f"Python syntax verified in {target_file}"
                )
            except SyntaxError as e:
                return VerificationResult(
                    passed=False,
                    strategy_used="code_syntax",
                    details=f"SyntaxError detected: {e}"
                )
        return self._verify_general_success(raw_result)

    def _verify_code_semantic(self, tool_input: Dict[str, Any], raw_result: Any) -> VerificationResult:
        """Deep semantic check for Python AST: checks for required symbols/classes/functions."""
        target_file = tool_input.get("file_path") or tool_input.get("target_file")
        expected_symbols = tool_input.get("expected_symbols", [])
        if target_file and Path(target_file).exists():
            try:
                tree = ast.parse(Path(target_file).read_text(encoding="utf-8"))
                found_symbols = {
                    node.name for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                }
                missing = [s for s in expected_symbols if s not in found_symbols]
                if missing:
                    return VerificationResult(
                        passed=False,
                        strategy_used="code_semantic",
                        details=f"Missing expected AST symbols: {missing}"
                    )
                return VerificationResult(
                    passed=True,
                    strategy_used="code_semantic",
                    details=f"AST verified with {len(found_symbols)} defined symbols.",
                    metrics={"symbols_count": len(found_symbols)}
                )
            except Exception as e:
                return VerificationResult(
                    passed=False,
                    strategy_used="code_semantic",
                    details=f"AST parsing failed: {e}"
                )
        return self._verify_code_syntax(tool_input, raw_result)

    async def _verify_browser_navigated(self, tool_input: Dict[str, Any], raw_result: Any) -> VerificationResult:
        from app.browser.playwright_manager import playwright_manager
        current_url = playwright_manager._current_url
        if current_url:
            return VerificationResult(
                passed=True,
                strategy_used="browser_navigated",
                details=f"Browser connected to active URL: {current_url}"
            )
        return self._verify_general_success(raw_result)

    async def _verify_browser_dom_semantic(self, tool_input: Dict[str, Any], raw_result: Any) -> VerificationResult:
        """Semantic verification of DOM state, element presence, and inner text."""
        from app.browser.playwright_manager import playwright_manager
        selector = tool_input.get("expected_selector")
        text_match = tool_input.get("expected_text")
        page = playwright_manager._page

        if not page:
            return self._verify_general_success(raw_result)

        try:
            if selector:
                elem = await page.query_selector(selector)
                if not elem:
                    return VerificationResult(
                        passed=False,
                        strategy_used="browser_dom_semantic",
                        details=f"Expected DOM element '{selector}' not found on page."
                    )
            if text_match:
                content = await page.content()
                if text_match.lower() not in content.lower():
                    return VerificationResult(
                        passed=False,
                        strategy_used="browser_dom_semantic",
                        details=f"Expected text '{text_match}' not found in DOM."
                    )
            return VerificationResult(
                passed=True,
                strategy_used="browser_dom_semantic",
                details="DOM semantic condition verified."
            )
        except Exception as e:
            return VerificationResult(
                passed=False,
                strategy_used="browser_dom_semantic",
                details=f"DOM verification error: {e}"
            )

    async def _verify_endpoint_health(self, tool_input: Dict[str, Any], raw_result: Any) -> VerificationResult:
        """Verify local HTTP service health endpoint."""
        import urllib.request
        port = tool_input.get("port", 8000)
        path = tool_input.get("path", "/health")
        url = f"http://127.0.0.1:{port}{path}"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status in (200, 204):
                    return VerificationResult(
                        passed=True,
                        strategy_used="endpoint_health",
                        details=f"HTTP endpoint '{url}' returned status {resp.status}"
                    )
                return VerificationResult(
                    passed=False,
                    strategy_used="endpoint_health",
                    details=f"HTTP endpoint '{url}' returned non-200 status: {resp.status}"
                )
        except Exception as e:
            return VerificationResult(
                passed=False,
                strategy_used="endpoint_health",
                details=f"Failed connecting to '{url}': {e}"
            )

    def _verify_general_success(self, raw_result: Any) -> VerificationResult:
        if isinstance(raw_result, dict):
            if raw_result.get("success") is False or "error" in raw_result:
                return VerificationResult(
                    passed=False,
                    strategy_used="general",
                    details=str(raw_result.get("error", "Action returned failure status."))
                )
            return VerificationResult(
                passed=True,
                strategy_used="general",
                details="Action completed with success status."
            )
        elif isinstance(raw_result, str):
            if raw_result.startswith("❌") or "error" in raw_result.lower():
                return VerificationResult(
                    passed=False,
                    strategy_used="general",
                    details=raw_result[:200]
                )
            return VerificationResult(
                passed=True,
                strategy_used="general",
                details=raw_result[:200]
            )
        return VerificationResult(passed=True, strategy_used="general", details="Action executed.")


# Singleton instance
observation_verifier = ObservationVerifier()
