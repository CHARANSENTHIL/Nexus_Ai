"""
Tiered Memory System — 4-Tier Memory Architecture with TTL Expiration, Memory Governance & Invalidation.
Tiers:
  1. Working Memory: Active task context and immediate scratchpad.
  2. Episodic Memory: Task execution history, user decisions, and outcomes with TTL expiration.
  3. Semantic Memory: User preferences, project facts, and domain knowledge with metadata governance (confidence, source, sensitivity).
  4. Procedural Memory: Reusable workflows, site navigation recipes, and action procedures.
"""
import os
import json
import time
import sqlite3
import contextlib
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

MEMORY_DIR = Path(os.path.expanduser("~")) / ".nexus_ai"
MEMORY_DB_PATH = MEMORY_DIR / "memory.db"


class TieredMemoryManager:
    """
    Coordinates multi-tier memory storage, retrieval, consolidation, TTL expiration, and user invalidation ("forget that").
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or MEMORY_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._working_memory: Dict[str, Dict[str, Any]] = {}
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return contextlib.closing(conn)

    def _init_db(self):
        """Initialize episodic, semantic, and procedural memory tables."""
        with self._get_connection() as conn:
            # 1. Episodic Memory Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    actions_taken_json TEXT NOT NULL,
                    learnings_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodic_created ON episodic_memory(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodic_expires ON episodic_memory(expires_at)")

            # 2. Semantic Memory Table (Facts & Preferences with Governance Metadata)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS semantic_memory (
                    key TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    source TEXT DEFAULT 'user_statement',
                    sensitivity TEXT DEFAULT 'normal',
                    created_at REAL NOT NULL,
                    last_used REAL NOT NULL,
                    expires_at REAL,
                    updated_at REAL NOT NULL
                )
            """)

            # 3. Procedural Memory Table (Learned Workflows & Recipes)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS procedural_memory (
                    procedure_id TEXT PRIMARY KEY,
                    domain_or_app TEXT NOT NULL,
                    trigger_pattern TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    success_count INTEGER DEFAULT 1,
                    updated_at REAL NOT NULL
                )
            """)

            # Safe column migration for existing tables
            existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(semantic_memory)").fetchall()}
            for col, col_def in [
                ("source", "TEXT DEFAULT 'user_statement'"),
                ("sensitivity", "TEXT DEFAULT 'normal'"),
                ("created_at", "REAL DEFAULT 0"),
                ("last_used", "REAL DEFAULT 0"),
                ("expires_at", "REAL")
            ]:
                if col not in existing_cols:
                    try:
                        conn.execute(f"ALTER TABLE semantic_memory ADD COLUMN {col} {col_def}")
                    except Exception:
                        pass

            conn.commit()

    # ── Tier 1: Working Memory ────────────────────────────────────────────────
    def init_working_memory(self, task_id: str, goal: str, initial_context: Optional[Dict[str, Any]] = None):
        self._working_memory[task_id] = {
            "task_id": task_id,
            "goal": goal,
            "context": initial_context or {},
            "observations": [],
            "tool_calls": [],
            "created_at": time.time(),
        }

    def record_working_observation(self, task_id: str, observation: Dict[str, Any]):
        if task_id in self._working_memory:
            self._working_memory[task_id]["observations"].append(observation)

    def append_step_observation(self, task_id: str, step_title: str = "", tool: str = "", action_input: Optional[Dict[str, Any]] = None, observation: Any = None):
        self.record_working_observation(task_id, {
            "title": step_title,
            "tool": tool,
            "input": action_input or {},
            "observation": str(observation)[:300],
            "timestamp": time.time()
        })

    def get_working_memory(self, task_id: str) -> Dict[str, Any]:
        return self._working_memory.get(task_id, {})

    def clear_working_memory(self, task_id: str):
        self._working_memory.pop(task_id, None)

    # ── Tier 2: Episodic Memory (with TTL Expiration) ─────────────────────────
    def store_episode(
        self,
        task_id: str,
        goal: str,
        outcome: str,
        actions_taken: List[Dict[str, Any]],
        learnings: Optional[List[str]] = None,
        ttl_days: int = 30,
    ):
        now = time.time()
        expires = now + (ttl_days * 86400)
        episode_id = f"ep_{task_id}"

        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO episodic_memory (
                    id, task_id, goal, outcome, actions_taken_json, learnings_json, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                episode_id, task_id, goal, outcome,
                json.dumps(actions_taken), json.dumps(learnings or []),
                now, expires
            ))
            conn.commit()
        logger.info(f"[Memory] Stored episode {episode_id} (TTL={ttl_days}d)")

    def query_recent_episodes(self, limit: int = 10) -> List[Dict[str, Any]]:
        self.prune_expired_memories()
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM episodic_memory ORDER BY created_at DESC LIMIT ?", (limit,)
            )
            rows = cursor.fetchall()
            return [
                {
                    "task_id": r["task_id"],
                    "goal": r["goal"],
                    "outcome": r["outcome"],
                    "actions": json.loads(r["actions_taken_json"]),
                    "learnings": json.loads(r["learnings_json"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def prune_expired_memories(self) -> int:
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.execute("DELETE FROM episodic_memory WHERE expires_at < ?", (now,))
            conn.commit()
            return cursor.rowcount

    # ── Tier 3: Semantic Memory (Governed Facts, Preferences & Invalidation) ───
    def set_semantic_fact(
        self,
        key: str,
        value: Any,
        category: str = "preference",
        confidence: float = 1.0,
        source: str = "explicit_user_statement",
        sensitivity: str = "normal",
        ttl_days: Optional[int] = None
    ):
        now = time.time()
        expires = (now + ttl_days * 86400) if ttl_days else None
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO semantic_memory (
                    key, category, value_json, confidence, source, sensitivity,
                    created_at, last_used, expires_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                key, category, json.dumps(value), confidence, source, sensitivity,
                now, now, expires, now
            ))
            conn.commit()
        logger.info(f"[Memory] Saved governed semantic fact '{key}' [{category}] (source={source}, conf={confidence})")

    def get_semantic_fact(self, key: str) -> Optional[Any]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT value_json FROM semantic_memory WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                conn.execute("UPDATE semantic_memory SET last_used = ? WHERE key = ?", (time.time(), key))
                conn.commit()
                return json.loads(row["value_json"])
        return None

    def list_semantic_facts(self, category: Optional[str] = None) -> Dict[str, Any]:
        with self._get_connection() as conn:
            if category:
                cursor = conn.execute("SELECT key, value_json FROM semantic_memory WHERE category = ?", (category,))
            else:
                cursor = conn.execute("SELECT key, value_json FROM semantic_memory")
            rows = cursor.fetchall()
            return {r["key"]: json.loads(r["value_json"]) for r in rows}

    def forget_memory(self, query_or_key: str) -> int:
        """
        Invalidates and deletes stored memories matching a key or pattern ('Forget that' capability).
        Returns number of deleted facts.
        """
        with self._get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM semantic_memory WHERE key = ? OR key LIKE ? OR value_json LIKE ?",
                (query_or_key, f"%{query_or_key}%", f"%{query_or_key}%")
            )
            deleted_count = cur.rowcount
            conn.commit()
            logger.info(f"[Memory] 🗑️ User requested forget for '{query_or_key}'. Deleted {deleted_count} semantic entries.")
            return deleted_count

    # ── Tier 4: Procedural Memory (Learned Workflows & Recipes) ────────────────
    def store_procedure(self, domain_or_app: str, trigger_pattern: str, steps: List[Dict[str, Any]]):
        proc_id = f"proc_{domain_or_app.lower().replace(' ', '_')}"
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO procedural_memory (procedure_id, domain_or_app, trigger_pattern, steps_json, success_count, updated_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(procedure_id) DO UPDATE SET
                    steps_json = excluded.steps_json,
                    success_count = success_count + 1,
                    updated_at = excluded.updated_at
            """, (proc_id, domain_or_app, trigger_pattern, json.dumps(steps), time.time()))
            conn.commit()
        logger.info(f"[Memory] Stored procedural workflow for '{domain_or_app}'")

    def find_procedure(self, query: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM procedural_memory")
            rows = cursor.fetchall()
            q_lower = query.lower()
            for r in rows:
                if r["domain_or_app"].lower() in q_lower or r["trigger_pattern"].lower() in q_lower:
                    return {
                        "procedure_id": r["procedure_id"],
                        "domain": r["domain_or_app"],
                        "steps": json.loads(r["steps_json"]),
                        "success_count": r["success_count"],
                    }
        return None

    def retrieve_relevant_context(self, user_id: str = "default", query: str = "") -> Dict[str, Any]:
        facts = self.list_semantic_facts()
        proc = self.find_procedure(query) if query else None
        return {
            "semantic_facts": facts,
            "matched_procedure": proc,
            "query": query
        }

    # ── Consolidation Hook ────────────────────────────────────────────────────
    def consolidate_task_memory(self, task_id: str, goal: str = "", outcome: str = "", subtasks: Optional[List[Any]] = None, success: bool = True):
        wm = self.get_working_memory(task_id)
        effective_goal = goal or wm.get("goal", f"Task {task_id}")
        effective_outcome = outcome or ("Success" if success else "Failed")
        actions = []
        if subtasks:
            for st in subtasks:
                actions.append({
                    "title": getattr(st, "title", str(st)),
                    "tool": getattr(st, "tool_name", ""),
                    "success": getattr(st, "state", "") == "COMPLETED" or getattr(st, "verification_passed", False),
                })
        elif wm.get("observations"):
            actions = wm["observations"]

        self.store_episode(
            task_id=task_id,
            goal=effective_goal,
            outcome=effective_outcome,
            actions_taken=actions,
            learnings=[f"Task completed with {len(actions)} steps."],
            ttl_days=30,
        )

        self.clear_working_memory(task_id)
        return True


# Singleton instance
tiered_memory = TieredMemoryManager()
