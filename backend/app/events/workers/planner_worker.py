"""
Planner Agent Worker: Listens for TASK_CLASSIFIED and emits ACTION_REQUESTED events.
"""
import logging
from typing import List

from app.events.agent_worker import AgentWorker
from app.events.event_models import ActionRequestedPayload, EventType, NexusEvent
from app.events.task_tracker import task_tracker

logger = logging.getLogger(__name__)


class PlannerWorker(AgentWorker):
    name = "planner_agent"
    listen_stream = "task_events"
    consumer_group = "planner_group"
    listen_event_types = [EventType.TASK_CLASSIFIED]

    async def handle_event(self, event: NexusEvent) -> List[NexusEvent]:
        subtasks = event.payload.get("subtasks", [])
        domain = event.payload.get("domain", "pc_tools")
        logger.info(f"[PlannerWorker] Generating action requests for {len(subtasks)} subtask(s)")
        await task_tracker.update_task_from_event(event)

        action_events: List[NexusEvent] = []
        for idx, subtask in enumerate(subtasks):
            tool_name = subtask.get("tool", "run_shell_command")
            tool_input = subtask.get("tool_input", {})
            requires_approval = subtask.get("requires_approval", False)

            # Infer domain if tool is browser-specific
            st_domain = domain
            if "browser" in tool_name or "url" in tool_name:
                st_domain = "browser"
            elif tool_name in ("run_shell_command", "repair_source_code") and domain == "coding":
                st_domain = "coding"

            payload = ActionRequestedPayload(
                action=tool_name,
                tool_input=tool_input,
                domain=st_domain,
                subtask_index=idx,
                requires_approval=requires_approval,
            )

            req_event = NexusEvent(
                event_type=EventType.ACTION_REQUESTED,
                task_id=event.task_id,
                user_id=event.user_id,
                source_agent=self.name,
                payload=payload.model_dump(),
            )
            action_events.append(req_event)

        return action_events


# Global instance
planner_worker = PlannerWorker()
