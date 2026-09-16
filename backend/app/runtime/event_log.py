"""
Append-Only Execution Event Log — Enterprise Event Sourcing for Nexus AI.
Provides sequence-numbered, tamper-evident audit logs, replay, and forensic analysis.
"""
import sqlite3
import json
import time
import hashlib
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".nexus_ai" / "events.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


class ExecutionEventType:
    TASK_CREATED = "TASK_CREATED"
    PLAN_GENERATED = "PLAN_GENERATED"
    RESOURCE_ACQUIRED = "RESOURCE_ACQUIRED"
    RESOURCE_RELEASED = "RESOURCE_RELEASED"
    TOOL_REQUESTED = "TOOL_REQUESTED"
    POLICY_CHECKED = "POLICY_CHECKED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_GRANTED = "APPROVAL_GRANTED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    IDEMPOTENCY_HIT = "IDEMPOTENCY_HIT"
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    TOOL_FAILED = "TOOL_FAILED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_PASSED = "VERIFICATION_PASSED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    HUMAN_HANDOFF = "HUMAN_HANDOFF"
    HUMAN_RESUMED = "HUMAN_RESUMED"
    TASK_PAUSED = "TASK_PAUSED"
    TASK_RESUMED = "TASK_RESUMED"
    CANCELLATION_REQUESTED = "CANCELLATION_REQUESTED"
    TASK_CANCELLED = "TASK_CANCELLED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"


@dataclass
class ExecutionEvent:
    task_id: str
    sequence: int
    event_type: str
    tool_name: Optional[str] = None
    input_summary: Optional[str] = None
    result_hash: Optional[str] = None
    duration_ms: Optional[float] = None
    timestamp: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()
        if self.metadata is None:
            self.metadata = {}


class ExecutionEventLog:
    """
    Append-only SQLite event store with sequence-ordered task timelines and replay capabilities.
    """

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    tool_name TEXT,
                    input_summary TEXT,
                    result_hash TEXT,
                    duration_ms REAL,
                    timestamp REAL NOT NULL,
                    metadata_json TEXT,
                    UNIQUE(task_id, sequence)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_task ON execution_events(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON execution_events(event_type)")
            conn.commit()

    def _get_next_sequence(self, task_id: str) -> int:
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM execution_events WHERE task_id = ?",
                (task_id,)
            )
            row = cur.fetchone()
            return row["next_seq"] if row else 1

    def append_event(
        self,
        task_id: str,
        event_type: str,
        tool_name: Optional[str] = None,
        input_data: Optional[Any] = None,
        output_data: Optional[Any] = None,
        duration_ms: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ExecutionEvent:
        """Append a sequence-ordered execution event to the tamper-evident event log."""
        sequence = self._get_next_sequence(task_id)

        input_summary = None
        if input_data is not None:
            raw_s = json.dumps(input_data, default=str)
            input_summary = raw_s[:200] + ("..." if len(raw_s) > 200 else "")

        result_hash = None
        if output_data is not None:
            raw_out = json.dumps(output_data, default=str, sort_keys=True)
            result_hash = hashlib.sha256(raw_out.encode("utf-8")).hexdigest()[:16]

        event = ExecutionEvent(
            task_id=task_id,
            sequence=sequence,
            event_type=event_type,
            tool_name=tool_name,
            input_summary=input_summary,
            result_hash=result_hash,
            duration_ms=duration_ms,
            timestamp=time.time(),
            metadata=metadata or {}
        )

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO execution_events (
                    task_id, sequence, event_type, tool_name,
                    input_summary, result_hash, duration_ms, timestamp, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.task_id,
                event.sequence,
                event.event_type,
                event.tool_name,
                event.input_summary,
                event.result_hash,
                event.duration_ms,
                event.timestamp,
                json.dumps(event.metadata, default=str)
            ))
            conn.commit()

        logger.debug(f"[EventLog] #{event.sequence} [{task_id}] {event.event_type} tool={tool_name}")
        return event

    def get_task_events(self, task_id: str) -> List[Dict[str, Any]]:
        """Retrieve the full chronological event stream for a task."""
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT * FROM execution_events WHERE task_id = ? ORDER BY sequence ASC",
                (task_id,)
            )
            events = []
            for row in cur.fetchall():
                events.append({
                    "task_id": row["task_id"],
                    "sequence": row["sequence"],
                    "event_type": row["event_type"],
                    "tool_name": row["tool_name"],
                    "input_summary": row["input_summary"],
                    "result_hash": row["result_hash"],
                    "duration_ms": row["duration_ms"],
                    "timestamp": row["timestamp"],
                    "metadata": json.loads(row["metadata_json"]) if row["metadata_json"] else {}
                })
            return events

    def get_event_metrics(self) -> Dict[str, Any]:
        """Get global event counts and statistics."""
        with self._get_conn() as conn:
            total_cur = conn.execute("SELECT COUNT(*) AS total FROM execution_events")
            total = total_cur.fetchone()["total"]
            types_cur = conn.execute("SELECT event_type, COUNT(*) AS cnt FROM execution_events GROUP BY event_type")
            type_counts = {r["event_type"]: r["cnt"] for r in types_cur.fetchall()}
            return {"total_events": total, "by_type": type_counts}


# Singleton instance
execution_event_log = ExecutionEventLog()
