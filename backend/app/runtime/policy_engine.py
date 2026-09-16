"""
Capability Policy Engine — Pre-execution security and permission evaluation.
Enforces Level 0 to Level 4 capability boundaries BEFORE any tool executes.
The LLM never determines its own authorization.
"""
import re
import logging
from typing import Dict, Any, Tuple, Optional

from app.runtime.task_models import CapabilityLevel, ToolDefinition, SubtaskNode

logger = logging.getLogger(__name__)

# Hard blocked destructive patterns (LEVEL 4 - CRITICAL / BLOCKED)
_BLOCKED_COMMAND_PATTERNS = [
    r"set-mppreference",
    r"disable.*(antivirus|monitoring|behavior|realtime)",
    r"advfirewall.*state\s+off",
    r"reg\s+(delete|add)\s+hklm",
    r"format\s+[a-z]:",
    r"rmdir\s+/s.*c:\\",
    r"del\s+/f.*c:\\",
    r"remove-item.*c:\\",
    r"bcdedit",
    r"vssadmin\s+delete",
    r"wmic\s+shadowcopy\s+delete",
    r"stop-service\s+windefend",
    r"sc\s+config\s+windefend",
    r"takeown.*/f\s+c:\\",
    r"icacls.*c:\\windows",
    r"attrib.*c:\\bootmgr",
    r"runas\s+/user:administrator",
    r"bitsadmin.*/transfer",
    r"certutil.*-urlcache",
    r"iex\s*\(new-object\s+net\.webclient\)",
    r"invoke-webrequest.*(malware|trojan|payload|evil)",
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",  # fork bomb
]

# Sensitive/Destructive command patterns requiring human confirmation (LEVEL 3)
_DESTRUCTIVE_COMMAND_PATTERNS = [
    r"del\s+/f",
    r"rmdir\s+/s",
    r"remove-item\s+-recurse",
    r"taskkill\s+/f",
    r"shutdown",
    r"restart-computer",
    r"drop\s+table",
    r"drop\s+database",
]


class PolicyEngine:
    """
    Evaluates requested tool executions against capability levels, input boundaries, and security rules.
    """

    def evaluate_execution(
        self,
        tool: ToolDefinition,
        tool_input: Dict[str, Any],
        user_id: str
    ) -> Tuple[bool, CapabilityLevel, bool, str]:
        """
        Evaluate tool execution authorization.
        Returns: (is_allowed, capability_level, requires_approval, reason)
        """
        level = tool.capability_level
        cmd_text = ""
        if "command" in tool_input:
            cmd_text = str(tool_input["command"]).lower()
        elif "cmd" in tool_input:
            cmd_text = str(tool_input["cmd"]).lower()

        # 1. Check for Hard-Blocked Privileged Operations (Level 4)
        if cmd_text:
            for pattern in _BLOCKED_COMMAND_PATTERNS:
                if re.search(pattern, cmd_text, re.IGNORECASE):
                    logger.error(f"[PolicyEngine] 🚫 BLOCKED dangerous command pattern: '{pattern}'")
                    return False, CapabilityLevel.LEVEL_4_PRIVILEGED, False, f"Blocked dangerous system command: '{pattern}'"

            for pattern in _DESTRUCTIVE_COMMAND_PATTERNS:
                if re.search(pattern, cmd_text, re.IGNORECASE):
                    level = max(level, CapabilityLevel.LEVEL_3_DESTRUCTIVE)

        # 2. Check tool-specific capability requirements
        if level >= CapabilityLevel.LEVEL_4_PRIVILEGED:
            return False, CapabilityLevel.LEVEL_4_PRIVILEGED, True, "Privileged action requires explicit administrator authorization."

        if level >= CapabilityLevel.LEVEL_3_DESTRUCTIVE:
            return True, CapabilityLevel.LEVEL_3_DESTRUCTIVE, True, f"Destructive action '{tool.name}' requires explicit human approval."

        if level == CapabilityLevel.LEVEL_2_SENSITIVE and tool.requires_approval:
            return True, CapabilityLevel.LEVEL_2_SENSITIVE, True, f"Sensitive action '{tool.name}' requires human approval."

        # Level 0 (Read) and Level 1 (Safe Write) are authorized directly
        return True, level, False, f"Action '{tool.name}' authorized under capability level {level.name}."

    def evaluate_action(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        user_id: str = "",
        session_authenticated: bool = True
    ):
        """
        Structured evaluation helper accepting tool_name directly.
        Returns PolicyEvaluationResult dataclass.
        """
        from app.runtime.tool_registry import tool_registry
        from dataclasses import dataclass

        @dataclass
        class PolicyEvaluationResult:
            allowed: bool
            requires_approval: bool
            capability_level: CapabilityLevel
            reason: str
            approval_request: Optional[Any] = None

        tool_def = tool_registry.get_tool(tool_name)
        if not tool_def:
            # Fallback tool definition
            tool_def = ToolDefinition(
                name=tool_name,
                description="Dynamic tool",
                capability_level=CapabilityLevel.LEVEL_1_SAFE_WRITE,
                execute_fn=lambda **kw: None
            )

        is_allowed, cap_level, req_approval, reason = self.evaluate_execution(
            tool=tool_def,
            tool_input=tool_input,
            user_id=user_id
        )

        return PolicyEvaluationResult(
            allowed=is_allowed and not req_approval,
            requires_approval=req_approval,
            capability_level=cap_level,
            reason=reason,
            approval_request={"tool_name": tool_name, "tool_input": tool_input, "reason": reason} if req_approval else None
        )


# Singleton instance
policy_engine = PolicyEngine()
