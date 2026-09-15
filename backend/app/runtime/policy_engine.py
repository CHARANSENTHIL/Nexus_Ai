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
    r"disable.*antivirus",
    r"advfirewall.*state\s+off",
    r"reg\s+(delete|add)\s+hklm",
    r"format\s+[c-z]:",
    r"rmdir\s+/s\s+/q\s+c:\\windows",
    r"del\s+/f\s+/s\s+/q\s+c:\\windows",
    r"remove-item\s+-recurse\s+c:\\windows",
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


# Singleton instance
policy_engine = PolicyEngine()
