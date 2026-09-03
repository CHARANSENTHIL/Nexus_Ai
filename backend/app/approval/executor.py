"""
Approval Center & Self-Healing Executor.
- Gates dangerous actions behind Telegram Approve/Reject
- Wraps agent execution in fault-tolerant retry logic
- Maintains full audit log
"""
import asyncio
import uuid
import time
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Audit Log Model ───────────────────────────────────────────────────────────
class AuditLog(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    user_id: str
    action_type: str
    details: Dict[str, Any] = Field(default_factory=dict)
    outcome: str  # "approved", "rejected", "executed", "failed", "retried"
    reasoning: Optional[str] = None
    execution_duration_seconds: float = 0.0


# In-memory audit store (replace with DB in production)
_audit_log: list[AuditLog] = []

# Pending approvals: approval_id -> asyncio.Event + metadata
_pending_approvals: Dict[str, Dict[str, Any]] = {}


def get_audit_log(limit: int = 100) -> list:
    return [entry.model_dump() for entry in _audit_log[-limit:]]


def add_audit_entry(entry: AuditLog):
    _audit_log.append(entry)
    logger.info(f"[AUDIT] {entry.outcome.upper()} | {entry.action_type} | user={entry.user_id}")


# ── Approval Center ───────────────────────────────────────────────────────────
class ApprovalCenter:
    """Gates dangerous actions behind Telegram Approve/Reject inline keyboard."""

    async def request_approval(
        self,
        user_id: str,
        action_type: str,
        details: Dict[str, Any],
        notify_fn: Callable,  # async fn(user_id, message, approval_id) -> None
        timeout_seconds: int = 300,
    ) -> bool:
        """
        Send an approval request via Telegram and wait for response.
        Returns True if approved, False if rejected or timed out.
        """
        approval_id = str(uuid.uuid4())[:8]
        event = asyncio.Event()
        _pending_approvals[approval_id] = {
            "event": event,
            "approved": False,
            "user_id": user_id,
            "action_type": action_type,
        }

        # Send Telegram approval message
        message = (
            f"⚠️ *Approval Required*\n\n"
            f"Action: `{action_type}`\n"
            f"Details: `{str(details)[:300]}`\n\n"
            f"Approval ID: `{approval_id}`\n"
            f"This action requires your explicit approval."
        )
        await notify_fn(user_id, message, approval_id)

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
            approved = _pending_approvals[approval_id]["approved"]
        except asyncio.TimeoutError:
            approved = False
            logger.warning(f"Approval {approval_id} timed out after {timeout_seconds}s")
        finally:
            _pending_approvals.pop(approval_id, None)

        outcome = "approved" if approved else "rejected"
        add_audit_entry(AuditLog(
            user_id=user_id,
            action_type=action_type,
            details=details,
            outcome=outcome,
        ))
        return approved

    def resolve_approval(self, approval_id: str, approved: bool):
        """Called when user taps Approve or Reject in Telegram."""
        if approval_id in _pending_approvals:
            _pending_approvals[approval_id]["approved"] = approved
            _pending_approvals[approval_id]["event"].set()

    def get_pending(self) -> list:
        return [
            {"approval_id": aid, "action_type": v["action_type"], "user_id": v["user_id"]}
            for aid, v in _pending_approvals.items()
        ]


# ── Self-Healing Executor ─────────────────────────────────────────────────────
class SelfHealingExecutor:
    """
    Wraps any async callable in fault-tolerant retry logic.
    On failure: collect logs → retry with alternative → notify user.
    """

    async def execute(
        self,
        action: Callable,
        action_name: str,
        user_id: str,
        notify_fn: Callable,
        max_retries: int = 2,
        fallback: Optional[Callable] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        start_time = time.time()
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                if asyncio.iscoroutinefunction(action):
                    result = await action(**kwargs)
                else:
                    result = action(**kwargs)

                duration = round(time.time() - start_time, 2)
                add_audit_entry(AuditLog(
                    user_id=user_id,
                    action_type=action_name,
                    details=kwargs,
                    outcome="executed",
                    execution_duration_seconds=duration,
                ))
                return {"success": True, "result": result, "attempt": attempt + 1}

            except Exception as e:
                last_error = e
                logger.warning(f"[EXECUTOR] Attempt {attempt + 1} failed for '{action_name}': {e}")
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff

        # All retries exhausted — try fallback
        if fallback:
            try:
                logger.info(f"[EXECUTOR] Trying fallback for '{action_name}'")
                result = await fallback(**kwargs) if asyncio.iscoroutinefunction(fallback) else fallback(**kwargs)
                add_audit_entry(AuditLog(
                    user_id=user_id,
                    action_type=f"{action_name}_fallback",
                    details=kwargs,
                    outcome="retried",
                ))
                return {"success": True, "result": result, "fallback_used": True}
            except Exception as fallback_err:
                last_error = fallback_err

        # Total failure — notify user with root cause
        duration = round(time.time() - start_time, 2)
        error_msg = str(last_error)
        add_audit_entry(AuditLog(
            user_id=user_id,
            action_type=action_name,
            details={"error": error_msg, **kwargs},
            outcome="failed",
            execution_duration_seconds=duration,
        ))

        failure_message = (
            f"❌ *Task Failed: {action_name}*\n\n"
            f"Root cause: `{error_msg[:300]}`\n"
            f"Attempts: {max_retries + 1}\n"
            f"Duration: {duration}s\n\n"
            f"The system could not complete this task after {max_retries + 1} attempts."
        )
        await notify_fn(user_id, failure_message)
        return {"success": False, "error": error_msg, "attempts": max_retries + 1}


# Singletons
approval_center = ApprovalCenter()
self_healing_executor = SelfHealingExecutor()
