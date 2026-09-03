"""
Execution Router — Decides the optimal executor based on priority hierarchy:
Native OS API -> Browser DOM (Playwright) -> Vision GUI (PyAutoGUI).
"""
import logging
from typing import Dict, Any, List, Optional

from app.computer_use.models import ActionRequest, ActionResult, ActionType, ExecutionMethod
from app.computer_use.executors.base import BaseExecutor
from app.computer_use.executors.windows_executor import WindowsNativeExecutor
from app.computer_use.executors.browser_executor import BrowserDOMExecutor
from app.computer_use.executors.vision_gui_executor import VisionGUIExecutor

logger = logging.getLogger(__name__)


class ExecutionRouter:
    """Intelligent router directing action requests to the highest-reliability technology layer."""

    def __init__(self):
        self.windows_executor = WindowsNativeExecutor()
        self.browser_executor = BrowserDOMExecutor()
        self.vision_executor = VisionGUIExecutor()

        # Priority chain: Native OS -> Browser DOM -> Vision GUI
        self.executors: List[BaseExecutor] = [
            self.windows_executor,
            self.browser_executor,
            self.vision_executor,
        ]

    def select_executor(self, request: ActionRequest) -> BaseExecutor:
        """
        Select the best executor for the requested action based on priority strategy.
        If user or agent explicitly specifies preferred_method, honors that preference.
        """
        if request.preferred_method:
            for ex in self.executors:
                if ex.method == request.preferred_method:
                    return ex

        # 1. Check Native OS API
        if self.windows_executor.can_handle(request):
            return self.windows_executor

        # 2. Check Browser DOM
        if self.browser_executor.can_handle(request):
            return self.browser_executor

        # 3. Fallback to Vision GUI
        return self.vision_executor

    async def route_and_execute(self, request: ActionRequest) -> ActionResult:
        """Route action to optimal executor with automatic fallback to Vision GUI on DOM failure."""
        primary_executor = self.select_executor(request)
        logger.info(
            f"[ExecutionRouter] Routing action '{request.action.value}' "
            f"(target='{request.target}') to executor: {primary_executor.method.value}"
        )

        result = await primary_executor.execute(request)

        # Automatic fallback: If Browser DOM failed to find element, fallback to Vision GUI
        if not result.success and primary_executor.method == ExecutionMethod.BROWSER_DOM:
            logger.info(
                f"[ExecutionRouter] Primary executor {primary_executor.method.value} failed. "
                f"Attempting visual fallback via {self.vision_executor.method.value}..."
            )
            fallback_result = await self.vision_executor.execute(request)
            fallback_result.metadata["fallback_from"] = primary_executor.method.value
            return fallback_result

        return result
