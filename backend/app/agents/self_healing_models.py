"""
Data models and contracts for the Nexus AI Self-Healing Agent Framework.
"""
import uuid
import time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ErrorCategory(str, Enum):
    DEPENDENCY_ERROR = "dependency_error"      # ModuleNotFoundError, ImportError, missing npm pkg
    PORT_CONFLICT = "port_conflict"            # Address already in use, EADDRINUSE, WinError 10048
    APPLICATION_CRASH = "application_crash"    # Process terminated unexpectedly, Chrome crash
    NETWORK_ERROR = "network_error"            # ConnectionRefused, Timeout, DNS failure
    FILE_ERROR = "file_error"                  # FileNotFoundError, Path missing
    PERMISSION_ERROR = "permission_error"      # PermissionError, Access is denied
    SYNTAX_LOGIC_ERROR = "syntax_logic_error"  # SyntaxError, IndentationError, TypeError
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    LOW = "low"            # e.g., pip install <safe_pkg>, restart browser, check net
    MEDIUM = "medium"      # e.g., kill owned stale process on dev port, clear temp cache
    HIGH = "high"          # e.g., delete file, kill external PID, modify system config
    CRITICAL = "critical"  # e.g., tamper with Defender, modify system registry (BLOCKED)


class ErrorDiagnosis(BaseModel):
    """Structured diagnosis of an execution failure."""
    category: ErrorCategory
    root_cause: str
    missing_entity: Optional[str] = None  # e.g. "fastapi", "8000", "D:\path\file.txt"
    confidence: float = Field(default=0.90, ge=0.0, le=1.0)
    raw_stderr: str = ""
    exit_code: Optional[int] = None
    diagnosed_by: str = "deterministic_parser"  # "deterministic_parser" or "llm_reasoning"
    timestamp: float = Field(default_factory=time.time)


class RecoveryAction(BaseModel):
    """Specific proposed remediation action."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    strategy_name: str
    tool_name: str                        # e.g. "run_shell_command", "kill_process", "open_application"
    arguments: Dict[str, Any] = Field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    description: str = ""
    verification_type: str = ""           # "package_installed", "port_listening", "http_health", "process_alive"
    verification_args: Dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False


class RepairOutcome(BaseModel):
    """Result of attempting a recovery action."""
    success: bool
    action_executed: RecoveryAction
    verification_passed: bool
    verification_detail: str = ""
    attempt: int = 1
    latency_ms: int = 0
    error_message: Optional[str] = None
