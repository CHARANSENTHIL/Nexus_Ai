"""
Browser Agent Worker: Listens for ACTION_APPROVED and executes Web/Browser automation.
"""
import asyncio
import logging
import time
from typing import List

from app.browser.playwright_manager import playwright_manager
from app.browser.browser_work_agent import browser_work_agent
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
            goal = tool_input.get("goal") or tool_input.get("objective") or action

            if action == "run_autonomous_browser_workflow":
                res_dict = await browser_work_agent.run_objective(
                    goal=goal,
                    initial_url=tool_input.get("url"),
                    task_id=event.task_id,
                    user_id=event.user_id,
                )
                res = res_dict.get("summary", "Browser workflow finished.")
            elif action == "inject_domain_credentials":
                res_dict = await playwright_manager.inject_credentials(tool_input.get("domain"))
                res = f"Credential injection: {res_dict}"
            elif action == "autofill_profile_form":
                res_dict = await playwright_manager.autofill_profile_fields()
                res = f"Autofilled profile fields: {res_dict}"
            elif action in ("open_url_in_browser", "open_url", "browse"):
                from app.agents.tools.app_tools import open_url_in_browser
                fn = getattr(open_url_in_browser, "func", open_url_in_browser)
                res = await asyncio.to_thread(fn, url)
                if isinstance(res, dict):
                    res = res.get("message", f"Opened {url} in browser")
            elif action == "download_images_from_web":
                from app.agents.tools.app_tools import download_images_from_web
                fn = getattr(download_images_from_web, "func", download_images_from_web)
                query_val = tool_input.get("query", url)
                count_val = tool_input.get("count", 3)
                res = await asyncio.to_thread(fn, query=query_val, count=count_val)
                if isinstance(res, dict):
                    res = res.get("message", f"Downloaded images for {query_val}")
            elif action == "search_web":
                res = await playwright_manager.search_web(url)
            elif action == "click_element":
                res = await playwright_manager.click_element(tool_input.get("selector", ""))
            elif action == "fill_form":
                res = await playwright_manager.fill_form(tool_input.get("selector", ""), tool_input.get("value", ""))
            elif action == "read_page":
                res = await playwright_manager.read_page()
            else:
                from app.agents.tools.app_tools import open_url_in_browser
                fn = getattr(open_url_in_browser, "func", open_url_in_browser)
                res = await asyncio.to_thread(fn, url)
                if isinstance(res, dict):
                    res = res.get("message", f"Opened {url} in browser")

            duration_ms = (time.time() - start_time) * 1000
            comp_payload = ActionCompletedPayload(
                action=action,
                result=res or f"Browser action '{action}' completed.",
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
                payload={"final_output": f"🌐 Browser action '{action}' completed successfully: {res}"},
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
