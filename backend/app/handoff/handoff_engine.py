"""
Human Handoff Engine — Orchestrates seamless human-in-the-loop transitions.
Handles OTP/2FA requests, CAPTCHAs, sensitive approvals, and state-verified resumption.
"""
import os
import json
import time
import asyncio
import inspect
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Callable, List

from app.handoff.handoff_models import (
    HandoffState,
    HandoffTrigger,
    HandoffCheckpoint,
)

logger = logging.getLogger(__name__)

CHECKPOINT_DIR = Path(os.path.expanduser("~")) / ".nexus_ai" / "handoff_checkpoints"


class HandoffEngine:
    """
    Coordinates agent pauses, user notifications via Telegram, state verification,
    and task resumption.
    """

    def __init__(self):
        self.checkpoint_dir = CHECKPOINT_DIR
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._active_handoffs: Dict[str, HandoffCheckpoint] = {}
        self._handoff_events: Dict[str, asyncio.Event] = {}
        self._telegram_notifier: Optional[Callable] = None

    def register_notifier(self, notifier_fn: Callable):
        """Register Telegram notification callback async fn(user_id, text, keyboard_buttons)."""
        self._telegram_notifier = notifier_fn
        logger.info("[HandoffEngine] Telegram notifier registered.")

    async def trigger_handoff(
        self,
        task_id: str,
        user_id: str,
        agent_name: str,
        trigger: HandoffTrigger,
        reason: str,
        subtask_index: int = 0,
        subtask_data: Optional[Dict[str, Any]] = None,
        target_url: Optional[str] = None,
        expected_url_change: Optional[str] = None,
        screenshot_path: Optional[str] = None,
        timeout_seconds: int = 600,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> HandoffCheckpoint:
        """
        Creates a handoff checkpoint, alerts the user, and sets the state machine to WAITING_FOR_HUMAN.
        """
        checkpoint = HandoffCheckpoint(
            task_id=task_id,
            user_id=user_id,
            agent_name=agent_name,
            trigger=trigger,
            reason=reason,
            subtask_index=subtask_index,
            subtask_data=subtask_data or {},
            target_url=target_url,
            initial_url=target_url,
            expected_url_change=expected_url_change,
            screenshot_path=screenshot_path,
            timeout_seconds=timeout_seconds,
            metadata=metadata or {},
            state=HandoffState.WAITING_FOR_HUMAN,
        )

        self._active_handoffs[checkpoint.checkpoint_id] = checkpoint
        self._handoff_events[checkpoint.checkpoint_id] = asyncio.Event()
        self._persist_checkpoint(checkpoint)

        logger.warning(
            f"[HandoffEngine] 🚨 Handoff triggered [{checkpoint.checkpoint_id}] "
            f"Trigger={trigger.value} Reason='{reason}' User={user_id}"
        )

        # Send Telegram notification if notifier available
        if self._telegram_notifier:
            try:
                await self._notify_user_telegram(checkpoint)
            except Exception as e:
                logger.error(f"[HandoffEngine] Failed to send Telegram handoff notification: {e}")

        return checkpoint

    async def _notify_user_telegram(self, checkpoint: HandoffCheckpoint):
        """Format and dispatch rich interactive handoff prompt to Telegram."""
        trigger_emojis = {
            HandoffTrigger.OTP_REQUIRED: "🔐",
            HandoffTrigger.CAPTCHA_DETECTED: "🧩",
            HandoffTrigger.SENSITIVE_ACTION: "⚠️",
            HandoffTrigger.LOW_CONFIDENCE: "❓",
            HandoffTrigger.STUCK_LOOP: "🔄",
            HandoffTrigger.MANUAL_REQUEST: "👤",
        }
        emoji = trigger_emojis.get(checkpoint.trigger, "✋")

        msg = (
            f"{emoji} *HUMAN ASSISTANCE REQUIRED*\n\n"
            f"*Reason*: {checkpoint.reason}\n"
            f"*Agent*: `{checkpoint.agent_name}`\n"
            f"*Task*: `{checkpoint.task_id[:8]}`\n"
        )
        if checkpoint.target_url:
            msg += f"*URL*: `{checkpoint.target_url}`\n"

        buttons = []
        if checkpoint.trigger == HandoffTrigger.OTP_REQUIRED:
            msg += "\n_Please reply to this bot with the OTP code or complete 2FA in the opened browser, then tap Done._"
            buttons = [
                [{"text": "✅ 2FA Completed (Resume)", "callback_data": f"handoff_done:{checkpoint.checkpoint_id}"}],
                [{"text": "❌ Cancel Task", "callback_data": f"handoff_cancel:{checkpoint.checkpoint_id}"}]
            ]
        elif checkpoint.trigger == HandoffTrigger.CAPTCHA_DETECTED:
            msg += "\n_Please solve the CAPTCHA in the opened browser window, then tap I've Solved It below._"
            buttons = [
                [{"text": "✅ I've Solved the CAPTCHA", "callback_data": f"handoff_done:{checkpoint.checkpoint_id}"}],
                [{"text": "❌ Cancel Task", "callback_data": f"handoff_cancel:{checkpoint.checkpoint_id}"}]
            ]
        elif checkpoint.trigger == HandoffTrigger.SENSITIVE_ACTION:
            msg += "\n_This action is sensitive and requires explicit confirmation._"
            buttons = [
                [{"text": "👍 Approve & Continue", "callback_data": f"handoff_done:{checkpoint.checkpoint_id}"}],
                [{"text": "🛑 Reject Action", "callback_data": f"handoff_cancel:{checkpoint.checkpoint_id}"}]
            ]
        else:
            buttons = [
                [{"text": "✅ Resume Agent", "callback_data": f"handoff_done:{checkpoint.checkpoint_id}"}],
                [{"text": "❌ Cancel", "callback_data": f"handoff_cancel:{checkpoint.checkpoint_id}"}]
            ]

        await self._telegram_notifier(checkpoint.user_id, msg, buttons, checkpoint.screenshot_path)

    async def wait_for_resolution(
        self,
        checkpoint_id: str,
        verifiers: Optional[List[Callable[[], Any]]] = None
    ) -> HandoffCheckpoint:
        """
        Pauses caller until human completes handoff or timeout expires.
        Runs post-handoff verification before returning state RESUMED.
        """
        checkpoint = self._active_handoffs.get(checkpoint_id)
        if not checkpoint:
            raise ValueError(f"No active handoff found for ID {checkpoint_id}")

        event = self._handoff_events.get(checkpoint_id)
        if not event:
            event = asyncio.Event()
            self._handoff_events[checkpoint_id] = event

        try:
            await asyncio.wait_for(event.wait(), timeout=checkpoint.timeout_seconds)
        except asyncio.TimeoutError:
            checkpoint.state = HandoffState.FAILED
            checkpoint.verification_notes = f"Handoff timed out after {checkpoint.timeout_seconds} seconds."
            self._persist_checkpoint(checkpoint)
            logger.warning(f"[HandoffEngine] Handoff {checkpoint_id} TIMED OUT.")
            return checkpoint

        # Human signaled completion — verify state
        checkpoint.state = HandoffState.VERIFYING_HANDOFF
        self._persist_checkpoint(checkpoint)

        verification_passed = True
        verification_notes = "User confirmed completion."

        if verifiers:
            for verifier in verifiers:
                try:
                    if inspect.iscoroutinefunction(verifier):
                        v_result = await verifier()
                    else:
                        v_result = verifier()
                    if not v_result:
                        verification_passed = False
                        verification_notes = f"Verification check failed: {verifier.__name__}"
                        break
                except Exception as e:
                    logger.error(f"[HandoffEngine] Verifier exception: {e}")
                    verification_passed = False
                    verification_notes = f"Verification exception: {e}"
                    break

        checkpoint.verification_passed = verification_passed
        checkpoint.verification_notes = verification_notes
        if verification_passed:
            checkpoint.state = HandoffState.RESUMED
            logger.info(f"[HandoffEngine] ✅ Handoff {checkpoint_id} VERIFIED & RESUMED.")
        else:
            checkpoint.state = HandoffState.FAILED
            logger.warning(f"[HandoffEngine] ❌ Handoff {checkpoint_id} verification failed: {verification_notes}")

        checkpoint.resolved_at = time.time()
        self._persist_checkpoint(checkpoint)
        return checkpoint

    def resolve_handoff(self, checkpoint_id: str, human_input: Optional[str] = None, approved: bool = True):
        """Called when user interacts with Telegram buttons or provides OTP."""
        checkpoint = self._active_handoffs.get(checkpoint_id)
        if not checkpoint:
            logger.warning(f"[HandoffEngine] Cannot resolve unknown checkpoint {checkpoint_id}")
            return False

        checkpoint.human_input = human_input
        checkpoint.state = HandoffState.HUMAN_ACTIVE if approved else HandoffState.FAILED
        if not approved:
            checkpoint.verification_notes = "User explicitly rejected / cancelled handoff."

        self._persist_checkpoint(checkpoint)

        event = self._handoff_events.get(checkpoint_id)
        if event:
            event.set()
        return True

    def get_checkpoint(self, checkpoint_id: str) -> Optional[HandoffCheckpoint]:
        return self._active_handoffs.get(checkpoint_id)

    def _persist_checkpoint(self, checkpoint: HandoffCheckpoint):
        try:
            file_path = self.checkpoint_dir / f"{checkpoint.checkpoint_id}.json"
            file_path.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"[HandoffEngine] Failed to persist checkpoint {checkpoint.checkpoint_id}: {e}")


# Singleton instance
handoff_engine = HandoffEngine()
