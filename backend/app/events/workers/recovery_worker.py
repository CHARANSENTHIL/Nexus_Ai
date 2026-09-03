"""
Recovery Agent Worker: Listens for ACTION_FAILED / VERIFICATION_FAILED and executes self-healing recovery.
"""
import logging
from typing import List

from app.agents.code_repair_engine import code_repair_engine
from app.agents.error_analyzer import error_analyzer
from app.events.agent_worker import AgentWorker
from app.events.event_models import (
    ActionRequestedPayload,
    EventType,
    NexusEvent,
    RecoveryPayload,
)
from app.events.task_tracker import task_tracker

logger = logging.getLogger(__name__)


class RecoveryWorker(AgentWorker):
    name = "recovery_agent"
    listen_stream = "action_events"
    consumer_group = "recovery_group"
    listen_event_types = [EventType.ACTION_FAILED, EventType.VERIFICATION_FAILED]

    async def handle_event(self, event: NexusEvent) -> List[NexusEvent]:
        error_msg = event.payload.get("error") or event.payload.get("detail") or "Unknown failure"
        action = event.payload.get("action", "run_shell_command")
        subtask_idx = event.payload.get("subtask_index", 0)

        logger.info(f"[RecoveryWorker] 🛡️ Analyzing failure: '{error_msg}'")

        # Emit RECOVERY_STARTED
        start_payload = RecoveryPayload(
            strategy="self_heal_diagnosis",
            attempt=1,
            repaired_successfully=False,
            repair_note="Diagnosing failure with ErrorAnalyzer",
        )
        rec_start_evt = NexusEvent(
            event_type=EventType.RECOVERY_STARTED,
            task_id=event.task_id,
            user_id=event.user_id,
            source_agent=self.name,
            payload=start_payload.model_dump(),
        )
        await task_tracker.update_task_from_event(rec_start_evt)

        # 1. Analyze error
        diagnosis = await error_analyzer.analyze(error_msg)
        logger.info(f"[RecoveryWorker] 🔍 Diagnosis: {diagnosis.category} (entity: '{diagnosis.missing_entity}')")


        repaired = False
        repair_note = None

        # 2. Heuristic or AST Code Repair
        if "syntax" in diagnosis.category.value or "NameError" in error_msg or "SyntaxError" in error_msg:
            repair_res = await code_repair_engine.repair_file(error_msg)
            if repair_res.get("success"):
                repaired = True
                repair_note = repair_res.get("explanation", "Auto-repaired source code.")

        if repaired:
            rec_succ_payload = RecoveryPayload(
                strategy=diagnosis.category.value,
                attempt=1,
                repaired_successfully=True,
                repair_note=repair_note,
            )
            rec_succ_evt = NexusEvent(
                event_type=EventType.RECOVERY_SUCCEEDED,
                task_id=event.task_id,
                user_id=event.user_id,
                source_agent=self.name,
                payload=rec_succ_payload.model_dump(),
            )
            await task_tracker.update_task_from_event(rec_succ_evt)

            # Re-emit ACTION_REQUESTED to retry the action
            retry_payload = ActionRequestedPayload(
                action=action,
                tool_input=event.payload.get("tool_input", {}),
                domain="coding",
                subtask_index=subtask_idx,
            )
            retry_evt = NexusEvent(
                event_type=EventType.ACTION_REQUESTED,
                task_id=event.task_id,
                user_id=event.user_id,
                source_agent=self.name,
                payload=retry_payload.model_dump(),
            )
            return [rec_start_evt, rec_succ_evt, retry_evt]

        # Recovery failed
        rec_fail_payload = RecoveryPayload(
            strategy=diagnosis.category.value,
            attempt=1,
            repaired_successfully=False,
            repair_note=f"Unable to automatically heal error: {error_msg}",
        )
        rec_fail_evt = NexusEvent(
            event_type=EventType.RECOVERY_FAILED,
            task_id=event.task_id,
            user_id=event.user_id,
            source_agent=self.name,
            payload=rec_fail_payload.model_dump(),
        )
        await task_tracker.update_task_from_event(rec_fail_evt)

        # Mark TASK_FAILED
        task_fail_evt = NexusEvent(
            event_type=EventType.TASK_FAILED,
            task_id=event.task_id,
            user_id=event.user_id,
            source_agent=self.name,
            payload={"error": f"❌ Action '{action}' failed and could not be recovered: {error_msg}"},
        )
        await task_tracker.update_task_from_event(task_fail_evt)
        return [rec_start_evt, rec_fail_evt, task_fail_evt]


# Global instance
recovery_worker = RecoveryWorker()
