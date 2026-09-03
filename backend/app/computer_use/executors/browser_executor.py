"""
Browser DOM Executor — Playwright and DOM-level automation.
Interacts directly with web page elements via selectors, text matching, and DOM APIs.
"""
import time
import asyncio
import logging
from typing import Dict, Any, Optional

from app.computer_use.models import ActionRequest, ActionResult, ActionType, ExecutionMethod
from app.computer_use.executors.base import BaseExecutor

logger = logging.getLogger(__name__)


class BrowserDOMExecutor(BaseExecutor):
    """Executes actions against web browsers and DOM structures using Playwright."""

    def __init__(self):
        super().__init__(ExecutionMethod.BROWSER_DOM)

    def can_handle(self, request: ActionRequest) -> bool:
        """Determines if the action is targeted at browser navigation or web DOM."""
        if request.action == ActionType.NAVIGATE:
            return True
        if request.action in (ActionType.CLICK_ELEMENT, ActionType.TYPE_ELEMENT) and (
            request.metadata.get("in_browser") or (request.target and request.target.startswith(("#", ".", "//", "text=", "role=")))
        ):
            return True
        return False

    async def execute(self, request: ActionRequest) -> ActionResult:
        start_time = time.monotonic()
        action = request.action
        target = request.target or ""

        try:
            # 1. Navigate URL
            if action == ActionType.NAVIGATE:
                return await self._navigate(target, request, start_time)

            # 2. Click DOM Element
            elif action == ActionType.CLICK_ELEMENT:
                return await self._click_element(target, request, start_time)

            # 3. Type into DOM Element
            elif action == ActionType.TYPE_ELEMENT:
                return await self._type_element(target, request.text_val or "", request, start_time)

            else:
                return ActionResult(
                    success=False,
                    action=action,
                    target=target,
                    executor_used=self.method,
                    error=f"Unsupported browser action: {action}",
                    duration_ms=(time.monotonic() - start_time) * 1000,
                )

        except Exception as e:
            logger.warning(f"[BrowserExecutor] DOM action {action} failed: {e}")
            return ActionResult(
                success=False,
                action=action,
                target=target,
                executor_used=self.method,
                error=str(e),
                duration_ms=(time.monotonic() - start_time) * 1000,
            )

    async def _navigate(self, url: str, request: ActionRequest, start: float) -> ActionResult:
        clean_url = url if url.startswith("http") else f"https://{url}"
        browser_choice = request.metadata.get("browser", "chrome")

        # Try Playwright if active session exists
        try:
            from app.browser.playwright_manager import playwright_manager
            page = await playwright_manager.get_current_page()
            if page:
                await page.goto(clean_url, timeout=15000)
                title = await page.title()
                return ActionResult(
                    success=True,
                    action=ActionType.NAVIGATE,
                    target=clean_url,
                    executor_used=self.method,
                    window_title=title,
                    output=f"Navigated Playwright page to '{clean_url}'",
                    duration_ms=(time.monotonic() - start) * 1000,
                )
        except Exception as pe:
            logger.debug(f"[BrowserExecutor] Playwright direct navigation not available: {pe}")

        # Fallback to desktop browser opening
        import webbrowser
        import subprocess
        try:
            webbrowser.open(clean_url)
        except Exception:
            subprocess.Popen(f'start "" "{clean_url}"', shell=True)

        return ActionResult(
            success=True,
            action=ActionType.NAVIGATE,
            target=clean_url,
            executor_used=self.method,
            output=f"Opened '{clean_url}' in default browser",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _click_element(self, selector: str, request: ActionRequest, start: float) -> ActionResult:
        try:
            from app.browser.playwright_manager import playwright_manager
            page = await playwright_manager.get_current_page()
            if not page:
                return ActionResult(
                    success=False,
                    action=ActionType.CLICK_ELEMENT,
                    target=selector,
                    executor_used=self.method,
                    error="No active Playwright browser page session found",
                    duration_ms=(time.monotonic() - start) * 1000,
                )

            # Try direct selector click
            await page.click(selector, timeout=5000)
            return ActionResult(
                success=True,
                action=ActionType.CLICK_ELEMENT,
                target=selector,
                executor_used=self.method,
                output=f"Clicked DOM element '{selector}'",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action=ActionType.CLICK_ELEMENT,
                target=selector,
                executor_used=self.method,
                error=f"DOM element '{selector}' not found or not clickable: {e}",
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def _type_element(self, selector: str, text: str, request: ActionRequest, start: float) -> ActionResult:
        try:
            from app.browser.playwright_manager import playwright_manager
            page = await playwright_manager.get_current_page()
            if not page:
                return ActionResult(
                    success=False,
                    action=ActionType.TYPE_ELEMENT,
                    target=selector,
                    executor_used=self.method,
                    error="No active Playwright browser page session found",
                    duration_ms=(time.monotonic() - start) * 1000,
                )

            await page.fill(selector, text, timeout=5000)
            if request.metadata.get("press_enter"):
                await page.keyboard.press("Enter")

            return ActionResult(
                success=True,
                action=ActionType.TYPE_ELEMENT,
                target=selector,
                executor_used=self.method,
                output=f"Typed '{text}' into DOM element '{selector}'",
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as e:
            return ActionResult(
                success=False,
                action=ActionType.TYPE_ELEMENT,
                target=selector,
                executor_used=self.method,
                error=f"Failed to type into DOM element '{selector}': {e}",
                duration_ms=(time.monotonic() - start) * 1000,
            )
