"""
Human Handoff Models — State machine enums, triggers, and checkpoint data structures.
"""
import uuid
import time
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class HandoffState(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    WAITING_FOR_HUMAN = "WAITING_FOR_HUMAN"
    HUMAN_ACTIVE = "HUMAN_ACTIVE"
    VERIFYING_HANDOFF = "VERIFYING_HANDOFF"
    RESUMED = "RESUMED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class HandoffTrigger(str, Enum):
    OTP_REQUIRED = "OTP_REQUIRED"
    CAPTCHA_DETECTED = "CAPTCHA_DETECTED"
    SENSITIVE_ACTION = "SENSITIVE_ACTION"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    STUCK_LOOP = "STUCK_LOOP"
    MANUAL_REQUEST = "MANUAL_REQUEST"


class HandoffCheckpoint(BaseModel):
    """Snapshot of agent/browser/system state when handoff occurs."""
    checkpoint_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    task_id: str
    user_id: str
    trigger: HandoffTrigger
    reason: str
    state: HandoffState = HandoffState.WAITING_FOR_HUMAN
    created_at: float = Field(default_factory=time.time)
    timeout_seconds: int = 600
    
    # Context snapshots
    target_url: Optional[str] = None
    initial_url: Optional[str] = None
    expected_url_change: Optional[str] = None
    expected_dom_elements: List[str] = Field(default_factory=list)
    screenshot_path: Optional[str] = None
    
    # State recovery payload
    agent_name: str
    subtask_index: int = 0
    subtask_data: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    # Resolution details
    human_input: Optional[str] = None
    resolved_at: Optional[float] = None
    verification_passed: bool = False
    verification_notes: Optional[str] = None
