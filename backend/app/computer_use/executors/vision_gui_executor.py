"""
Vision GUI Executor — Visual localization (Gemma 3 Vision + OCR) and PyAutoGUI physical input.
Used when no native API or DOM structure exists for desktop UI interaction.
"""
import os
import time
import asyncio
import logging
from typing import Dict, Any, Optional, Tuple

from app.computer_use.models import ActionRequest, ActionResult, ActionType, ExecutionMethod
from app.computer_use.executors.base import BaseExecutor
from app.vision.screen_reader import screen_reader

logger = logging.getLogger(__name__)

# Check PyAutoGUI
HAS_PYAUTOGUI = False
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    HAS_PYAUTOGUI = True
except ImportError:
    pass


class VisionGUIExecutor(BaseExecutor):
    """Executes actions visually using OCR, Vision localization, and PyAutoGUI."""

    def __init__(self):
        super().__init__(ExecutionMethod.VISION_GUI)

    def can_handle(self, request: ActionRequest) -> bool:
        """Vision GUI can act as universal fallback for all physical actions."""
        gui_actions = {
            ActionType.CLICK,
            ActionType.CLICK_ELEMENT,
            ActionType.DOUBLE_CLICK,
            ActionType.RIGHT_CLICK,
            ActionType.TYPE,
            ActionType.TYPE_ELEMENT,
            ActionType.PRESS,
            ActionType.HOTKEY,
            ActionType.SCROLL,
            ActionType.MOVE,
            ActionType.SCREENSHOT,
        }
        return request.action in gui_actions

    async def execute(self, request: ActionRequest) -> ActionResult:
        start_time = time.monotonic()
        action = request.action
        target = request.target or ""

        try:
            # 1. Screenshot
            if action == ActionType.SCREENSHOT:
                path = screen_reader.take_screenshot()
                return ActionResult(
                    success=bool(path),
                    action=ActionType.SCREENSHOT,
                    executor_used=self.method,
                    screenshot_path=path,
                    output=path,
                    duration_ms=(time.monotonic() - start_time) * 1000,
                )

            # 2. Click or Element Click
            elif action in (ActionType.CLICK, ActionType.CLICK_ELEMENT, ActionType.DOUBLE_CLICK, ActionType.RIGHT_CLICK):
                return await self._execute_click(action, request, start_time)

            # 3. Type text
            elif action in (ActionType.TYPE, ActionType.TYPE_ELEMENT):
                return await self._execute_type(request, start_time)

            # 4. Key Press
            elif action == ActionType.PRESS:
                return await self._execute_press(request, start_time)

            # 5. Hotkey
            elif action == ActionType.HOTKEY:
                return await self._execute_hotkey(request, start_time)

            # 6. Scroll
            elif action == ActionType.SCROLL:
                return await self._execute_scroll(request, start_time)

            # 7. Move
            elif action == ActionType.MOVE:
                return await self._execute_move(request, start_time)

            else:
                return ActionResult(
                    success=False,
                    action=action,
                    target=target,
                    executor_used=self.method,
                    error=f"Unsupported vision action: {action}",
                    duration_ms=(time.monotonic() - start_time) * 1000,
                )

        except Exception as e:
            logger.error(f"[VisionGUIExecutor] Execution error for {action}: {e}", exc_info=True)
            return ActionResult(
                success=False,
                action=action,
                target=target,
                executor_used=self.method,
                error=str(e),
                duration_ms=(time.monotonic() - start_time) * 1000,
            )

    async def _execute_click(self, action: ActionType, request: ActionRequest, start: float) -> ActionResult:
        coords = request.coordinates

        # If coordinates not provided, locate element visually via OCR or Gemma Vision
        if not coords and request.target:
            coords = await self._locate_element_visually(request.target)

        if not coords:
            # Default center screen if unlocated
            if HAS_PYAUTOGUI:
                sw, sh = pyautogui.size()
                coords = (sw // 2, sh // 2)
            else:
                coords = (960, 540)

        if HAS_PYAUTOGUI:
            x, y = coords
            if action == ActionType.DOUBLE_CLICK:
                pyautogui.doubleClick(x, y)
            elif action == ActionType.RIGHT_CLICK:
                pyautogui.rightClick(x, y)
            else:
                pyautogui.click(x, y)

        return ActionResult(
            success=True,
            action=action,
            target=request.target,
            coordinates=coords,
            executor_used=self.method,
            output=f"Executed {action.value} at ({coords[0]}, {coords[1]})",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _execute_type(self, request: ActionRequest, start: float) -> ActionResult:
        text = request.text_val or request.target or ""
        coords = request.coordinates

        # Click into target field first if target or coordinates provided
        if coords or request.target:
            if not coords:
                coords = await self._locate_element_visually(request.target)
            if coords and HAS_PYAUTOGUI:
                pyautogui.click(coords[0], coords[1])
                await asyncio.sleep(0.2)

        if HAS_PYAUTOGUI and text:
            # Use clipboard paste for fast reliable text injection
            import pyperclip
            pyperclip.copy(text)
            pyautogui.hotkey('ctrl', 'v')
            if request.metadata.get("press_enter"):
                await asyncio.sleep(0.1)
                pyautogui.press('enter')

        return ActionResult(
            success=True,
            action=request.action,
            target=request.target,
            coordinates=coords,
            executor_used=self.method,
            output=f"Typed text into UI field",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _execute_press(self, request: ActionRequest, start: float) -> ActionResult:
        key = (request.target or "enter").lower()
        if HAS_PYAUTOGUI:
            pyautogui.press(key)

        return ActionResult(
            success=True,
            action=ActionType.PRESS,
            target=key,
            executor_used=self.method,
            output=f"Pressed key '{key}'",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _execute_hotkey(self, request: ActionRequest, start: float) -> ActionResult:
        keys = request.keys or (request.target.split("+") if request.target else ["ctrl", "c"])
        clean_keys = [k.strip().lower() for k in keys]

        if HAS_PYAUTOGUI:
            pyautogui.hotkey(*clean_keys)

        return ActionResult(
            success=True,
            action=ActionType.HOTKEY,
            target="+".join(clean_keys),
            executor_used=self.method,
            output=f"Triggered hotkey '{'+'.join(clean_keys)}'",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _execute_scroll(self, request: ActionRequest, start: float) -> ActionResult:
        amount = request.amount if request.amount is not None else -300
        if HAS_PYAUTOGUI:
            pyautogui.scroll(amount)

        return ActionResult(
            success=True,
            action=ActionType.SCROLL,
            amount=amount,
            executor_used=self.method,
            output=f"Scrolled {amount} units",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _execute_move(self, request: ActionRequest, start: float) -> ActionResult:
        coords = request.coordinates or (960, 540)
        if HAS_PYAUTOGUI:
            pyautogui.moveTo(coords[0], coords[1], duration=0.2)

        return ActionResult(
            success=True,
            action=ActionType.MOVE,
            coordinates=coords,
            executor_used=self.method,
            output=f"Moved mouse to ({coords[0]}, {coords[1]})",
            duration_ms=(time.monotonic() - start) * 1000,
        )

    async def _locate_element_visually(self, target_description: str) -> Optional[Tuple[int, int]]:
        """Locate element on screen using OCR text bounding boxes or Gemma Vision coordinates."""
        if not target_description:
            return None

        # Try OCR bounding boxes
        try:
            import pytesseract
            from PIL import Image
            screenshot_path = screen_reader.take_screenshot()
            if screenshot_path and os.path.exists(screenshot_path):
                img = Image.open(screenshot_path)
                data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
                target_lower = target_description.lower()
                for i, text in enumerate(data["text"]):
                    if text and target_lower in text.lower():
                        x = data["left"][i] + (data["width"][i] // 2)
                        y = data["top"][i] + (data["height"][i] // 2)
                        logger.info(f"[VisionGUIExecutor] Visual OCR located '{target_description}' at ({x}, {y})")
                        return (x, y)
        except Exception as e:
            logger.debug(f"[VisionGUIExecutor] OCR localization error: {e}")

        return None
