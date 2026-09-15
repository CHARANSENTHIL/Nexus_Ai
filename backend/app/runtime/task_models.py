"""
Task Models — Data structures, capability levels, state enums, and schemas for Nexus Runtime.
"""
import time
import uuid
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional, Callable
from pydantic import BaseModel, Field


class TaskState(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    HUMAN_COMPLETED = "HUMAN_COMPLETED"
    RETRYING = "RETRYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PAUSED = "PAUSED"


class CapabilityLevel(IntEnum):
    """
    Formal capability security tiers.
    Level 0: Read-only (no state change)
    Level 1: Safe write (local non-destructive files/apps)
    Level 2: Sensitive (email, web login, config changes)
    Level 3: Destructive (delete files, kill processes, arbitrary shell)
    Level 4: Privileged (admin ops, security disable, raw credential access)
    """
    LEVEL_0_READ = 0
    LEVEL_1_SAFE_WRITE = 1
    LEVEL_2_SENSITIVE = 2
    LEVEL_3_DESTRUCTIVE = 3
    LEVEL_4_PRIVILEGED = 4


class SubtaskNode(BaseModel):
    subtask_id: str = Field(default_factory=lambda: f"subtask_{str(uuid.uuid4())[:8]}")
    title: str
    description: str
    tool_name: str
    tool_input: Dict[str, Any] = Field(default_factory=dict)
    assigned_agent: str = "general"
    capability_level: CapabilityLevel = CapabilityLevel.LEVEL_0_READ
    requires_approval: bool = False
    dependencies: List[str] = Field(default_factory=list)
    state: TaskState = TaskState.CREATED
    result: Optional[Any] = None
    error: Optional[str] = None
    verification_passed: bool = False
    verification_notes: Optional[str] = None
    execution_duration_ms: float = 0.0
    attempts: int = 0


class TaskRecord(BaseModel):
    """Durable task representation persisted in SQLite/Postgres."""
    task_id: str = Field(default_factory=lambda: f"task_{str(uuid.uuid4())[:12]}")
    user_id: str
    goal: str
    state: TaskState = TaskState.CREATED
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    completed_at: Optional[float] = None
    subtasks: List[SubtaskNode] = Field(default_factory=list)
    current_subtask_index: int = 0
    total_steps: int = 0
    completed_steps_count: int = 0
    retry_count: int = 0
    max_retries: int = 3
    final_output: Optional[str] = None
    error_summary: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    passed: bool
    strategy_used: str
    details: str
    metrics: Dict[str, Any] = Field(default_factory=dict)


class ToolDefinition:
    """Formal definition of an executable tool."""
    def __init__(
        self,
        name: str,
        description: str,
        capability_level: CapabilityLevel,
        execute_fn: Callable,
        input_schema: Optional[Dict[str, Any]] = None,
        output_schema: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 60,
        requires_approval: bool = False,
        verification_strategy: Optional[str] = None,
        rollback_fn: Optional[Callable] = None,
    ):
        self.name = name
        self.description = description
        self.capability_level = capability_level
        self.execute_fn = execute_fn
        self.input_schema = input_schema or {}
        self.output_schema = output_schema or {}
        self.timeout_seconds = timeout_seconds
        self.requires_approval = requires_approval
        self.verification_strategy = verification_strategy
        self.rollback_fn = rollback_fn
