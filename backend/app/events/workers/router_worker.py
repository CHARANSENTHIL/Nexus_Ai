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

        import re
        cmd_lower = command.lower().strip()

        # ── Fast Intercept: Blender 3D Scene / Animation ──────────────────────
        if "blender" in cmd_lower or any(w in cmd_lower for w in ("create 3d", "make 3d", "render 3d", "3d animation", "3d scene", "3d model")):
            blend_match = re.search(r"(\w+)\.blend", command, re.IGNORECASE)
            fname = f"{blend_match.group(1)}.blend" if blend_match else "scene.blend"
            is_anim = any(w in cmd_lower for w in ("animation", "animate", "moving", "video", "frames"))
            subtasks = [{
                "id": "task_1",
                "title": f"Create 3D Blender Scene: {command[:40]}",
                "description": f"Generate procedural 3D scene in Blender with bpy and render: {command}",
                "agent": "application",
                "tool": "create_blender_scene",
                "tool_input": {
                    "prompt": command,
                    "filename": fname,
                    "render_image": True,
                    "is_animation": is_anim,
                },
                "dependencies": [],
                "risk_level": "low",
                "requires_approval": False,
            }]
            payload = TaskClassifiedPayload(
                intent="blender_3d_generation",
                domain="pc_tools",
                subtasks=subtasks,
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

        # ── Tier 1: Keyword Fast Path (0ms) ──────────────────────────────────
        keyword_subtasks = IntentRouter.detect(command)
        if keyword_subtasks:
            domain = "pc_tools"
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
                plan = await planner_agent.decompose_goal(command)
                extracted_subtasks = []
                if hasattr(plan, "task_graph") and plan.task_graph:
                    node_order = plan.task_graph.execution_order or list(plan.task_graph.nodes.keys())
                    for nid in node_order:
                        node = plan.task_graph.nodes.get(nid)
                        if node:
                            agent_val = getattr(node.assigned_agent, "value", str(node.assigned_agent))
                            extracted_subtasks.append({
                                "id": node.id,
                                "title": node.title,
                                "description": node.description,
                                "agent": str(agent_val),
                                "tool": node.input_data.get("tool", "run_shell_command"),
                                "tool_input": node.input_data.get("tool_input", {}),
                                "requires_approval": nid in (getattr(plan, "approval_actions", []) or []) or node.input_data.get("risk_level") in ("high", "critical"),
                            })
                elif isinstance(plan, list):
                    extracted_subtasks = plan
                
                if not extracted_subtasks:
                    extracted_subtasks = [{"tool": "run_shell_command", "tool_input": {"command": command}}]

                domain = "pc_tools"
                payload = TaskClassifiedPayload(
                    intent="complex_plan",
                    domain=domain,
                    subtasks=extracted_subtasks,
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
