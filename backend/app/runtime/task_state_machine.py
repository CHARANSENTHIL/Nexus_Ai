"""
Task State Machine — Durable SQLite-backed state machine for all Nexus AI operations.
Persists task graphs, state transitions, subtask execution logs, and resumption checkpoints.
"""
import os
import json
import time
import asyncio
import sqlite3
import contextlib
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.runtime.task_models import (
    TaskState,
    TaskRecord,
    SubtaskNode,
)

logger = logging.getLogger(__name__)

DB_DIR = Path(os.path.expanduser("~")) / ".nexus_ai"
DB_PATH = DB_DIR / "tasks.db"


class TaskStateMachine:
    """
    Manages durable state transitions and database checkpoints for tasks.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return contextlib.closing(conn)

    def _init_db(self):
        """Create tasks table and indexes if not exists."""
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    current_subtask_index INTEGER DEFAULT 0,
                    total_steps INTEGER DEFAULT 0,
                    completed_steps_count INTEGER DEFAULT 0,
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    final_output TEXT,
                    error_summary TEXT,
                    subtasks_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id)")
            conn.commit()

    def create_task(self, goal: str, user_id: str, metadata: Optional[Dict[str, Any]] = None) -> TaskRecord:
        """Create a new task record in CREATED state."""
        task = TaskRecord(
            user_id=user_id,
            goal=goal,
            state=TaskState.CREATED,
            metadata=metadata or {},
        )
        self.save_task(task)
        logger.info(f"[StateMachine] Created durable task {task.task_id} for user {user_id}: '{goal[:50]}'")
        return task

    def attach_plan(self, task: TaskRecord, subtasks: List[SubtaskNode]):
        """Attach planned subtasks to task record and persist to SQLite."""
        task.subtasks = subtasks
        task.total_steps = len(subtasks)
        self.save_task(task)
        logger.info(f"[StateMachine] Attached plan ({len(subtasks)} steps) to task {task.task_id}")

    def save_task(self, task: TaskRecord):
        """Persist or update task record atomically."""
        task.updated_at = time.time()
        subtasks_json = json.dumps([s.model_dump() for s in task.subtasks])
        metadata_json = json.dumps(task.metadata)

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO tasks (
                    task_id, user_id, goal, state, created_at, updated_at,
                    completed_at, current_subtask_index, total_steps,
                    completed_steps_count, retry_count, max_retries,
                    final_output, error_summary, subtasks_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    state = excluded.state,
                    updated_at = excluded.updated_at,
                    completed_at = excluded.completed_at,
                    current_subtask_index = excluded.current_subtask_index,
                    total_steps = excluded.total_steps,
                    completed_steps_count = excluded.completed_steps_count,
                    retry_count = excluded.retry_count,
                    final_output = excluded.final_output,
                    error_summary = excluded.error_summary,
                    subtasks_json = excluded.subtasks_json,
                    metadata_json = excluded.metadata_json
            """, (
                task.task_id, task.user_id, task.goal, task.state.value,
                task.created_at, task.updated_at, task.completed_at,
                task.current_subtask_index, task.total_steps,
                task.completed_steps_count, task.retry_count, task.max_retries,
                task.final_output, task.error_summary, subtasks_json, metadata_json
            ))
            conn.commit()

    def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Fetch task record from SQLite."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                return None
            
            subtasks_raw = json.loads(row["subtasks_json"])
            subtasks = [SubtaskNode(**s) for s in subtasks_raw]
            metadata = json.loads(row["metadata_json"])

            return TaskRecord(
                task_id=row["task_id"],
                user_id=row["user_id"],
                goal=row["goal"],
                state=TaskState(row["state"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                completed_at=row["completed_at"],
                current_subtask_index=row["current_subtask_index"],
                total_steps=row["total_steps"],
                completed_steps_count=row["completed_steps_count"],
                retry_count=row["retry_count"],
                max_retries=row["max_retries"],
                final_output=row["final_output"],
                error_summary=row["error_summary"],
                subtasks=subtasks,
                metadata=metadata,
            )

    def transition_state(self, task: TaskRecord, new_state: TaskState, error: Optional[str] = None) -> TaskRecord:
        """Atomically transition task to a new lifecycle state."""
        old_state = task.state
        task.state = new_state
        if error:
            task.error_summary = error
        if new_state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
            task.completed_at = time.time()
        
        self.save_task(task)
        logger.info(f"[StateMachine] Task {task.task_id}: {old_state.value} -> {new_state.value}")
        return task

    def list_active_tasks(self) -> List[TaskRecord]:
        """List all incomplete tasks for resumption upon restart."""
        active_states = (
            TaskState.CREATED.value,
            TaskState.PLANNING.value,
            TaskState.AWAITING_APPROVAL.value,
            TaskState.EXECUTING.value,
            TaskState.VERIFYING.value,
            TaskState.WAITING_FOR_HUMAN.value,
            TaskState.RETRYING.value,
            TaskState.PAUSED.value,
        )
        placeholders = ",".join("?" for _ in active_states)
        with self._get_connection() as conn:
            cursor = conn.execute(f"SELECT task_id FROM tasks WHERE state IN ({placeholders}) ORDER BY created_at ASC", active_states)
            rows = cursor.fetchall()
            return [self.get_task(r["task_id"]) for r in rows if r]

    # ── Live Control Signals ──────────────────────────────────────────────────
    _pause_events: Dict[str, asyncio.Event] = {}
    _cancel_flags: Dict[str, bool] = {}

    def is_cancelled(self, task_id: str) -> bool:
        return self._cancel_flags.get(task_id, False)

    def cancel_task(self, task_id: str):
        self._cancel_flags[task_id] = True
        task = self.get_task(task_id)
        if task:
            self.transition_state(task, TaskState.CANCELLED, error="Task cancelled by user.")
        # If task was paused, unblock it so it can terminate cleanly
        if task_id in self._pause_events:
            self._pause_events[task_id].set()
        logger.warning(f"[StateMachine] Task {task_id} marked CANCELLED by user signal.")

    def pause_task(self, task_id: str):
        task = self.get_task(task_id)
        if task and task.state in (TaskState.EXECUTING, TaskState.PLANNING):
            self.transition_state(task, TaskState.PAUSED)
            event = asyncio.Event()
            self._pause_events[task_id] = event
            logger.info(f"[StateMachine] Task {task_id} PAUSED.")

    def resume_task(self, task_id: str):
        task = self.get_task(task_id)
        if task and task.state == TaskState.PAUSED:
            self.transition_state(task, TaskState.EXECUTING)
            event = self._pause_events.pop(task_id, None)
            if event:
                event.set()
            logger.info(f"[StateMachine] Task {task_id} RESUMED.")

    async def wait_if_paused(self, task_id: str):
        """Called between subtask executions to block if task is paused."""
        event = self._pause_events.get(task_id)
        if event:
            await event.wait()


# Singleton instance
task_state_machine = TaskStateMachine()
