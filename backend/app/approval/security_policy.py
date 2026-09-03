"""
Security Policy Engine — Evaluates proposed recovery actions against safety boundaries.
Prevents autonomous agents from executing destructive commands without explicit human approval.
"""
import re
import logging
from typing import Callable, Optional, Tuple

from app.agents.self_healing_models import RecoveryAction, RiskLevel
from app.approval.executor import approval_center, add_audit_entry, AuditLog

logger = logging.getLogger(__name__)

# Hard blocked destructive patterns (CRITICAL risk - Never executed)
_CRITICAL_PATTERNS = [
    r"set-mppreference",
    r"disable.*antivirus",
    r"advfirewall.*state\s+off",
    r"reg\s+(delete|add)\s+hklm",
    r"format\s+[c-z]:",
    r"rmdir\s+/s\s+/q\s+c:\\windows",
    r"del\s+/f\s+/s\s+/q\s+c:\\windows",
    r"remove-item\s+-recurse\s+c:\\windows",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",  # fork bomb
]

# Patterns that require explicit human approval (HIGH risk)
_HIGH_RISK_PATTERNS = [
    r"del\s+/f",
    r"rmdir\s+/s",
    r"remove-item\s+-recurse",
    r"taskkill\s+/f\s+/im\s+explorer\.exe",
    r"taskkill\s+/f\s+/im\s+svchost\.exe",
    r"shutdown",
    r"restart-computer",
]


class SecurityPolicyEngine:
    """
    Evaluates proposed recovery actions against risk tiers and safety rules.
    """

    def evaluate_risk(self, action: RecoveryAction) -> Tuple[RiskLevel, str]:
        """Classify risk level of a recovery action."""
        cmd = ""
        if action.tool_name == "run_shell_command":
            cmd = action.arguments.get("command", "").lower()

        # 1. Check for CRITICAL blocked commands
        for pattern in _CRITICAL_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                logger.error(f"[SecurityEngine] 🚫 CRITICAL BLOCKED command pattern detected: {pattern}")
                return RiskLevel.CRITICAL, f"Blocked dangerous security-sensitive operation: '{pattern}'"

        # 2. Check for HIGH risk commands requiring approval
        for pattern in _HIGH_RISK_PATTERNS:
            if re.search(pattern, cmd, re.IGNORECASE):
                return RiskLevel.HIGH, f"High-risk system modification requires explicit user approval: '{pattern}'"

        # 3. Pip install commands in virtualenv are LOW risk
        if "pip install" in cmd:
            # Check for suspicious package names
            pkg = action.arguments.get("command", "").split("pip install")[-1].strip()
            if any(char in pkg for char in (";", "&&", "|", "`", "$")):
                return RiskLevel.CRITICAL, "Blocked command injection in package name"
            return RiskLevel.LOW, f"Safe Python dependency installation: {pkg}"

        # Default to action's declared risk level
        return action.risk_level, action.description

    async def authorize(
        self,
        action: RecoveryAction,
        user_id: str = "default_user",
        notify_fn: Optional[Callable] = None,
    ) -> Tuple[bool, str]:
        """
        Determine if action can proceed.
        - LOW / MEDIUM: Automatically permitted and logged.
        - HIGH: Pauses and requests Telegram approval.
        - CRITICAL: Rejected immediately.
        """
        risk, reason = self.evaluate_risk(action)

        if risk == RiskLevel.CRITICAL:
            add_audit_entry(AuditLog(
                user_id=user_id,
                action_type=f"recovery_{action.strategy_name}",
                details={"action": action.model_dump(), "risk": risk.value, "reason": reason},
                outcome="blocked",
            ))
            return False, f"🚫 Action blocked by security policy: {reason}"

        if risk == RiskLevel.HIGH or action.requires_approval:
            if not notify_fn:
                return False, f"⚠️ Action requires approval but no notification channel available"

            logger.info(f"[SecurityEngine] Escalating HIGH risk recovery action '{action.description}' for approval")
            approved = await approval_center.request_approval(
                user_id=user_id,
                action_type=f"recovery_{action.strategy_name}",
                details={"action": action.description, "arguments": action.arguments, "risk": risk.value},
                notify_fn=notify_fn,
            )
            if not approved:
                return False, "❌ Action rejected by user"
            return True, "✅ Approved by user"

        # LOW or MEDIUM risk -> Auto-allowed
        add_audit_entry(AuditLog(
            user_id=user_id,
            action_type=f"recovery_{action.strategy_name}",
            details={"action": action.model_dump(), "risk": risk.value},
            outcome="auto_allowed",
        ))
        return True, "✅ Permitted by security policy"


# Singleton
security_policy_engine = SecurityPolicyEngine()
