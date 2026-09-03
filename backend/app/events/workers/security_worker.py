"""
Security Agent Worker: Listens for ACTION_REQUESTED and emits ACTION_APPROVED or ACTION_BLOCKED.
"""
import logging
from typing import List

from app.approval.security_policy import RiskLevel, security_policy_engine
from app.events.agent_worker import AgentWorker
from app.events.event_models import EventType, NexusEvent
from app.events.task_tracker import task_tracker

logger = logging.getLogger(__name__)


class SecurityWorker(AgentWorker):
    name = "security_agent"
    listen_stream = "action_events"
    consumer_group = "security_group"
    listen_event_types = [EventType.ACTION_REQUESTED]

    async def handle_event(self, event: NexusEvent) -> List[NexusEvent]:
        from app.agents.self_healing_models import RecoveryAction
        action_name = event.payload.get("action", "")
        tool_input = event.payload.get("tool_input", {})
        subtask_idx = event.payload.get("subtask_index", 0)

        args = tool_input if isinstance(tool_input, dict) else {"command": str(tool_input)}
        rec_action = RecoveryAction(
            action_id=event.event_id,
            strategy_name="direct_action",
            tool_name=action_name,
            arguments=args,
            description=f"Action: {action_name}",
            risk_level=RiskLevel.LOW,
        )


        # Evaluate risk policy
        risk, reason = security_policy_engine.evaluate_risk(rec_action)
        logger.info(f"[SecurityWorker] Evaluated action '{action_name}' as RiskLevel.{risk.name}")
        await task_tracker.update_task_from_event(event)

        if risk == RiskLevel.CRITICAL:
            blocked_event = NexusEvent(
                event_type=EventType.ACTION_BLOCKED,
                task_id=event.task_id,
                user_id=event.user_id,
                source_agent=self.name,
                payload={
                    "action": action_name,
                    "reason": reason or f"Action violates security policy (RiskLevel.CRITICAL): '{action_name}'",
                    "subtask_index": subtask_idx,
                    "risk": risk.value,
                },
            )
            await task_tracker.update_task_from_event(blocked_event)
            return [blocked_event]

        # LOW / MEDIUM: auto-approve
        approved_event = NexusEvent(
            event_type=EventType.ACTION_APPROVED,
            task_id=event.task_id,
            user_id=event.user_id,
            source_agent=self.name,
            payload={
                "action": action_name,
                "tool_input": tool_input,
                "domain": event.payload.get("domain", "pc_tools"),
                "subtask_index": subtask_idx,
                "risk": risk.value,
            },
        )
        return [approved_event]



# Global instance
security_worker = SecurityWorker()
