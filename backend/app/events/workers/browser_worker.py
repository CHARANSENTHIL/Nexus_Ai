"""
Browser Agent Worker: Listens for ACTION_APPROVED and executes Web/Browser automation.
"""
import asyncio
import logging
import time
from typing import List


from app.browser.playwright_manager import playwright_manager
from app.events.agent_worker import AgentWorker
from app.events.event_models import (
    ActionCompletedPayload,
    ActionFailedPayload,
    EventType,
    NexusEvent,
)
from app.events.task_tracker import task_tracker

logger = logging.getLogger(__name__)


class BrowserWorker(AgentWorker):
    name = "browser_agent"
    listen_stream = "action_events"
    consumer_group = "browser_group"
    listen_event_types = [EventType.ACTION_APPROVED]

    async def handle_event(self, event: NexusEvent) -> List[NexusEvent]:
        domain = event.payload.get("domain", "pc_tools")
        action = event.payload.get("action", "")
        if domain != "browser" and "browser" not in action and "url" not in action:
            return []

        tool_input = event.payload.get("tool_input", {})
        subtask_idx = event.payload.get("subtask_index", 0)
        start_time = time.time()

        logger.info(f"[BrowserWorker] 🌐 Executing browser action '{action}' with input: {tool_input}")

        try:
            url = tool_input.get("url") or tool_input.get("query") or "https://www.google.com"
            if action in ("open_url_in_browser", "open_url", "browse"):
                from app.agents.tools.app_tools import open_url_in_browser
                fn = getattr(open_url_in_browser, "func", open_url_in_browser)
                res = await asyncio.to_thread(fn, url)
                if isinstance(res, dict):
                    res = res.get("message", f"Opened {url} in browser")
            elif action == "search_web":
                res = await playwright_manager.search_web(url)
            else:
                from app.agents.tools.app_tools import open_url_in_browser
                fn = getattr(open_url_in_browser, "func", open_url_in_browser)
                res = await asyncio.to_thread(fn, url)
                if isinstance(res, dict):
                    res = res.get("message", f"Opened {url} in browser")



            duration_ms = (time.time() - start_time) * 1000
            comp_payload = ActionCompletedPayload(
                action=action,
                result=res or f"Opened browser URL: {url}",
                success=True,
                duration_ms=duration_ms,
                subtask_index=subtask_idx,
            )
            comp_evt = NexusEvent(
                event_type=EventType.ACTION_COMPLETED,
                task_id=event.task_id,
                user_id=event.user_id,
                source_agent=self.name,
                payload=comp_payload.model_dump(),
            )
            await task_tracker.update_task_from_event(comp_evt)

            task_comp_evt = NexusEvent(
                event_type=EventType.TASK_COMPLETED,
                task_id=event.task_id,
                user_id=event.user_id,
                source_agent=self.name,
                payload={"final_output": f"🌐 Browser action '{action}' completed successfully: {url}"},
            )
            await task_tracker.update_task_from_event(task_comp_evt)
            return [comp_evt, task_comp_evt]

        except Exception as e:
            logger.error(f"[BrowserWorker] Browser action failed: {e}")
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


# Global instance
browser_worker = BrowserWorker()
