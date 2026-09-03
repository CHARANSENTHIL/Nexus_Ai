"""
tests_e2e/utils.py - E2E Test Helpers, Mock Harnesses, Pydantic Models, and Assertion Engine

Provides zero-paid-API, offline, deterministic mock harnesses for Nexus AI testing.
"""

import time
import uuid
import math
from typing import Dict, Any, List, Optional, Union
from pydantic import BaseModel, Field


# ============================================================================
# 1. Pydantic v2 Models (Interface Contracts R1-R8)
# ============================================================================

class TaskRequest(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str
    user_id: str
    context: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = Field(default_factory=time.time)


class SubtaskItem(BaseModel):
    subtask_id: str
    agent: str  # "SystemAgent", "ApplicationAgent", "FileAgent", "PlannerAgent"
    action: str
    params: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    status: str = "PENDING"  # "PENDING", "IN_PROGRESS", "COMPLETED", "FAILED"


class SubtaskExecutionPlan(BaseModel):
    task_id: str
    goal: str
    subtasks: List[SubtaskItem] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)


class DigitalTwinState(BaseModel):
    cpu_percent: float = Field(..., ge=0.0, le=100.0)
    ram_percent: float = Field(..., ge=0.0, le=100.0)
    disk_percent: float = Field(..., ge=0.0, le=100.0)
    battery_percent: float = Field(..., ge=0.0, le=100.0)
    is_charging: bool = True
    processes: List[str] = Field(default_factory=list)
    active_windows: List[str] = Field(default_factory=list)
    network_usage_mbps: float = 0.0
    clipboard_text: Optional[str] = ""
    last_updated: float = Field(default_factory=time.time)


class MemoryItem(BaseModel):
    item_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    key: str
    value: Any
    category: str = "preference"  # "preference", "workspace", "history"
    score: float = 1.0
    created_at: float = Field(default_factory=time.time)


class HealthAlert(BaseModel):
    alert_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metric: str
    severity: str  # "INFO", "WARNING", "CRITICAL", "URGENT_CRITICAL"
    projected_fill_days: float
    message: str
    timestamp: float = Field(default_factory=time.time)


class AuditLog(BaseModel):
    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    user_id: str
    action_type: str
    target: str
    outcome: str  # "PENDING", "APPROVED", "REJECTED", "EXPIRED"
    details: Dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# 2. Standalone Mock Harnesses
# ============================================================================

class MockOllamaServer:
    """Simulates local Llama 3 LLM completions deterministically."""

    def __init__(self, port: int = 11434):
        self.port = port
        self.request_history: List[Dict[str, Any]] = []
        self.prompt_routes: Dict[str, Any] = {}

    def register_prompt_handler(self, keyword: str, response_data: Any) -> None:
        self.prompt_routes[keyword.lower()] = response_data

    def generate_completion(self, prompt: str, model: str = "llama3") -> Dict[str, Any]:
        self.request_history.append({"prompt": prompt, "model": model, "timestamp": time.time()})
        prompt_lower = prompt.lower()

        for kw, resp in self.prompt_routes.items():
            if kw in prompt_lower:
                return {"status": "success", "response": resp, "model": model}

        # Default fallback decomposition plan if prompt specifies coding or general goal
        default_subtasks = [
            SubtaskItem(subtask_id="st_1", agent="SystemAgent", action="check_system_resources"),
            SubtaskItem(subtask_id="st_2", agent="ApplicationAgent", action="launch_ide", params={"app": "VSCode"}, depends_on=["st_1"]),
            SubtaskItem(subtask_id="st_3", agent="SystemAgent", action="start_docker_containers", depends_on=["st_1"]),
            SubtaskItem(subtask_id="st_4", agent="ApplicationAgent", action="open_browser", params={"url": "http://localhost:8000/docs"}, depends_on=["st_2"]),
            SubtaskItem(subtask_id="st_5", agent="FileAgent", action="organize_directory", params={"path": "C:/Downloads"}, depends_on=["st_3", "st_4"]),
        ]
        return {"status": "success", "response": [st.model_dump() for st in default_subtasks], "model": model}


