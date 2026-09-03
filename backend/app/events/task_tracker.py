"""
Task State Machine and Lifecycle Tracker for Event-Driven Tasks.
"""
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.events.event_bus import RedisEventBus, event_bus
from app.events.event_models import EventType, NexusEvent

logger = logging.getLogger(__name__)


class TaskTracker:
    """
    Tracks state transitions and completion status for asynchronous event-driven tasks.
    """

    def __init__(self, bus: Optional[RedisEventBus] = None):
        self.bus = bus or event_bus
        self._states: Dict[str, Dict[str, Any]] = {}
        self._completion_events: Dict[str, asyncio.Event] = {}
        self._lock = asyncio.Lock()

    async def register_task(self, task_id: str, user_id: str, command: str) -> Dict[str, Any]:
        """Initialize a new task lifecycle record."""
        async with self._lock:
            state = {
                "task_id": task_id,
                "user_id": user_id,
                "command": command,
                "status": "CREATED",
                "intent": None,
                "domain": None,
                "subtasks": [],
                "completed_actions": [],
                "failed_actions": [],
                "repairs": [],
                "final_output": None,
                "success": None,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self._states[task_id] = state
            self._completion_events[task_id] = asyncio.Event()
            return state

    async def update_task_from_event(self, event: NexusEvent):
        """Update task state based on an incoming lifecycle event."""
        task_id = event.task_id
        async with self._lock:
            if task_id not in self._states:
                self._states[task_id] = {
                    "task_id": task_id,
                    "user_id": event.user_id,
                    "status": "CREATED",
                    "created_at": event.timestamp,
                    "completed_actions": [],
                    "failed_actions": [],
                    "repairs": [],
                }
                if task_id not in self._completion_events:
                    self._completion_events[task_id] = asyncio.Event()

            task = self._states[task_id]
            task["updated_at"] = event.timestamp

            et = event.event_type
            if et == EventType.TASK_CLASSIFIED:
                task["status"] = "CLASSIFIED"
                task["intent"] = event.payload.get("intent")
                task["domain"] = event.payload.get("domain")
                task["subtasks"] = event.payload.get("subtasks", [])

            elif et == EventType.ACTION_REQUESTED:
                task["status"] = "EXECUTING"

            elif et == EventType.ACTION_COMPLETED:
                task["completed_actions"].append(event.payload)

            elif et == EventType.ACTION_FAILED:
                task["failed_actions"].append(event.payload)

            elif et == EventType.RECOVERY_SUCCEEDED:
                task["repairs"].append(event.payload)

            elif et == EventType.TASK_COMPLETED:
                task["status"] = "COMPLETED"
                task["success"] = True
                task["final_output"] = event.payload.get("final_output", "Task completed.")
                if task_id in self._completion_events:
                    self._completion_events[task_id].set()

            elif et in (EventType.TASK_FAILED, EventType.ACTION_BLOCKED):
                task["status"] = "FAILED"
                task["success"] = False
                task["final_output"] = event.payload.get("error", "Task execution failed or blocked.")
                if task_id in self._completion_events:
                    self._completion_events[task_id].set()

    async def get_task_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Fetch current state snapshot of a task."""
        async with self._lock:
            return self._states.get(task_id)

    async def wait_for_completion(self, task_id: str, timeout: float = 60.0) -> Dict[str, Any]:
        """Block until the task emits TASK_COMPLETED or TASK_FAILED."""
        evt = self._completion_events.get(task_id)
        if not evt:
            async with self._lock:
                evt = asyncio.Event()
                self._completion_events[task_id] = evt

        try:
            await asyncio.wait_for(evt.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"[TaskTracker] Task {task_id} timed out after {timeout}s")
            return {
                "task_id": task_id,
                "status": "TIMEOUT",
                "success": False,
                "final_output": f"Task execution timed out after {timeout} seconds.",
            }

        state = await self.get_task_state(task_id)
        return state or {
            "task_id": task_id,
            "status": "UNKNOWN",
            "success": False,
            "final_output": "Task completed with no state recorded.",
        }

    async def get_task_timeline(self, task_id: str) -> List[Dict[str, Any]]:
        """Retrieve full event timeline for dashboard visualisation."""
        events = await self.bus.get_task_timeline(task_id)
        return [e.to_dict() for e in events]


# Global singleton instance
task_tracker = TaskTracker()
