"""Omni-GUI Computer Copilot (Vision-Action Agent) for Nexus AI.

Provides autonomous visual control over Windows desktop applications:
mouse clicks, typing, keyboard hotkeys, and screen coordinate targeting with visual verification.
"""
import os
import time
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GUICopilotAgent:
    """Agent for controlling Windows desktop apps through visual mouse/keyboard actions."""

    def __init__(self):
        self._ensure_pyautogui()

    def _ensure_pyautogui(self):
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.4
        except Exception as e:
            logger.warning(f"[GUICopilot] PyAutoGUI init warning: {e}")

    async def execute_action_sequence(
        self,
        actions: List[Dict[str, Any]],
        verify_screenshot: bool = True
    ) -> Dict[str, Any]:
        """Executes a sequence of low-level GUI actions (click, type, hotkey, wait)."""
        import pyautogui
        results = []
        logger.info(f"[GUICopilot] Executing {len(actions)} GUI actions...")

        for idx, act in enumerate(actions, 1):
            act_type = act.get("type", "").lower()
            try:
                if act_type == "click":
                    x = act.get("x")
                    y = act.get("y")
                    clicks = act.get("clicks", 1)
                    button = act.get("button", "left")
                    if x is not None and y is not None:
                        pyautogui.click(x=x, y=y, clicks=clicks, button=button)
                    else:
                        pyautogui.click(clicks=clicks, button=button)
                    results.append(f"[{idx}] Clicked at ({x}, {y}) [{button}]")

                elif act_type == "double_click":
                    x = act.get("x")
                    y = act.get("y")
                    pyautogui.doubleClick(x=x, y=y)
                    results.append(f"[{idx}] Double clicked at ({x}, {y})")

                elif act_type == "type":
                    text = act.get("text", "")
                    interval = act.get("interval", 0.05)
                    pyautogui.typewrite(text, interval=interval)
                    results.append(f"[{idx}] Typed text: '{text}'")

                elif act_type == "hotkey":
                    keys = act.get("keys", [])
                    if isinstance(keys, str):
                        keys = [k.strip() for k in keys.split("+")]
                    pyautogui.hotkey(*keys)
                    results.append(f"[{idx}] Pressed hotkey: {'+'.join(keys)}")

                elif act_type == "press":
                    key = act.get("key", "enter")
                    pyautogui.press(key)
                    results.append(f"[{idx}] Pressed key: {key}")

                elif act_type == "wait":
                    sec = float(act.get("seconds", 1.0))
                    time.sleep(sec)
                    results.append(f"[{idx}] Waited {sec}s")

                elif act_type == "scroll":
                    amount = int(act.get("amount", -500))
                    pyautogui.scroll(amount)
                    results.append(f"[{idx}] Scrolled {amount}")

                else:
                    results.append(f"[{idx}] Unknown action type: {act_type}")

            except Exception as e:
                logger.error(f"[GUICopilot] Action {idx} failed: {e}", exc_info=True)
                return {
                    "success": False,
                    "error": f"Failed at step {idx} ({act_type}): {str(e)}",
                    "executed_steps": results
                }

        # Take verification screenshot
        screenshot_path = None
        if verify_screenshot:
            try:
                from app.vision.screen_reader import screen_reader
                screenshot_path = screen_reader.take_screenshot()
            except Exception as se:
                logger.warning(f"[GUICopilot] Verification screenshot failed: {se}")

        return {
            "success": True,
            "executed_steps": results,
            "screenshot_path": screenshot_path,
            "message": f"Successfully executed {len(actions)} GUI actions."
        }

    async def find_and_click_text(self, text_target: str) -> Dict[str, Any]:
        """Finds on-screen text coordinates using OCR and clicks the center."""
        try:
            import pytesseract
            from PIL import Image
            from app.vision.screen_reader import screen_reader, TESSERACT_PATH
            import pyautogui

            for p in [TESSERACT_PATH, r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Users\chara_qmka15y\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"]:
                if os.path.exists(p):
                    pytesseract.pytesseract.tesseract_cmd = p
                    break

            shot_path = screen_reader.take_screenshot()
            if not shot_path or not os.path.exists(shot_path):
                return {"success": False, "error": "Could not capture screenshot for text search."}

            img = Image.open(shot_path)
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

            target_lower = text_target.lower()
            n_boxes = len(data['text'])
            for i in range(n_boxes):
                if target_lower in data['text'][i].lower():
                    (x, y, w, h) = (data['left'][i], data['top'][i], data['width'][i], data['height'][i])
                    center_x = x + (w // 2)
                    center_y = y + (h // 2)
                    logger.info(f"[GUICopilot] Found text '{text_target}' at ({center_x}, {center_y})")
                    pyautogui.click(center_x, center_y)
                    return {
                        "success": True,
                        "clicked_coordinates": (center_x, center_y),
                        "found_text": data['text'][i],
                        "message": f"Clicked '{text_target}' at screen position ({center_x}, {center_y})."
                    }

            return {"success": False, "error": f"Target text '{text_target}' not found on active screen."}

        except Exception as e:
            logger.error(f"[GUICopilot] find_and_click_text error: {e}", exc_info=True)
            return {"success": False, "error": str(e)}


gui_copilot_agent = GUICopilotAgent()
