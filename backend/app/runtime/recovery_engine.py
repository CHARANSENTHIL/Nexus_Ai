"""
Recovery Engine — Bounded self-healing and error taxonomy resolution.
Prevents infinite retry loops by enforcing max_retries <= 3 and escalating to Human Handoff.
"""
import re
import logging
from typing import Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)


class ErrorCategory:
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    NOT_FOUND = "NOT_FOUND"
    NETWORK_TIMEOUT = "NETWORK_TIMEOUT"
    AUTH_WALL = "AUTH_WALL"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNKNOWN = "UNKNOWN"


class RecoveryEngine:
    """
    Classifies execution failures and determines recovery action or escalation.
    """

    def classify_error(self, error_message: str, tool_name: str) -> str:
        err = (error_message or "").lower()

        if any(w in err for w in ("modulenotfounderror", "no module named", "importerror", "pip install")):
            return ErrorCategory.DEPENDENCY_ERROR
        elif any(w in err for w in ("syntaxerror", "invalid syntax", "indentationerror")):
            return ErrorCategory.SYNTAX_ERROR
        elif any(w in err for w in ("not found", "no such file", "does not exist", "cannot find")):
            return ErrorCategory.NOT_FOUND
        elif any(w in err for w in ("timeout", "timed out", "connection reset", "unreachable")):
            return ErrorCategory.NETWORK_TIMEOUT
        elif any(w in err for w in ("captcha", "turnstile", "otp", "2fa", "two-factor", "verification code")):
            return ErrorCategory.AUTH_WALL
        elif any(w in err for w in ("permissiondenied", "access is denied", "unauthorized", "forbidden")):
            return ErrorCategory.PERMISSION_DENIED

        return ErrorCategory.UNKNOWN

    def determine_recovery(
        self,
        category: str,
        attempt: int,
        max_retries: int = 3,
        details: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Returns: (can_auto_recover, strategy_description, recovery_plan)
        """
        if attempt >= max_retries:
            return False, f"Max recovery attempts ({max_retries}) reached. Escalating to human handoff.", None

        if category == ErrorCategory.DEPENDENCY_ERROR:
            # Extract missing module
            err_text = str(details.get("error", "")) if details else ""
            match = re.search(r"no module named ['\"]([^'\"]+)['\"]", err_text, re.IGNORECASE)
            pkg = match.group(1) if match else ""
            return True, f"Auto-install missing dependency: {pkg or 'required package'}", {"action": "pip_install", "package": pkg}

        elif category == ErrorCategory.SYNTAX_ERROR:
            return True, "Trigger AST self-healing patch loop", {"action": "ast_patch"}

        elif category == ErrorCategory.NETWORK_TIMEOUT:
            return True, "Exponential backoff and retry connection", {"action": "retry_backoff", "backoff_seconds": attempt * 2}

        elif category == ErrorCategory.AUTH_WALL:
            return False, "Authentication challenge encountered. Human Handoff required.", {"action": "human_handoff"}

        elif category == ErrorCategory.PERMISSION_DENIED:
            return False, "Permission denied. Requesting elevated human authorization.", {"action": "human_approval"}

        return False, "Unrecognized error pattern. Escalating to human handoff.", None


# Singleton instance
recovery_engine = RecoveryEngine()
