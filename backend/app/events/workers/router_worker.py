"""
Router Agent Worker: Listens for TASK_CREATED and emits TASK_CLASSIFIED.
"""
import logging
from typing import List

from app.agents.grok_classifier import grok_classifier
from app.agents.planner import IntentRouter, planner_agent
from app.events.agent_worker import AgentWorker
from app.events.event_models import EventType, NexusEvent, TaskClassifiedPayload
from app.events.task_tracker import task_tracker

logger = logging.getLogger(__name__)


class RouterWorker(AgentWorker):
    name = "router_agent"
    listen_stream = "task_events"
    consumer_group = "router_group"
    listen_event_types = [EventType.TASK_CREATED]

    async def handle_event(self, event: NexusEvent) -> List[NexusEvent]:
        command = event.payload.get("command", "")
        logger.info(f"[RouterWorker] Routing incoming command: '{command}'")
        await task_tracker.update_task_from_event(event)

        # ── Tier 1: Keyword Fast Path (0ms) ──────────────────────────────────
        keyword_subtasks = IntentRouter.detect(command)
        if keyword_subtasks:
            domain = "pc_tools"
            cmd_lower = command.lower()
            if any(w in cmd_lower for w in ("youtube", "browse", "website", "http", "google.com")):
                domain = "browser"
            elif any(w in cmd_lower for w in ("run project", "run python", "run script", "execute")):
                domain = "coding"

            payload = TaskClassifiedPayload(
                intent="keyword_command",
                domain=domain,
                subtasks=keyword_subtasks,
                confidence=1.0,
            )
            out_event = NexusEvent(
                event_type=EventType.TASK_CLASSIFIED,
                task_id=event.task_id,
                user_id=event.user_id,
                source_agent=self.name,
                payload=payload.model_dump(),
            )
            await task_tracker.update_task_from_event(out_event)
            return [out_event]

        # ── Tier 2: Grok/Qwen NLP Classifier ──────────────────────────────────
        classification = await grok_classifier.classify(command)
        task_type = classification.get("type", "simple_task")

        if task_type == "chat":
            payload = TaskClassifiedPayload(
                intent="chat",
                domain="chat",
                subtasks=[{"tool": "chat_response", "tool_input": {"prompt": command}}],
                confidence=classification.get("confidence", 0.9),
            )
        elif task_type == "vision_task":
            payload = TaskClassifiedPayload(
                intent="vision_analysis",
                domain="vision",
                subtasks=[{"tool": "analyze_screen", "tool_input": {"prompt": command}}],
                confidence=classification.get("confidence", 0.85),
            )
        elif task_type == "coding_task":
            payload = TaskClassifiedPayload(
                intent="code_execution",
                domain="coding",
                subtasks=[{"tool": "run_shell_command", "tool_input": {"command": command}}],
                confidence=classification.get("confidence", 0.85),
            )
        else:
            # Full decomposition for complex multi-step tasks
            try:
                subtasks = await planner_agent.decompose_goal(command)
                domain = "pc_tools"
                payload = TaskClassifiedPayload(
                    intent="complex_plan",
                    domain=domain,
                    subtasks=subtasks if isinstance(subtasks, list) else [],
                    confidence=0.8,
                )
            except Exception as e:
                logger.warning(f"[RouterWorker] Planner decomposition fallback: {e}")
                payload = TaskClassifiedPayload(
                    intent="generic_execution",
                    domain="pc_tools",
                    subtasks=[{"tool": "run_shell_command", "tool_input": {"command": command}}],
                    confidence=0.5,
                )

        out_event = NexusEvent(
            event_type=EventType.TASK_CLASSIFIED,
            task_id=event.task_id,
            user_id=event.user_id,
            source_agent=self.name,
            payload=payload.model_dump(),
        )
        await task_tracker.update_task_from_event(out_event)
        return [out_event]


# Global instance
router_worker = RouterWorker()