class MockTelegramHarness:
    """Simulates Telegram Bot API, user authorization, and notification delivery."""

    def __init__(self):
        self.whitelisted_user_ids: set[str] = {"123456789", "user_admin", "tg_user_1"}
        self.sent_messages: List[Dict[str, Any]] = []
        self.inline_callbacks: List[Dict[str, Any]] = []

    def is_authorized(self, user_id: str) -> bool:
        return user_id in self.whitelisted_user_ids

    def simulate_user_message(self, user_id: str, message_text: str) -> Dict[str, Any]:
        if not self.is_authorized(user_id):
            return {"status_code": 403, "error": "Unauthorized user ID", "delivered": False}
        
        return {
            "status_code": 200,
            "user_id": user_id,
            "message_text": message_text,
            "timestamp": time.time(),
            "delivered": True
        }

    def send_notification(self, user_id: str, text: str, inline_keyboard: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        msg = {
            "message_id": str(uuid.uuid4()),
            "user_id": user_id,
            "text": text,
            "inline_keyboard": inline_keyboard,
            "timestamp": time.time()
        }
        self.sent_messages.append(msg)
        return msg

    def simulate_inline_button_click(self, user_id: str, callback_data: str, message_id: str) -> Dict[str, Any]:
        event = {
            "user_id": user_id,
            "callback_data": callback_data,
            "message_id": message_id,
            "timestamp": time.time()
        }
        self.inline_callbacks.append(event)
        return event

    def get_latest_message(self) -> Optional[Dict[str, Any]]:
        return self.sent_messages[-1] if self.sent_messages else None


class MockN8nHarness:
    """Simulates self-hosted n8n workflow engine triggering AI Planner REST webhooks."""
    def __init__(self, backend_base_url: str = "http://localhost:8000"):
        self.backend_url = backend_base_url
        self.executed_workflows: List[Dict[str, Any]] = []

    def trigger_workflow_execution(self, workflow_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        record = {
            "execution_id": str(uuid.uuid4()),
            "workflow_name": workflow_name,
            "payload": payload,
            "status": "SUCCESS",
            "timestamp": time.time()
        }
        self.executed_workflows.append(record)
        return record


class DigitalTwinSimulator:
    """In-memory Digital Twin state manager and Health Monitor alert engine."""

    def __init__(self):
        self.state = DigitalTwinState(
            cpu_percent=15.5,
            ram_percent=42.0,
            disk_percent=55.0,
            battery_percent=88.0,
            is_charging=True,
            processes=["explorer.exe", "svchost.exe", "code.exe", "python.exe"],
            active_windows=["Visual Studio Code", "Terminal"],
            network_usage_mbps=1.2,
            clipboard_text="https://github.com/nexus-ai/nexus_ai"
        )
        self.disk_history: List[tuple[float, float]] = []  # (timestamp, disk_percent)

    def update_state(self, **kwargs) -> DigitalTwinState:
        current_data = self.state.model_dump()
        current_data.update(kwargs)
        current_data["last_updated"] = time.time()
        self.state = DigitalTwinState(**current_data)
        self.disk_history.append((self.state.last_updated, self.state.disk_percent))
        return self.state

    def get_state(self) -> DigitalTwinState:
        return self.state

    def calculate_health_alerts(self, growth_rate_per_day: float = 2.5) -> List[HealthAlert]:
        alerts = []
        # Calculate days until disk full
        remaining_percent = 100.0 - self.state.disk_percent
        if growth_rate_per_day > 0:
            days_to_full = remaining_percent / growth_rate_per_day
        else:
            days_to_full = 999.0

        if self.state.disk_percent >= 95.0 or days_to_full < 3:
            alerts.append(HealthAlert(
                metric="disk_usage",
                severity="URGENT_CRITICAL",
                projected_fill_days=round(days_to_full, 1),
                message=f"Disk critical! {self.state.disk_percent}% full. Projected full in {round(days_to_full, 1)} days."
            ))
        elif self.state.disk_percent >= 80.0 or days_to_full < 14:
            alerts.append(HealthAlert(
                metric="disk_usage",
                severity="CRITICAL",
                projected_fill_days=round(days_to_full, 1),
                message=f"Proactive alert: Disk usage is {self.state.disk_percent}%. Projected full in {round(days_to_full, 1)} days."
            ))

        if self.state.battery_percent <= 5.0 and not self.state.is_charging:
            alerts.append(HealthAlert(
                metric="battery",
                severity="WARNING",
                projected_fill_days=0.0,
                message=f"Battery critically low: {self.state.battery_percent}% remaining."
            ))
        return alerts


class MockMemoryStore:
    """In-memory ChromaDB vector store simulation with session & score filtering."""

    def __init__(self):
        self.items: List[MemoryItem] = []

    def save_item(self, user_id: str, key: str, value: Any, category: str = "preference") -> MemoryItem:
        # Overwrite existing if user_id and key match
        for item in self.items:
            if item.user_id == user_id and item.key == key:
                item.value = value
                item.created_at = time.time()
                return item

        item = MemoryItem(user_id=user_id, key=key, value=value, category=category)
        self.items.append(item)
        return item

    def search_semantic(self, user_id: str, query: str, top_k: int = 3) -> List[MemoryItem]:
        user_items = [i for i in self.items if i.user_id == user_id]
        query_words = set(query.lower().split())
        
        scored_items = []
        for item in user_items:
            item_text = f"{item.key} {str(item.value)} {item.category}".lower()
            overlap = sum(1 for word in query_words if word in item_text)
            score = round(0.5 + (0.5 * (overlap / max(1, len(query_words)))), 2)
            scored_item = item.model_copy()
            scored_item.score = score
            scored_items.append(scored_item)

        scored_items.sort(key=lambda x: x.score, reverse=True)
        return scored_items[:top_k]

    def get_by_key(self, user_id: str, key: str) -> Optional[MemoryItem]:
        for item in self.items:
            if item.user_id == user_id and item.key == key:
                return item
        return None


class MockApprovalCenter:
    """Manages dangerous actions, approval state machine, and audit logs."""

    DANGEROUS_ACTIONS = {"file_delete", "shutdown", "process_kill", "registry_edit"}

    def __init__(self):
        self.pending_approvals: Dict[str, Dict[str, Any]] = {}
        self.audit_logs: List[AuditLog] = []

    def is_dangerous(self, action_type: str) -> bool:
        return action_type in self.DANGEROUS_ACTIONS

    def request_approval(self, user_id: str, action_type: str, target: str, details: Dict[str, Any]) -> Dict[str, Any]:
        approval_id = str(uuid.uuid4())
        record = {
            "approval_id": approval_id,
            "user_id": user_id,
            "action_type": action_type,
            "target": target,
            "details": details,
            "status": "PENDING",
            "created_at": time.time(),
            "expires_at": time.time() + 600  # 10 mins
        }
        self.pending_approvals[approval_id] = record

        # Add initial pending audit log
        log = AuditLog(
            user_id=user_id,
            action_type=action_type,
            target=target,
            outcome="PENDING",
            details=details
        )
        self.audit_logs.append(log)
        return record

    def resolve_approval(self, approval_id: str, user_id: str, outcome: str) -> Dict[str, Any]:
        if approval_id not in self.pending_approvals:
            raise KeyError(f"Approval ID {approval_id} not found")

        record = self.pending_approvals[approval_id]
        if time.time() > record["expires_at"]:
            record["status"] = "EXPIRED"
            outcome = "EXPIRED"
        else:
            record["status"] = outcome

        # Update audit log
        log = AuditLog(
            user_id=user_id,
            action_type=record["action_type"],
            target=record["target"],
            outcome=outcome,
            details=record["details"]
        )
        self.audit_logs.append(log)
        return record


class MockSSEServerStream:
    """Simulates real-time SSE stream events for Dashboard."""

    def __init__(self):
        self.subscribers: int = 0
        self.events: List[Dict[str, Any]] = []

    def connect(self) -> str:
        self.subscribers += 1
        client_id = str(uuid.uuid4())
        return client_id

    def disconnect(self, client_id: str) -> None:
        if self.subscribers > 0:
            self.subscribers -= 1

    def emit_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "event": event_type,
            "data": data,
            "timestamp": time.time()
        }
        self.events.append(payload)
        return payload


# ============================================================================
# 3. Assertion Helpers
# ============================================================================

class E2EAssertionHelpers:
    """Reusable opaque-box assertion methods."""

    @staticmethod
    def assert_task_plan_valid(plan: Union[SubtaskExecutionPlan, List[Dict[str, Any]]]) -> None:
        if isinstance(plan, SubtaskExecutionPlan):
            subtasks = plan.subtasks
            assert len(subtasks) >= 5, f"Expected ≥5 subtasks in plan, got {len(subtasks)}"
            for st in subtasks:
                assert st.subtask_id, "Subtask must have subtask_id"
                assert st.agent in {"SystemAgent", "ApplicationAgent", "FileAgent", "PlannerAgent"}, f"Invalid agent {st.agent}"
                assert st.action, "Subtask must specify action"
        elif isinstance(plan, list):
            assert len(plan) >= 5, f"Expected ≥5 subtasks in list, got {len(plan)}"
            for st in plan:
                assert "subtask_id" in st or "id" in st
                assert "agent" in st or "action" in st

    @staticmethod
    def assert_jwt_unauthorized(status_code: int, detail: Dict[str, Any]) -> None:
        assert status_code == 401, f"Expected HTTP 401 Unauthorized, got {status_code}"
        assert "detail" in detail or "error" in detail

    @staticmethod
    def assert_audit_logged(audit_logs: List[AuditLog], action_type: str, expected_outcome: str) -> None:
        matched = [log for log in audit_logs if log.action_type == action_type and log.outcome == expected_outcome]
        assert len(matched) > 0, f"Expected audit log entry for action {action_type} with outcome {expected_outcome}"

    @staticmethod
    def assert_sse_event_emitted(events: List[Dict[str, Any]], event_type: str) -> None:
        matched = [e for e in events if e.get("event") == event_type]
        assert len(matched) > 0, f"Expected SSE event of type {event_type}"

    @staticmethod
    def assert_digital_twin_valid(state: DigitalTwinState) -> None:
        assert 0.0 <= state.cpu_percent <= 100.0
        assert 0.0 <= state.ram_percent <= 100.0
        assert 0.0 <= state.disk_percent <= 100.0
        assert 0.0 <= state.battery_percent <= 100.0
        assert isinstance(state.processes, list)

    @staticmethod
    def assert_memory_recalled(memories: List[MemoryItem], key: str, expected_value: Any) -> None:
        matched = [m for m in memories if m.key == key and m.value == expected_value]
        assert len(matched) > 0, f"Expected memory item for key {key} with value {expected_value}"
