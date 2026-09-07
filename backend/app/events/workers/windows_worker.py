"""
Windows Agent Worker: Listens for ACTION_APPROVED and executes PC/System tools.
"""
import asyncio
import logging
import time
from typing import List

from app.agents.planner import _build_tool_registry, _format_tool_result
from app.agents.self_healing_pipeline import self_healing_pipeline
from app.events.agent_worker import AgentWorker
from app.events.event_models import (
    ActionCompletedPayload,
    ActionFailedPayload,
    EventType,
    NexusEvent,
)
from app.events.task_tracker import task_tracker

logger = logging.getLogger(__name__)


class WindowsWorker(AgentWorker):
    name = "windows_agent"
    listen_stream = "action_events"
    consumer_group = "windows_group"
    listen_event_types = [EventType.ACTION_APPROVED]

    async def handle_event(self, event: NexusEvent) -> List[NexusEvent]:
        domain = event.payload.get("domain", "pc_tools")
        if domain not in ("pc_tools", "coding", "chat"):
            # Not a Windows/PC/Chat action (handled by Browser/Vision worker)
            return []

        action = event.payload.get("action", "")
        tool_input = event.payload.get("tool_input", {})
        subtask_idx = event.payload.get("subtask_index", 0)

        start_time = time.time()
        registry = _build_tool_registry()
        fn = registry.get(action)

        logger.info(f"[WindowsWorker] ⚙️ Executing action '{action}' with input: {tool_input}")

        # ── Conversational Chat Action ──────────────────────────────────────────
        if action == "chat_response" or domain == "chat":
            prompt = tool_input.get("prompt", "") if isinstance(tool_input, dict) else str(tool_input)
            from app.agents.chat_agent import chat_agent
            user_name = event.user_id if event.user_id != "system" else "User"
            chat_text = await chat_agent.generate_response(prompt, user_name=user_name)

            if any(w in prompt.lower() for w in ("hi", "hello", "hey", "hola", "greetings")):
                if "offline" in chat_text.lower():
                    chat_text = (
                        "👋 Hello! I am **Nexus AI**, your autonomous desktop assistant.\n\n"
                        "How can I help you today? You can ask me to:\n"
                        "- Open apps or browse websites (`open chrome and search YouTube`)\n"
                        "- Solve LeetCode problems from screenshots\n"
                        "- Check system health, CPU/RAM/Disk, and manage background tasks"
                    )

            duration_ms = (time.time() - start_time) * 1000
            completed_payload = ActionCompletedPayload(
                action=action,
                result=chat_text,
                success=True,
                duration_ms=duration_ms,
                subtask_index=subtask_idx,
            )
            comp_evt = NexusEvent(
                event_type=EventType.ACTION_COMPLETED,
                task_id=event.task_id,
                user_id=event.user_id,
                source_agent=self.name,
                payload=completed_payload.model_dump(),
            )
            await task_tracker.update_task_from_event(comp_evt)

            task_comp_evt = NexusEvent(
                event_type=EventType.TASK_COMPLETED,
                task_id=event.task_id,
                user_id=event.user_id,
                source_agent=self.name,
                payload={"final_output": chat_text},
            )
            await task_tracker.update_task_from_event(task_comp_evt)
            return [comp_evt, task_comp_evt]


        # ── Shell Execution with Self-Healing ──────────────────────────────────
        if action == "run_shell_command":
            cmd = tool_input.get("command", "") if isinstance(tool_input, dict) else str(tool_input)
            heal_res = await self_healing_pipeline.run(
                command=cmd,
                goal=f"Execute: {cmd}",
                user_id=event.user_id,
            )
            duration_ms = (time.time() - start_time) * 1000

            if heal_res.get("success"):
                completed_payload = ActionCompletedPayload(
                    action=action,
                    result=heal_res.get("output", "Command executed successfully."),
                    success=True,
                    duration_ms=duration_ms,
                    subtask_index=subtask_idx,
                )
                comp_evt = NexusEvent(
                    event_type=EventType.ACTION_COMPLETED,
                    task_id=event.task_id,
                    user_id=event.user_id,
                    source_agent=self.name,
                    payload=completed_payload.model_dump(),
                )
                await task_tracker.update_task_from_event(comp_evt)

                # Also emit TASK_COMPLETED
                task_comp_evt = NexusEvent(
                    event_type=EventType.TASK_COMPLETED,
                    task_id=event.task_id,
                    user_id=event.user_id,
                    source_agent=self.name,
                    payload={"final_output": heal_res.get("output", "Task completed successfully.")},
                )
                await task_tracker.update_task_from_event(task_comp_evt)
                return [comp_evt, task_comp_evt]

            else:
                fail_payload = ActionFailedPayload(
                    action=action,
                    error=heal_res.get("error", "Execution failed."),
                    subtask_index=subtask_idx,
                )
                fail_evt = NexusEvent(
                    event_type=EventType.ACTION_FAILED,
                    task_id=event.task_id,
                    user_id=event.user_id,
                    source_agent=self.name,
                    payload=fail_payload.model_dump(),
                )
                await task_tracker.update_task_from_event(fail_evt)
                return [fail_evt]

        # ── Standard System / App Tools ─────────────────────────────────────────
        if fn:
            try:
                res = await asyncio.to_thread(fn, **tool_input) if isinstance(tool_input, dict) else await asyncio.to_thread(fn, tool_input)
                duration_ms = (time.time() - start_time) * 1000
                formatted = _format_tool_result(action, res)

                completed_payload = ActionCompletedPayload(
                    action=action,
                    result=formatted,
                    success=True,
                    duration_ms=duration_ms,
                    subtask_index=subtask_idx,
                )
                comp_evt = NexusEvent(
                    event_type=EventType.ACTION_COMPLETED,
                    task_id=event.task_id,
                    user_id=event.user_id,
                    source_agent=self.name,
                    payload=completed_payload.model_dump(),
                )
                await task_tracker.update_task_from_event(comp_evt)

                task_comp_evt = NexusEvent(
                    event_type=EventType.TASK_COMPLETED,
                    task_id=event.task_id,
                    user_id=event.user_id,
                    source_agent=self.name,
                    payload={"final_output": formatted},
                )
                await task_tracker.update_task_from_event(task_comp_evt)
                return [comp_evt, task_comp_evt]

            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                fail_payload = ActionFailedPayload(
                    action=action,
                    error=str(e),
                    subtask_index=subtask_idx,
                )
                fail_evt = NexusEvent(
                    event_type=EventType.ACTION_FAILED,
                    task_id=event.task_id,
                    user_id=event.user_id,
                    source_agent=self.name,
                    payload=fail_payload.model_dump(),
                )
                await task_tracker.update_task_from_event(fail_evt)
                return [fail_evt]

        # Fallback if tool not registered
        fail_payload = ActionFailedPayload(
            action=action,
            error=f"Tool '{action}' not found in registry.",
            subtask_index=subtask_idx,
        )
        fail_evt = NexusEvent(
            event_type=EventType.ACTION_FAILED,
            task_id=event.task_id,
            user_id=event.user_id,
            source_agent=self.name,
            payload=fail_payload.model_dump(),
        )
        await task_tracker.update_task_from_event(fail_evt)
        return [fail_evt]


# Global instance
windows_worker = WindowsWorker()
