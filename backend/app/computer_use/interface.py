"""
ComputerInterface — Universal standard language between AI Agents and the Computer.
Exposes high-level semantic capabilities, delegating execution to the ExecutionRouter.
"""
import logging
from typing import Dict, Any, List, Optional, Tuple, Union

from app.computer_use.models import ActionRequest, ActionResult, ActionType, ExecutionMethod
from app.computer_use.router import ExecutionRouter

logger = logging.getLogger(__name__)


class ComputerInterface:
    """
    Universal Computer Use Interface.
    Agents interact through semantic capability methods; the underlying Execution Router
    determines the optimal execution method (Windows API, Playwright DOM, or Vision GUI).
    """

    def __init__(self, router: Optional[ExecutionRouter] = None):
        self.router = router or ExecutionRouter()

    async def execute_action(self, request: ActionRequest) -> ActionResult:
        """Core execution pipeline for any ActionRequest."""
        return await self.router.route_and_execute(request)

    # ── High-Level Semantic Capabilities ───────────────────────────────────────

    async def open_application(self, app_name: str, args: str = "") -> ActionResult:
        """Start a desktop application via native OS process API."""
        req = ActionRequest(
            action=ActionType.OPEN_APP,
            target=app_name,
            text_val=args,
        )
        return await self.execute_action(req)

    async def close_application(self, app_name: str) -> ActionResult:
        """Terminate an application by process name via native OS API."""
        req = ActionRequest(
            action=ActionType.CLOSE_APP,
            target=app_name,
        )
        return await self.execute_action(req)

    async def navigate(self, url: str, browser: str = "chrome") -> ActionResult:
        """Navigate to a web URL (Playwright DOM or default browser)."""
        req = ActionRequest(
            action=ActionType.NAVIGATE,
            target=url,
            metadata={"browser": browser},
        )
        return await self.execute_action(req)

    async def click(self, x: int, y: int) -> ActionResult:
        """Perform a mouse click at screen coordinates (x, y)."""
        req = ActionRequest(
            action=ActionType.CLICK,
            coordinates=(x, y),
        )
        return await self.execute_action(req)

    async def click_element(self, target: str, in_browser: bool = False) -> ActionResult:
        """Click a named UI element or DOM selector (tries DOM first, then Vision OCR)."""
        req = ActionRequest(
            action=ActionType.CLICK_ELEMENT,
            target=target,
            metadata={"in_browser": in_browser},
        )
        return await self.execute_action(req)

    async def double_click(self, x: int, y: int) -> ActionResult:
        """Perform a double click at screen coordinates (x, y)."""
        req = ActionRequest(
            action=ActionType.DOUBLE_CLICK,
            coordinates=(x, y),
        )
        return await self.execute_action(req)

    async def right_click(self, x: int, y: int) -> ActionResult:
        """Perform a right click at screen coordinates (x, y)."""
        req = ActionRequest(
            action=ActionType.RIGHT_CLICK,
            coordinates=(x, y),
        )
        return await self.execute_action(req)

    async def type(self, text: str, press_enter: bool = False) -> ActionResult:
        """Type text into the currently active window or focused field."""
        req = ActionRequest(
            action=ActionType.TYPE,
            text_val=text,
            metadata={"press_enter": press_enter},
        )
        return await self.execute_action(req)

    async def type_element(self, target: str, text: str, press_enter: bool = False) -> ActionResult:
        """Type text into a specific target element or DOM selector."""
        req = ActionRequest(
            action=ActionType.TYPE_ELEMENT,
            target=target,
            text_val=text,
            metadata={"press_enter": press_enter},
        )
        return await self.execute_action(req)

    async def press(self, key: str) -> ActionResult:
        """Press a single keyboard key (e.g. 'enter', 'tab', 'escape')."""
        req = ActionRequest(
            action=ActionType.PRESS,
            target=key,
        )
        return await self.execute_action(req)

    async def hotkey(self, *keys: str) -> ActionResult:
        """Trigger a keyboard combination (e.g. 'ctrl', 'c' or 'alt', 'tab')."""
        req = ActionRequest(
            action=ActionType.HOTKEY,
            keys=list(keys),
        )
        return await self.execute_action(req)

    async def scroll(self, amount: int = -300) -> ActionResult:
        """Scroll vertical wheel units (positive up, negative down)."""
        req = ActionRequest(
            action=ActionType.SCROLL,
            amount=amount,
        )
        return await self.execute_action(req)

    async def move(self, x: int, y: int) -> ActionResult:
        """Move cursor to screen coordinates (x, y)."""
        req = ActionRequest(
            action=ActionType.MOVE,
            coordinates=(x, y),
        )
        return await self.execute_action(req)

    async def screenshot(self) -> ActionResult:
        """Capture display screenshot via mss."""
        req = ActionRequest(
            action=ActionType.SCREENSHOT,
        )
        return await self.execute_action(req)

    async def get_active_window(self) -> ActionResult:
        """Get the title of the currently focused foreground window."""
        req = ActionRequest(
            action=ActionType.GET_ACTIVE_WINDOW,
        )
        return await self.execute_action(req)

    async def get_system_state(self) -> ActionResult:
        """Get CPU, RAM, Disk, and Battery metrics natively via psutil."""
        req = ActionRequest(
            action=ActionType.GET_SYSTEM_STATE,
        )
        return await self.execute_action(req)

    async def set_system_volume(self, level: int) -> ActionResult:
        """Set audio volume (0-100) via native Windows audio API."""
        req = ActionRequest(
            action=ActionType.SET_VOLUME,
            amount=level,
        )
        return await self.execute_action(req)

    async def set_system_brightness(self, level: int) -> ActionResult:
        """Set screen brightness (0-100) via WMI API."""
        req = ActionRequest(
            action=ActionType.SET_BRIGHTNESS,
            amount=level,
        )
        return await self.execute_action(req)

    async def set_system_power(self, power_action: str) -> ActionResult:
        """Control system power: 'lock', 'sleep', 'shutdown', 'restart'."""
        req = ActionRequest(
            action=ActionType.SET_POWER,
            target=power_action,
        )
        return await self.execute_action(req)

    async def run_command(self, command: str, cwd: str = ".", timeout_seconds: float = 30.0) -> ActionResult:
        """Execute a shell command asynchronously via subprocess."""
        req = ActionRequest(
            action=ActionType.RUN_COMMAND,
            target=command,
            timeout_seconds=timeout_seconds,
            metadata={"cwd": cwd},
        )
        return await self.execute_action(req)


# Default global singleton instance
computer = ComputerInterface()
