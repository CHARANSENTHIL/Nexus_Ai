"""
Idempotency Subsystem — Guarantees exactly-once execution semantics for side-effecting actions.
Prevents duplicate emails, duplicate database mutations, repeated API dispatches on retry.
"""
import sqlite3
import json
import time
import hashlib
import logging
from typing import Dict, Any, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".nexus_ai" / "idempotency.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


class IdempotencyManager:
    """
    Tracks action commits keyed by (task_id, step_id, tool_name, input_hash).
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
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    idempotency_key TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    created_at REAL NOT NULL,
                    completed_at REAL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_idem_task ON idempotency_records(task_id)")
            conn.commit()

    def generate_key(self, task_id: str, step_id: str, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """Generate a deterministic idempotency key for an action step."""
        input_hash = hashlib.sha256(json.dumps(tool_input, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
        return f"{task_id}:{step_id}:{tool_name}:{input_hash}"

    def check_idempotency(self, idempotency_key: str) -> Tuple[bool, Optional[Any]]:
        """
        Check if an operation with this key has already succeeded.
        Returns: (is_cached, cached_result)
        """
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT status, result_json FROM idempotency_records WHERE idempotency_key = ?",
                (idempotency_key,)
            )
            row = cur.fetchone()
            if row and row["status"] == "COMPLETED":
                logger.info(f"[Idempotency] Cache hit for key: {idempotency_key}")
                cached_res = json.loads(row["result_json"]) if row["result_json"] else None
                return True, cached_res
            return False, None

    def record_start(self, idempotency_key: str, task_id: str, step_id: str, tool_name: str):
        """Mark action as in-flight."""
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO idempotency_records (idempotency_key, task_id, step_id, tool_name, status, created_at)
                VALUES (?, ?, ?, ?, 'IN_PROGRESS', ?)
                ON CONFLICT(idempotency_key) DO UPDATE SET status = 'IN_PROGRESS'
            """, (idempotency_key, task_id, step_id, tool_name, time.time()))
            conn.commit()

    def record_complete(self, idempotency_key: str, result: Any):
        """Commit action result under idempotency key."""
        with self._get_conn() as conn:
            conn.execute("""
                UPDATE idempotency_records
                SET status = 'COMPLETED', result_json = ?, completed_at = ?
                WHERE idempotency_key = ?
            """, (json.dumps(result, default=str), time.time(), idempotency_key))
            conn.commit()
            logger.debug(f"[Idempotency] Committed result for: {idempotency_key}")

    def record_failure(self, idempotency_key: str):
        """Clear or mark failure so retry can proceed if needed."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM idempotency_records WHERE idempotency_key = ?", (idempotency_key,))
            conn.commit()


# Singleton instance
idempotency_manager = IdempotencyManager()
