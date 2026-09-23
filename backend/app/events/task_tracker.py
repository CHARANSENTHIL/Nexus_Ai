"""
Task State Machine and Lifecycle Tracker for Event-Driven Tasks.
Tracks multi-subtask completion and aggregates results before notifying callers.
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
    
    Key behaviour for multi-subtask tasks:
      - On TASK_CLASSIFIED:  stores the expected subtask count.
      - On ACTION_COMPLETED / ACTION_FAILED:  increments the finished counter and
        records each result.
      - On TASK_COMPLETED:  only fires the asyncio completion Event once the
        finished counter >= expected subtask count.  This prevents the Telegram
        bot from showing "Task Completed" after the first worker finishes.
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
                "subtask_count": 0,          # expected total
                "finished_count": 0,          # completed + failed
                "completed_actions": [],
                "failed_actions": [],
                "repairs": [],
                "aggregated_results": [],     # ordered result strings for final output
                "final_output": None,
                "success": None,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self._states[task_id] = state
            self._completion_events[task_id] = asyncio.Event()
            return state

    def _check_all_subtasks_done(self, task: Dict[str, Any]) -> bool:
        """Return True when every subtask has reported back."""
        expected = task.get("subtask_count", 0)
        if expected <= 0:
            return True  # single-action tasks complete immediately
        return task.get("finished_count", 0) >= expected

    def _build_aggregated_output(self, task: Dict[str, Any]) -> str:
        """Combine all per-subtask results into a single human-readable summary."""
        parts = []
        for idx, result in enumerate(task.get("aggregated_results", []), 1):
            parts.append(f"{result}")
        
        failed = task.get("failed_actions", [])
        for f in failed:
            parts.append(f"❌ {f.get('action', 'unknown')} failed: {f.get('error', 'Unknown error')}")
        
        return "\n\n".join(parts) if parts else "Task completed."

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
                    "subtask_count": 0,
                    "finished_count": 0,
                    "completed_actions": [],
                    "failed_actions": [],
                    "repairs": [],
                    "aggregated_results": [],
                }
                if task_id not in self._completion_events:
                    self._completion_events[task_id] = asyncio.Event()

            task = self._states[task_id]
            task["updated_at"] = event.timestamp

            et = event.event_type

            # ── TASK_CLASSIFIED: learn how many subtasks to expect ──
            if et == EventType.TASK_CLASSIFIED:
                task["status"] = "CLASSIFIED"
                task["intent"] = event.payload.get("intent")
                task["domain"] = event.payload.get("domain")
                subtasks = event.payload.get("subtasks", [])
                task["subtasks"] = subtasks
                task["subtask_count"] = len(subtasks)
                logger.info(f"[TaskTracker] Task {task_id} classified with {len(subtasks)} subtask(s)")

            elif et == EventType.ACTION_REQUESTED:
                task["status"] = "EXECUTING"

            # ── ACTION_COMPLETED: record result, bump counter ──
            elif et == EventType.ACTION_COMPLETED:
                task["completed_actions"].append(event.payload)
                task["finished_count"] = task.get("finished_count", 0) + 1
                
                # Build a human-readable result line
                action_name = event.payload.get("action", "")
                result_text = event.payload.get("result", "Done")
                if isinstance(result_text, str) and len(result_text) > 500:
                    result_text = result_text[:500] + "..."
                task["aggregated_results"].append(f"🌐 {action_name}: {result_text}")
                
                logger.info(
                    f"[TaskTracker] Task {task_id}: subtask {task['finished_count']}/{task.get('subtask_count', '?')} completed ({action_name})"
                )

            # ── ACTION_FAILED: record failure, bump counter ──
            elif et == EventType.ACTION_FAILED:
                task["failed_actions"].append(event.payload)
                task["finished_count"] = task.get("finished_count", 0) + 1
                logger.info(
                    f"[TaskTracker] Task {task_id}: subtask {task['finished_count']}/{task.get('subtask_count', '?')} FAILED ({event.payload.get('action', '')})"
                )

            elif et == EventType.RECOVERY_SUCCEEDED:
                task["repairs"].append(event.payload)

            # ── TASK_COMPLETED: only fire when ALL subtasks done ──
            elif et == EventType.TASK_COMPLETED:
                if self._check_all_subtasks_done(task):
                    task["status"] = "COMPLETED"
                    task["success"] = len(task.get("failed_actions", [])) == 0
                    # For multi-subtask: use aggregated output; for single/zero: use event payload
                    aggregated = self._build_aggregated_output(task)
                    if aggregated and aggregated != "Task completed.":
                        task["final_output"] = aggregated
                    else:
                        task["final_output"] = event.payload.get("final_output", "Task completed.")
                    if task_id in self._completion_events:
                        self._completion_events[task_id].set()
                    logger.info(f"[TaskTracker] ✅ Task {task_id} FULLY COMPLETED ({task['finished_count']} subtasks)")
                else:
                    # Not all subtasks done yet — don't signal completion
                    logger.info(
                        f"[TaskTracker] Task {task_id}: TASK_COMPLETED received but only "
                        f"{task.get('finished_count', 0)}/{task.get('subtask_count', 0)} subtasks done — waiting..."
                    )

            elif et in (EventType.TASK_FAILED, EventType.ACTION_BLOCKED):
                task["status"] = "BLOCKED" if et == EventType.ACTION_BLOCKED else "FAILED"
                task["success"] = False
                task["final_output"] = event.payload.get("reason") or event.payload.get("error") or "Task execution failed or blocked."
                if task_id in self._completion_events:
                    self._completion_events[task_id].set()

    async def get_task_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Fetch current state snapshot of a task."""
        async with self._lock:
            return self._states.get(task_id)

    async def wait_for_completion(self, task_id: str, timeout: float = 120.0) -> Dict[str, Any]:
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
            # Even on timeout, return whatever partial results we have
            state = await self.get_task_state(task_id)
            if state:
                partial = self._build_aggregated_output(state)
                return {
                    "task_id": task_id,
                    "status": "TIMEOUT",
                    "success": False,
                    "final_output": f"⏱️ Task timed out after {timeout}s. Partial results:\n\n{partial}" if partial != "Task completed." else f"Task execution timed out after {timeout} seconds.",
                }
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
