"""
Event Schemas and Data Models for Nexus AI Event-Driven Architecture.
"""
from enum import Enum
import time
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EventType(str, Enum):
    # Task Lifecycle Events
    TASK_CREATED = "TASK_CREATED"
    TASK_CLASSIFIED = "TASK_CLASSIFIED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"

    # Action Lifecycle Events
    ACTION_REQUESTED = "ACTION_REQUESTED"
    ACTION_APPROVED = "ACTION_APPROVED"
    ACTION_BLOCKED = "ACTION_BLOCKED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_FAILED = "ACTION_FAILED"

    # Security Events
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"

    # Verification Events
    VERIFICATION_PASSED = "VERIFICATION_PASSED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"

    # Vision Events
    SCREEN_CAPTURED = "SCREEN_CAPTURED"
    SCREEN_VERIFIED = "SCREEN_VERIFIED"

    # Recovery / Self-Healing Events
    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_SUCCEEDED = "RECOVERY_SUCCEEDED"
    RECOVERY_FAILED = "RECOVERY_FAILED"

    # System & Telemetry Events
    SYSTEM_HEALTH_CHECK = "SYSTEM_HEALTH_CHECK"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"


class NexusEvent(BaseModel):
    """
    Standard event envelope passed through Redis Streams.
    """
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    task_id: str
    user_id: str = "system"
    timestamp: float = Field(default_factory=time.time)
    source_agent: str = "unknown"
    payload: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value if isinstance(self.event_type, EventType) else str(self.event_type),
            "task_id": self.task_id,
            "user_id": self.user_id,
            "timestamp": str(self.timestamp),
            "source_agent": self.source_agent,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NexusEvent":
        import json
        payload = data.get("payload", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {"raw": payload}

        raw_type = data.get("event_type", EventType.TASK_CREATED)
        try:
            event_type = EventType(raw_type)
        except ValueError:
            event_type = EventType.TASK_CREATED

        return cls(
            event_id=str(data.get("event_id", str(uuid.uuid4()))),
            event_type=event_type,
            task_id=str(data.get("task_id", "")),
            user_id=str(data.get("user_id", "system")),
            timestamp=float(data.get("timestamp", time.time())),
            source_agent=str(data.get("source_agent", "unknown")),
            payload=payload,
        )


class TaskCreatedPayload(BaseModel):
    command: str
    raw_text: Optional[str] = None


class TaskClassifiedPayload(BaseModel):
    intent: str
    domain: str  # "pc_tools", "browser", "coding", "security", "chat"
    subtasks: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = 1.0


class ActionRequestedPayload(BaseModel):
    action: str
    tool_input: Dict[str, Any] = Field(default_factory=dict)
    domain: str = "pc_tools"
    subtask_index: int = 0
    requires_approval: bool = False


class ActionCompletedPayload(BaseModel):
    action: str
    result: Any
    success: bool = True
    duration_ms: float = 0.0
    subtask_index: int = 0


class ActionFailedPayload(BaseModel):
    action: str
    error: str
    subtask_index: int = 0
    traceback: Optional[str] = None


class VerificationResultPayload(BaseModel):
    verified: bool
    detail: str
    screenshot_path: Optional[str] = None


class RecoveryPayload(BaseModel):
    strategy: str
    attempt: int
    repaired_successfully: bool = False
    repair_note: Optional[str] = None
