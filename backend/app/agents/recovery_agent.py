"""
Recovery Agent — Bounded, deterministic recovery strategies for failed actions.

Strategy table (by attempt number):
  Attempt 1: Wait 2s and retry the same action unchanged.
  Attempt 2: Inspect window/process state; adjust coordinates or re-focus; retry.
  Attempt 3: Hard restart (close browser tab / relaunch app); retry from scratch.
  > 3:       Escalate — send Telegram interactive message to user.

MAX_ATTEMPTS = 3 (hard cap before escalation)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional

from app.agents.action_observation import Action, Observation

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
TELEGRAM_BOT_TOKEN = "8425363554:AAFTlzacQNTIGuX9GJirOajGD8KuWH4R7Fk"
TELEGRAM_USER_ID = "7074735945"


class RecoveryStrategy(str, Enum):
    WAIT_RETRY = "wait_retry"           # attempt 1: pause and retry
    INSPECT_RETRY = "inspect_retry"     # attempt 2: re-focus / adjust coordinates
    RESTART_RETRY = "restart_retry"     # attempt 3: hard restart browser/app
    ESCALATE = "escalate"               # > 3: ask user via Telegram


@dataclass
class RecoveryDecision:
    strategy: RecoveryStrategy
    action: Action                   # possibly modified action to retry
    message: str = ""                # human-readable description of what we're doing
    execute: Optional[Callable] = field(default=None, repr=False)  # coroutine factory


class RecoveryAgent:
    """
    Receives a failed action + the post-action observation + attempt number.
    Returns a RecoveryDecision describing what to do next.

    The ActionPipeline calls decision.execute() (an async no-arg coroutine)
    before re-running the action, so each strategy can perform side-effects
    (sleep, click, restart, Telegram message) independently.
    """

    async def handle(
        self,
        action: Action,
        observation: Observation,
        attempt: int,
    ) -> RecoveryDecision:
        """Choose and return the appropriate recovery strategy."""
        logger.info(
            f"[RecoveryAgent] Handling failed action '{action.description}' "
            f"(attempt {attempt}/{MAX_ATTEMPTS})"
        )

        if attempt > MAX_ATTEMPTS:
            return await self._escalate(action, observation, attempt)

        if attempt == 1:
            return self._wait_retry(action)
        elif attempt == 2:
            return await self._inspect_retry(action, observation)
        else:  # attempt == 3
            return await self._restart_retry(action, observation)

    # ── Strategy 1: Wait + Retry ────────────────────────────────────────────────
    def _wait_retry(self, action: Action) -> RecoveryDecision:
        msg = f"⏳ Waiting 2s then retrying '{action.description}'..."
        logger.info(f"[RecoveryAgent] Strategy: WAIT_RETRY — {msg}")

        async def _do_wait():
            await asyncio.sleep(2.0)

        return RecoveryDecision(
            strategy=RecoveryStrategy.WAIT_RETRY,
            action=action,
            message=msg,
            execute=_do_wait,
        )

    # ── Strategy 2: Inspect & Re-focus ─────────────────────────────────────────
    async def _inspect_retry(self, action: Action, obs: Observation) -> RecoveryDecision:
        msg = f"🔍 Inspecting state and re-focusing for '{action.description}'..."
        logger.info(f"[RecoveryAgent] Strategy: INSPECT_RETRY — {msg}")

        async def _do_inspect():
            try:
                # Re-click screen center to focus the OS window
                import pyautogui
                import ctypes
                screen_w = ctypes.windll.user32.GetSystemMetrics(0)
                screen_h = ctypes.windll.user32.GetSystemMetrics(1)
                center_x, center_y = screen_w // 2, screen_h // 2
                logger.info(f"[RecoveryAgent] Re-focusing: clicking screen center ({center_x}, {center_y})")
                pyautogui.click(center_x, center_y)
                await asyncio.sleep(1.0)

                # If it's a browser action, try Playwright reload
                if any(k in action.expected_state for k in ("url_contains", "page_title_contains")):
                    try:
                        from app.browser.playwright_manager import playwright_manager
                        if playwright_manager._page:
                            await playwright_manager._page.reload(wait_until="domcontentloaded", timeout=10000)
                            logger.info("[RecoveryAgent] Playwright page reloaded.")
                    except Exception as e:
                        logger.warning(f"[RecoveryAgent] Page reload failed: {e}")

            except Exception as e:
                logger.warning(f"[RecoveryAgent] Inspect/refocus error: {e}")
            await asyncio.sleep(1.5)

        return RecoveryDecision(
            strategy=RecoveryStrategy.INSPECT_RETRY,
            action=action,
            message=msg,
            execute=_do_inspect,
        )

    # ── Strategy 3: Hard Restart ────────────────────────────────────────────────
    async def _restart_retry(self, action: Action, obs: Observation) -> RecoveryDecision:
        msg = f"🔄 Hard restarting browser/app for '{action.description}'..."
        logger.info(f"[RecoveryAgent] Strategy: RESTART_RETRY — {msg}")

        async def _do_restart():
            try:
                from app.browser.playwright_manager import playwright_manager
                # Close existing browser
                await playwright_manager.close_browser()
                await asyncio.sleep(1.0)
                # Reopen browser
                await playwright_manager.initialize(browser_name="chromium", headless=False)
                await asyncio.sleep(2.0)

                # If the action had a URL target, navigate there directly
                url = (action.arguments.get("url") or
                       action.expected_state.get("url_contains", ""))
                if url:
                    if not url.startswith("http"):
                        url = "https://" + url
                    logger.info(f"[RecoveryAgent] Navigating to {url} after restart")
                    await playwright_manager.open_url(url)
                    await asyncio.sleep(2.0)
            except Exception as e:
                logger.warning(f"[RecoveryAgent] Hard restart error: {e}")

        return RecoveryDecision(
            strategy=RecoveryStrategy.RESTART_RETRY,
            action=action,
            message=msg,
            execute=_do_restart,
        )

    # ── Strategy 4: Escalate to User via Telegram ───────────────────────────────
    async def _escalate(self, action: Action, obs: Observation, attempt: int) -> RecoveryDecision:
        msg = (
            f"🆘 Action '{action.description}' failed after {MAX_ATTEMPTS} attempts. "
            f"Asking user for help via Telegram."
        )
        logger.warning(f"[RecoveryAgent] {msg}")

        async def _do_escalate():
            await _send_telegram_escalation(action, attempt)

        return RecoveryDecision(
            strategy=RecoveryStrategy.ESCALATE,
            action=action,
            message=msg,
            execute=_do_escalate,
        )


async def _send_telegram_escalation(action: Action, attempt: int) -> None:
    """Send an interactive Telegram message with recovery options."""
    import httpx
    text = (
        f"🆘 *Nexus AI Recovery Needed*\n\n"
        f"Action: `{action.description}`\n"
        f"Tool: `{action.tool}`\n"
        f"Failed after *{attempt}* attempts.\n\n"
        f"Please choose how to proceed:"
    )
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🔄 Retry", "callback_data": f"recovery_retry_{action.id}"},
                {"text": "⏭ Skip", "callback_data": f"recovery_skip_{action.id}"},
            ],
            [
                {"text": "🛑 Abort task", "callback_data": f"recovery_abort_{action.id}"},
            ],
        ]
    }
    payload = {
        "chat_id": TELEGRAM_USER_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": keyboard,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json=payload,
            )
            if resp.status_code == 200:
                logger.info("[RecoveryAgent] Escalation message sent to Telegram.")
            else:
                logger.warning(f"[RecoveryAgent] Telegram escalation failed: {resp.text}")
    except Exception as e:
        logger.error(f"[RecoveryAgent] Escalation Telegram send error: {e}")


# Singleton
recovery_agent = RecoveryAgent()
