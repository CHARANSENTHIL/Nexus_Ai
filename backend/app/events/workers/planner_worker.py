"""
Planner Agent Worker: Listens for TASK_CLASSIFIED and emits ACTION_REQUESTED events.
"""
import asyncio
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
    listen_event_types = [EventType.TASK_CLASSIFIED, EventType.ACTION_COMPLETED]

    def __init__(self, bus=None):
        super().__init__(bus)
        self._active_plans = {}
        self._action_task = None

    async def start(self):
        await super().start()
        # Also listen to action_events for ACTION_COMPLETED to trigger sequential pipeline steps
        self._action_task = asyncio.create_task(
            self.bus.listen_stream(
                stream_name="action_events",
                group_name="planner_step_group",
                consumer_name=f"{self.name}_step_consumer",
                target_event_types=[EventType.ACTION_COMPLETED],
                callback=self._on_event_received,
                stop_event=self._stop_event,
            )
        )

    async def stop(self):
        if self._action_task and not self._action_task.done():
            self._action_task.cancel()
        await super().stop()

    def _create_action_request(self, task_id: str, user_id: str, domain: str, subtask: dict, idx: int) -> NexusEvent:
        tool_name = subtask.get("tool", "run_shell_command")
        tool_input = subtask.get("tool_input", {})
        requires_approval = subtask.get("requires_approval", False)

        BROWSER_TOOLS = {
            "open_browser", "open_url", "search_web", "read_page",
            "click_element", "fill_form", "download_file", "upload_file",
            "take_browser_screenshot", "get_page_text", "close_browser",
            "download_images_from_web",
        }
        st_domain = domain
        if "browser" in tool_name or "url" in tool_name or tool_name in BROWSER_TOOLS:
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

        return NexusEvent(
            event_type=EventType.ACTION_REQUESTED,
            task_id=task_id,
            user_id=user_id,
            source_agent=self.name,
            payload=payload.model_dump(),
        )

    async def handle_event(self, event: NexusEvent) -> List[NexusEvent]:
        # 1. TASK_CLASSIFIED: Start step 0
        if event.event_type == EventType.TASK_CLASSIFIED:
            subtasks = event.payload.get("subtasks", [])
            domain = event.payload.get("domain", "pc_tools")
            logger.info(f"[PlannerWorker] Generating action requests for {len(subtasks)} subtask(s)")
            await task_tracker.update_task_from_event(event)

            if not subtasks:
                return []

            self._active_plans[event.task_id] = {
                "subtasks": subtasks,
                "domain": domain,
                "current_idx": 0,
                "user_id": event.user_id,
            }

            # Dispatch first subtask
            req_event = self._create_action_request(event.task_id, event.user_id, domain, subtasks[0], 0)
            return [req_event]

        # 2. ACTION_COMPLETED: Dispatch next sequential step if any
        elif event.event_type == EventType.ACTION_COMPLETED:
            plan = self._active_plans.get(event.task_id)
            if not plan:
                return []

            completed_idx = event.payload.get("subtask_index", plan.get("current_idx", 0))
            next_idx = completed_idx + 1
            subtasks = plan.get("subtasks", [])

            if next_idx < len(subtasks):
                plan["current_idx"] = next_idx
                next_subtask = subtasks[next_idx]
                logger.info(f"[PlannerWorker] ⚡ Triggering sequential subtask {next_idx+1}/{len(subtasks)}: {next_subtask.get('tool')}")
                req_event = self._create_action_request(event.task_id, plan["user_id"], plan["domain"], next_subtask, next_idx)
                return [req_event]
            else:
                # All steps dispatched
                self._active_plans.pop(event.task_id, None)
                return []

        return []


# Global instance
planner_worker = PlannerWorker()
