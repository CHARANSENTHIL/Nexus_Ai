"""
Nexus AI Self-Healing Error Handler — automatic failure recovery.
Ported from JIN/JARVIS project. Pure Python, Docker-safe.

Strategy:
1. Fast-path regex patterns for known errors (ModuleNotFoundError, PermissionError, etc.)
2. Auto-retry with healing between attempts (max 3)
3. Logs all failures for adaptive learning
"""
import re
import logging
import subprocess
from typing import Callable, Any, Dict, Optional

logger = logging.getLogger(__name__)


# Known error patterns → auto-fix strategies
ERROR_PATTERNS = [
    {
        "pattern": r"ModuleNotFoundError: No module named '(\w+)'",
        "fix_type": "pip_install",
        "extract_group": 1,
        "description": "Missing Python module → pip install",
    },
    {
        "pattern": r"FileNotFoundError:.*'(.+)'",
        "fix_type": "create_directory",
        "extract_group": 1,
        "description": "Missing file/directory → create it",
    },
    {
        "pattern": r"(?i)connection refused|connection error|ECONNREFUSED",
        "fix_type": "retry_later",
        "extract_group": None,
        "description": "Connection refused → retry after delay",
    },
    {
        "pattern": r"(?i)timeout|timed out|TimeoutError",
        "fix_type": "retry_longer",
        "extract_group": None,
        "description": "Timeout → retry with longer timeout",
    },
]


class ErrorHandler:
    """Handles errors with pattern-based auto-fixes and retry logic."""

    def __init__(self):
        self.failure_log = []
        self.max_retries = 3

    def analyze_error(self, error_msg: str) -> Optional[Dict[str, str]]:
        """
        Match an error message against known patterns.
        Returns fix info dict or None if no pattern matches.
        """
        for pattern_info in ERROR_PATTERNS:
            match = re.search(pattern_info["pattern"], error_msg)
            if match:
                fix = {
                    "fix_type": pattern_info["fix_type"],
                    "description": pattern_info["description"],
                    "matched_pattern": pattern_info["pattern"],
                }
                if pattern_info["extract_group"] is not None:
                    try:
                        fix["target"] = match.group(pattern_info["extract_group"])
                    except IndexError:
                        fix["target"] = ""
                return fix
        return None

    def apply_fix(self, fix: Dict[str, str]) -> bool:
        """Apply an auto-fix based on the fix type."""
        fix_type = fix.get("fix_type", "")
        target = fix.get("target", "")

        try:
            if fix_type == "pip_install" and target:
                logger.info(f"[SelfHeal] Auto-installing module: {target}")
                result = subprocess.run(
                    ["pip", "install", target],
                    capture_output=True, text=True, timeout=60
                )
                return result.returncode == 0

            elif fix_type == "create_directory" and target:
                import os
                dir_path = os.path.dirname(target) if '.' in os.path.basename(target) else target
                if dir_path:
                    os.makedirs(dir_path, exist_ok=True)
                    logger.info(f"[SelfHeal] Created directory: {dir_path}")
                    return True

            elif fix_type in ("retry_later", "retry_longer"):
                # These are handled by the retry logic in wrap()
                return True

        except Exception as e:
            logger.warning(f"[SelfHeal] Fix application failed: {e}")
        return False

    def wrap(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute a function with auto-retry and self-healing.
        On failure: analyze error → apply fix → retry (up to max_retries).
        """
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                error_msg = str(e)
                logger.warning(f"[SelfHeal] Attempt {attempt}/{self.max_retries} failed: {error_msg}")

                # Log the failure
                self.failure_log.append({
                    "attempt": attempt,
                    "error": error_msg,
                    "func": getattr(func, "__name__", str(func)),
                })

                # Try to auto-fix
                fix = self.analyze_error(error_msg)
                if fix:
                    logger.info(f"[SelfHeal] Applying fix: {fix['description']}")
                    self.apply_fix(fix)
                else:
                    logger.info(f"[SelfHeal] No auto-fix pattern matched")

                if attempt == self.max_retries:
                    break

                # Brief delay before retry
                import time
                time.sleep(1)

        # All retries exhausted
        raise last_error

    def get_failure_summary(self) -> list:
        """Return recent failure log entries."""
        return self.failure_log[-20:]


# Singleton
error_handler = ErrorHandler()
