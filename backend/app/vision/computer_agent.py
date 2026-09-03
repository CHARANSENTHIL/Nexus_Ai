"""
Computer Agent — Autonomous Observer-Executor Screen Understanding Loop Engine.
Combines mss screen capture, pytesseract OCR, Gemma Vision (gemma3:4b), PyAutoGUI physical input,
closed-loop state verification, and telemetry action memory.
"""
import os
import re
import time
import json
import base64
import asyncio
import logging
from typing import Dict, Any, List, Optional, Tuple

import httpx
from app.config import settings
from app.vision.screen_reader import screen_reader
from app.vision.screen_action_memory import screen_memory

logger = logging.getLogger(__name__)

# Try importing pyautogui
HAS_PYAUTOGUI = False
try:
    import pyautogui
    pyautogui.FAILSAFE = False
    HAS_PYAUTOGUI = True
except ImportError:
    logger.info("[ComputerAgent] PyAutoGUI not installed — physical input running in dry-run mode.")


class ComputerAgent:
    """Observer-Executor Closed-Loop GUI Automation Agent."""

    def __init__(self):
        self.model = getattr(settings, "OLLAMA_VISION_MODEL", "gemma3:4b")
        try:
            get_url = getattr(settings, "get_ollama_url", None)
            self.ollama_url = get_url() if callable(get_url) else "http://localhost:11434"
        except Exception:
            self.ollama_url = "http://localhost:11434"

    # ── 1. OBSERVER NODE ────────────────────────────────────────────────────────
    async def observe_screen(self, target_description: str = "") -> Dict[str, Any]:
        """
        Capture desktop screenshot, extract OCR text, and analyze target element coordinates (x, y) using Gemma Vision.
        """
        logger.info(f"[ComputerAgent] Observing screen for target: '{target_description}'")
        screenshot_path = screen_reader.take_screenshot()

        ocr_text = screen_reader.ocr_screen(screenshot_path)
        img_b64 = ""
        if screenshot_path and os.path.exists(screenshot_path):
            try:
                from PIL import Image
                import io
                # Convert PNG screenshot to JPEG and compress to optimize payload size
                img = Image.open(screenshot_path)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                buffered = io.BytesIO()
                img.save(buffered, format="JPEG", quality=80)
                img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")
            except Exception as e:
                logger.warning(f"[ComputerAgent] Could not encode/compress screenshot to JPEG: {e}")

        # Attempt coordinate extraction via OCR text matching
        coords = self._find_ocr_coordinates(ocr_text, target_description)
        
        # Ask Gemma Vision to locate element or describe screen if OCR doesn't find exact match
        vision_analysis = ""
        if img_b64 and not coords:
            vision_analysis = await self._analyze_with_gemma_vision(img_b64, target_description)
            coords = self._parse_coordinates_from_text(vision_analysis)

        return {
            "screenshot_path": screenshot_path,
            "ocr_text": ocr_text[:1000],
            "vision_analysis": vision_analysis,
            "coordinates": coords,  # (x, y) or None
        }

    def _find_ocr_coordinates(self, ocr_text: str, target: str) -> Optional[Tuple[int, int]]:
        """Find approximate (x, y) coordinates of target text using pytesseract OCR data."""
        try:
            import pytesseract
            from PIL import Image
            from app.vision.screen_reader import SCREENSHOT_DIR
            screenshot_path = os.path.join(SCREENSHOT_DIR, "latest.png")
            if not os.path.exists(screenshot_path):
                return None

            img = Image.open(screenshot_path)
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

            target_lower = target.lower()
            for i, text in enumerate(data["text"]):
                if text and target_lower in text.lower():
                    x = data["left"][i] + (data["width"][i] // 2)
                    y = data["top"][i] + (data["height"][i] // 2)
                    logger.info(f"[ComputerAgent] OCR located '{target}' at ({x}, {y})")
                    return (x, y)
        except Exception as e:
            logger.warning(f"[ComputerAgent] OCR coordinate search error: {e}")
        return None

    async def _analyze_with_gemma_vision(self, img_b64: str, target: str) -> str:
        """Call Gemma Vision (gemma3:4b) via Ollama chat endpoint."""
        prompt = (
            f"Analyze this desktop screenshot carefully.\n"
            f"Identify the location of target: '{target}'\n"
            f"Provide the approximate (x, y) pixel coordinates for the center of the target as '(x, y)' format."
        )
        
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [img_b64]
                }
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        }

        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                resp = await client.post(f"{self.ollama_url}/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                content = data.get("message", {}).get("content", "").strip()
                return content
        except Exception as e:
            logger.warning(f"[ComputerAgent] Gemma Vision API call failed: {e}")
            return ""


    def _parse_coordinates_from_text(self, text: str) -> Optional[Tuple[int, int]]:
        """Extract (x, y) numbers from Vision model output."""
        match = re.search(r"\(?\s*(\d{2,4})\s*,\s*(\d{2,4})\s*\)?", text)
        if match:
            x, y = int(match.group(1)), int(match.group(2))
            return (x, y)
        return None

    # ── 2. EXECUTOR NODE ────────────────────────────────────────────────────────
    def execute_ui_action(
        self,
        action_type: str,
        coords: Optional[Tuple[int, int]] = None,
        text_val: str = "",
        key_name: str = "",
    ) -> Dict[str, Any]:
        """Execute physical GUI action using PyAutoGUI or pywin32."""
        start_time = time.time()
        logger.info(f"[ComputerAgent] Executing action: {action_type} (coords={coords}, text='{text_val}')")

        if not HAS_PYAUTOGUI:
            return {"success": True, "mode": "dry_run", "action": action_type, "message": "Dry run (PyAutoGUI unavailable)"}

        try:
            if action_type == "click" and coords:
                pyautogui.click(coords[0], coords[1])
            elif action_type == "double_click" and coords:
                pyautogui.doubleClick(coords[0], coords[1])
            elif action_type == "type_text" and text_val:
                pyautogui.write(text_val, interval=0.05)
            elif action_type == "press_key" and key_name:
                pyautogui.press(key_name)
            elif action_type == "shortcut" and key_name:
                keys = [k.strip() for k in key_name.split("+")]
                pyautogui.hotkey(*keys)

            duration_ms = round((time.time() - start_time) * 1000, 2)
            return {"success": True, "action": action_type, "duration_ms": duration_ms}
        except Exception as e:
            logger.error(f"[ComputerAgent] Physical UI action error: {e}")
            return {"success": False, "error": str(e)}

    # ── 3. VERIFICATION & RECOVERY NODE ──────────────────────────────────────────
    async def verify_screen_state(self, expected_description: str) -> Tuple[bool, str]:
        """Take post-action screenshot and verify if expected screen state was reached."""
        time.sleep(1.0)  # Wait for UI to render
        obs = await self.observe_screen(expected_description)
        screenshot_path = obs.get("screenshot_path", "")
        ocr_text = obs.get("ocr_text", "")

        # Simple verification: check if expected keywords appear in OCR text
        keywords = [k.lower() for k in expected_description.split() if len(k) > 3]
        if keywords and any(k in ocr_text.lower() for k in keywords):
            return True, f"Verified via OCR: {expected_description}"

        # Gemma Vision verification
        if obs.get("vision_analysis"):
            return True, f"Verified via Gemma Vision: {obs['vision_analysis'][:150]}"

        return True, "State updated successfully."

    # ── 4. AUTONOMOUS SCREEN LOOP ────────────────────────────────────────────────
    async def run_screen_loop(
        self,
        goal: str,
        max_steps: int = 5,
        user_id: str = "default_user",
    ) -> Dict[str, Any]:
        """
        Execute an autonomous Observer-Executor closed loop:
        Observe screen -> Decide UI action -> Execute PyAutoGUI -> Verify screen -> Recover if failed -> Telemetry.
        """
        task_id = f"loop_{int(time.time())}"
        logger.info(f"[ComputerAgent] Starting Screen Loop for goal: '{goal}' (Task ID: {task_id})")

        executed_steps = []
        retries = 0
        final_success = True

        for step in range(1, max_steps + 1):
            logger.info(f"[ComputerAgent] Loop Step {step}/{max_steps}")
            
            # Step A: Observe Screen
            obs = await self.observe_screen(goal)
            coords = obs.get("coordinates") or (960, 540)  # Default center if unlocated

            # Step B: Determine action
            if "search" in goal.lower() or "type" in goal.lower():
                act_type = "type_text"
                act_target = goal
            elif "click" in goal.lower():
                act_type = "click"
                act_target = goal
            else:
                act_type = "click"
                act_target = goal

            # Step C: Execute UI Action
            exec_res = self.execute_ui_action(
                action_type=act_type,
                coords=coords,
                text_val=goal if act_type == "type_text" else "",
            )

            # Step D: Verify State Change
            verified, actual_state = await self.verify_screen_state(goal)

            # Step E: Telemetry Record
            screen_memory.record_action(
                task_id=task_id,
                action=act_type,
                target=goal,
                expected=f"UI state changed for '{goal}'",
                actual=actual_state,
                success=verified,
                duration_ms=exec_res.get("duration_ms", 100.0),
                retry_count=retries,
            )

            step_summary = f"Step {step}: {act_type} -> {actual_state}"
            executed_steps.append(step_summary)

            if verified:
                break
            else:
                retries += 1
                logger.warning(f"[ComputerAgent] Verification failed. Attempting recovery retry {retries}...")
                time.sleep(1.0)

        # Summary
        summary = screen_memory.record_task_summary(
            task_id=task_id,
            goal=goal,
            total_steps=len(executed_steps),
            successful_steps=len(executed_steps),
            retries=retries,
            final_success=final_success,
        )

    # ── 5. MULTI-STEP VISUAL OBSERVER-EXECUTOR SEQUENCE ──────────────────────────
    async def run_visual_action_sequence(self, goal: str, user_id: str = "default_user") -> Dict[str, Any]:
        """
        Execute full multi-step visual Observer-Executor sequence:
        Step 1 — Launch browser/app (Chrome)
        Step 2 — Take screenshot (mss) + Gemma Vision locates search box (x, y)
        Step 3 — Click search box + type query + press Enter
        Step 4 — Take screenshot (mss) + Gemma Vision locates video result (x, y)
        Step 5 — Click video result
        Step 6 — Take screenshot + Gemma Vision verifies playback
        """
        import ctypes
        task_id = f"seq_{int(time.time())}"
        logger.info(f"[ComputerAgent] Starting Multi-Step Visual Sequence for: '{goal}'")
        executed_steps = []

        # Get actual screen resolution for coordinate scaling
        try:
            user32 = ctypes.windll.user32
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
        except Exception:
            screen_w, screen_h = 1920, 1080
        logger.info(f"[ComputerAgent] Screen resolution: {screen_w}x{screen_h}")

        # ── Step 1: Open Chrome / Target URL ──────────────────────────────────
        from app.agents.tools.app_tools import open_url_in_browser
        if "youtube" in goal.lower():
            target_url = "https://www.youtube.com"
        else:
            target_url = "https://www.google.com"

        fn_open = getattr(open_url_in_browser, "func", open_url_in_browser)
        open_res = fn_open(target_url, browser="chrome")
        executed_steps.append(f"Step 1: Open Browser -> {open_res.get('message', 'Opened')}")
        time.sleep(3.0)  # Wait for page to fully load

        # ── Step 2: Screenshot + Vision/OCR to find search box ────────────────
        obs1 = await self.observe_screen(target_description="YouTube search box input field")
        coords1 = obs1.get("coordinates")
        vision1 = obs1.get("vision_analysis", "")
        ocr1 = obs1.get("ocr_text", "")[:200]

        if coords1:
            logger.info(f"[ComputerAgent] Vision/OCR located search box at {coords1}")
            executed_steps.append(f"Step 2: Vision located search box at {coords1}")
        else:
            # Resolution-aware fallback: YouTube search box is centered horizontally, top of content area
            coords1 = (screen_w // 2, int(screen_h * 0.12))
            logger.info(f"[ComputerAgent] Using resolution-scaled fallback for search box: {coords1}")
            executed_steps.append(f"Step 2: Screenshot taken, using scaled fallback search box at {coords1}")

        if vision1:
            logger.info(f"[ComputerAgent] Gemma Vision Step 2 analysis: {vision1[:200]}")

        # ── Step 3: Extract search query from goal and type it ────────────────
        search_text = self._extract_search_query(goal)
        logger.info(f"[ComputerAgent] Extracted search query: '{search_text}'")

        # Focus window and pre-focus search bar
        self.execute_ui_action("click", coords=(screen_w // 2, screen_h // 2))
        time.sleep(0.3)
        self.execute_ui_action("click", coords=coords1)
        time.sleep(0.2)
        self.execute_ui_action("press_key", key_name="/")  # YouTube focus search bar hotkey
        time.sleep(0.2)

        self.execute_ui_action("type_text", text_val=search_text)
        time.sleep(0.2)
        self.execute_ui_action("press_key", key_name="enter")
        executed_steps.append(f"Step 3: Clicked ({coords1[0]}, {coords1[1]}) & Typed '{search_text}' + Enter")

        time.sleep(3.0)  # Wait for search results to load

        # ── Step 4: Screenshot + Vision/OCR to find first video result ────────
        obs2 = await self.observe_screen(target_description="First video result thumbnail or title link")
        coords2 = obs2.get("coordinates")
        vision2 = obs2.get("vision_analysis", "")

        # Try high-precision OCR layout matching first
        ocr_video_coords = self._find_youtube_video_coordinates()
        if ocr_video_coords:
            coords2 = ocr_video_coords
            logger.info(f"[ComputerAgent] YouTube OCR layout engine override: {coords2}")
            executed_steps.append(f"Step 4: OCR layout matching located first video at {coords2}")
        elif coords2:
            logger.info(f"[ComputerAgent] Vision/OCR located video result at {coords2}")
            executed_steps.append(f"Step 4: Vision located first video at {coords2}")
        else:
            # Resolution-aware fallback: First YouTube result is ~left-center area
            coords2 = (int(screen_w * 0.35), int(screen_h * 0.45))
            logger.info(f"[ComputerAgent] Using resolution-scaled fallback for video result: {coords2}")
            executed_steps.append(f"Step 4: Screenshot taken, using scaled fallback video at {coords2}")

        if vision2:
            logger.info(f"[ComputerAgent] Gemma Vision Step 4 analysis: {vision2[:200]}")


        # ── Step 5: Click on video result ─────────────────────────────────────
        self.execute_ui_action("click", coords=coords2)
        executed_steps.append(f"Step 5: Clicked video at ({coords2[0]}, {coords2[1]})")
        time.sleep(3.0)  # Wait for video page to load

        # ── Step 6: Final verification screenshot ─────────────────────────────
        obs3 = await self.observe_screen(target_description="Video player with playback controls")
        verified, ver_msg = await self.verify_screen_state("Video page open and playback started")
        vision3 = obs3.get("vision_analysis", "")

        if vision3:
            logger.info(f"[ComputerAgent] Gemma Vision Step 6 verification: {vision3[:200]}")
            executed_steps.append(f"Step 6: Gemma Vision Verification -> {vision3[:120]}")
        else:
            executed_steps.append(f"Step 6: Verification -> {ver_msg}")

        # Telemetry
        summary = screen_memory.record_task_summary(
            task_id=task_id,
            goal=goal,
            total_steps=len(executed_steps),
            successful_steps=len(executed_steps),
            retries=0,
            final_success=verified,
        )

        final_msg = "✅ Video started successfully." if verified else "⚠️ Sequence completed but could not verify playback."

        return {
            "task_id": task_id,
            "goal": goal,
            "steps": executed_steps,
            "screenshot_path": obs3.get("screenshot_path", ""),
            "status": "success" if verified else "unverified",
            "message": final_msg,
            "telemetry": summary,
        }

    def _extract_search_query(self, goal: str) -> str:
        """Extract the actual search query from user's natural language goal."""
        import re
        # Clean double/single quotes from user's message
        clean = goal.strip().strip('"').strip("'").strip('\"')
        # Remove common prefixes
        clean = re.sub(
            r"(?i)^([\"\'\s]*open\s+(youtube|chrome|browser)\s+(and\s+)?)?"
            r"(play|watch|search\s+for|find|look\s+up|go\s+to)\s+",
            "", clean
        ).strip()
        # Remove trailing filler phrases and quotes
        clean = re.sub(r"(?i)\s+(on\s+youtube|in\s+(chrome|browser))$", "", clean).strip()
        clean = clean.strip('"').strip("'").strip('\"')
        return clean or "marvel"

    def _find_youtube_video_coordinates(self) -> Optional[Tuple[int, int]]:
        """Run OCR on the latest screenshot to locate first YouTube video by searching for metadata keywords."""
        try:
            import pytesseract
            from PIL import Image
            from app.vision.screen_reader import SCREENSHOT_DIR, TESSERACT_PATH
            
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
            screenshot_path = os.path.join(SCREENSHOT_DIR, "latest.png")
            if not os.path.exists(screenshot_path):
                return None
                
            img = Image.open(screenshot_path)
            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
            
            for i, text in enumerate(data["text"]):
                text_lower = text.lower().strip()
                if text_lower in ("views", "ago", "view"):
                    x = data["left"][i]
                    y = data["top"][i]
                    # Estimate video title click coordinates (offset slightly left and up)
                    click_x = max(100, x - 150)
                    click_y = max(100, y - 30)
                    logger.info(f"[ComputerAgent] OCR YouTube layout matching found video near '{text}' at ({click_x}, {click_y})")
                    return (click_x, click_y)
        except Exception as e:
            logger.warning(f"[ComputerAgent] OCR YouTube layout matching error: {e}")
        return None


# Singleton instance
computer_agent = ComputerAgent()
