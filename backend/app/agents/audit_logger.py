"""
Audit Logger — Writes action execution trace to PostgreSQL (primary) or JSONL file (fallback).

Schema:
  Table: agent_actions
  Columns: task_id, action_id, agent, tool, arguments_json, expected_state_json,
           actual_state_json, verification_result_json, confidence, attempt,
           latency_ms, recovery_action, success, timestamp
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.agents.action_observation import Action, Observation, VerificationResult

logger = logging.getLogger(__name__)

# Fallback JSONL file path when PostgreSQL is unavailable
AUDIT_LOG_PATH = r"D:\nexus_ai\backend\audit_log.jsonl"

# PostgreSQL DDL (run manually when DB is available)
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent_actions (
    id             SERIAL PRIMARY KEY,
    task_id        TEXT NOT NULL,
    action_id      TEXT NOT NULL,
    agent          TEXT NOT NULL DEFAULT 'nexus_ai',
    tool           TEXT NOT NULL,
    arguments_json JSONB,
    expected_state_json JSONB,
    actual_state_json   JSONB,
    verification_result_json JSONB,
    confidence     FLOAT,
    attempt        INT DEFAULT 0,
    latency_ms     INT,
    recovery_action TEXT,
    success        BOOLEAN,
    timestamp      TIMESTAMPTZ DEFAULT now()
);
"""


class AuditLogger:
    """
    Dual-write audit logger. Tries PostgreSQL first, silently falls back to JSONL.
    """

    def __init__(self):
        self._pg_available: Optional[bool] = None  # None = untested
        self._task_id: str = str(uuid.uuid4())[:8]

    def new_task(self) -> str:
        """Start a new task context and return the task_id."""
        self._task_id = str(uuid.uuid4())[:8]
        return self._task_id

    async def log(
        self,
        action: Action,
        observation: Observation,
        result: VerificationResult,
        latency_ms: int,
        attempt: int = 0,
        recovery_action: str = "",
        agent: str = "nexus_ai",
    ) -> None:
        """Log one action execution record."""
        record = {
            "task_id": self._task_id,
            "action_id": action.id,
            "agent": agent,
            "tool": action.tool,
            "arguments_json": action.arguments,
            "expected_state_json": action.expected_state,
            "actual_state_json": {
                "process_state": observation.process_state,
                "window_state": observation.window_state,
                "screen_state": {
                    k: v for k, v in observation.screen_state.items()
                    if k != "ocr_text"  # too verbose for DB
                },
                "browser_state": observation.browser_state,
                "errors": observation.errors,
            },
            "verification_result_json": {
                "success": result.success,
                "confidence": result.confidence,
                "reason": result.reason,
                "checks": [c.model_dump() for c in result.checks],
            },
            "confidence": result.confidence,
            "attempt": attempt,
            "latency_ms": latency_ms,
            "recovery_action": recovery_action,
            "success": result.success,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Try PostgreSQL first
        if self._pg_available is not False:
            pg_ok = await self._write_postgres(record)
            if pg_ok:
                return

        # Fallback: JSONL file
        self._write_jsonl(record)

    # ── PostgreSQL Write ────────────────────────────────────────────────────────
    async def _write_postgres(self, record: Dict[str, Any]) -> bool:
        """Attempt to write to PostgreSQL. Returns True on success."""
        try:
            import asyncpg  # type: ignore
            dsn = os.getenv("DATABASE_URL", "postgresql://localhost:5432/nexus_ai")
            conn = await asyncpg.connect(dsn, timeout=3)
            try:
                await conn.execute(
                    """
                    INSERT INTO agent_actions
                        (task_id, action_id, agent, tool, arguments_json,
                         expected_state_json, actual_state_json,
                         verification_result_json, confidence,
                         attempt, latency_ms, recovery_action, success, timestamp)
                    VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8::jsonb,
                            $9,$10,$11,$12,$13,$14)
                    """,
                    record["task_id"],
                    record["action_id"],
                    record["agent"],
                    record["tool"],
                    json.dumps(record["arguments_json"]),
                    json.dumps(record["expected_state_json"]),
                    json.dumps(record["actual_state_json"]),
                    json.dumps(record["verification_result_json"]),
                    record["confidence"],
                    record["attempt"],
                    record["latency_ms"],
                    record["recovery_action"],
                    record["success"],
                    record["timestamp"],
                )
                self._pg_available = True
                logger.debug(f"[AuditLogger] PostgreSQL write OK: action={record['action_id']}")
                return True
            finally:
                await conn.close()
        except Exception as e:
            if self._pg_available is None:
                logger.info(f"[AuditLogger] PostgreSQL unavailable ({e}). Using JSONL fallback.")
            self._pg_available = False
            return False

    # ── JSONL Fallback Write ────────────────────────────────────────────────────
    def _write_jsonl(self, record: Dict[str, Any]) -> None:
        """Append one JSON record to the JSONL audit log file."""
        try:
            os.makedirs(os.path.dirname(AUDIT_LOG_PATH), exist_ok=True)
            with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            logger.debug(f"[AuditLogger] JSONL write OK: action={record['action_id']}")
        except Exception as e:
            logger.error(f"[AuditLogger] JSONL write error: {e}")

    def get_ddl(self) -> str:
        """Return the PostgreSQL DDL to create the audit table."""
        return CREATE_TABLE_SQL


# Singleton
audit_logger = AuditLogger()
