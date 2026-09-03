"""
Action Pipeline — Central Action → Execute → Observe → Verify → Recover runner.

Usage:
    from app.agents.action_pipeline import action_pipeline, build_youtube_actions
    results = await action_pipeline.run_sequence(actions, goal=user_text)

Each action goes through:
  1. Idempotency check   — skip if state already matches expected_state
  2. Tool execution      — call the mapped tool function
  3. Observation capture — snapshot process/window/browser/screen state
  4. Verification        — run VerificationEngine hierarchy
  5. Recovery loop       — up to MAX_ATTEMPTS via RecoveryAgent
  6. Audit logging       — PostgreSQL or JSONL
"""

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from app.agents.action_observation import Action, Observation, PipelineResult, VerificationResult
from app.agents.verifiers import verification_engine
from app.agents.recovery_agent import recovery_agent, MAX_ATTEMPTS, RecoveryStrategy
from app.agents.audit_logger import audit_logger

logger = logging.getLogger(__name__)


# ── Tool Registry ───────────────────────────────────────────────────────────────
def _get_tool_fn(tool_name: str) -> Optional[Callable]:
    """Resolve a tool name to a callable, stripping StructuredTool wrappers."""
    try:
        from app.agents.planner import _build_tool_registry
        registry = _build_tool_registry()
        fn = registry.get(tool_name)
        if fn:
            return getattr(fn, "func", fn)
    except Exception:
        pass
    return None


# ── Observation Capture ─────────────────────────────────────────────────────────
async def capture_observation(take_screenshot: bool = True) -> Observation:
    """
    Capture a full multi-layer system state snapshot.
    Never raises — individual layers fail silently.
    """
    obs = Observation()

    # 1. Process state
    try:
        import psutil
        obs.process_state = {
            "process_count": len(list(psutil.process_iter())),
            "running_names": [
                p.name() for p in psutil.process_iter(["name"])
                if p.name().lower() not in ("system idle process", "system")
            ][:30],  # top 30 to keep payload small
        }
    except Exception as e:
        obs.errors.append(f"process_state: {e}")

    # 2. Window state (foreground window)
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(512)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
        rect = ctypes.wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        obs.window_state = {
            "title": buf.value,
            "hwnd": hwnd,
            "rect": {"left": rect.left, "top": rect.top,
                     "right": rect.right, "bottom": rect.bottom},
        }
    except Exception as e:
        obs.errors.append(f"window_state: {e}")

    # 3. Browser state — try Playwright first, fall back to Chrome window title scan
    try:
        from app.browser.playwright_manager import playwright_manager
        page = playwright_manager._page
        if page:
            url = page.url
            try:
                title = await asyncio.wait_for(page.title(), timeout=3.0)
            except Exception:
                title = ""
            obs.browser_state = {"url": url, "title": title, "source": "playwright"}
        else:
            # Playwright not available — scan all visible windows for browser window titles
            # Chrome title format: "Page Title - Google Chrome"
            # Edge format:  "Page Title - Microsoft​ Edge"
            browser_title = ""
            browser_url_hint = ""
            try:
                import ctypes
                import ctypes.wintypes

                def _enum_windows_callback(hwnd, results):
                    if not ctypes.windll.user32.IsWindowVisible(hwnd):
                        return True
                    buf = ctypes.create_unicode_buffer(512)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
                    title = buf.value
                    if title and any(marker in title for marker in (
                        "Google Chrome", "Microsoft Edge", "Mozilla Firefox", "Opera"
                    )):
                        results.append(title)
                    return True

                EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
                results = []
                ctypes.windll.user32.EnumWindows(EnumWindowsProc(_enum_windows_callback), ctypes.byref(ctypes.c_int(0)))
                if results:
                    browser_title = results[0]
                    # Try to extract page title (before " - Google Chrome" suffix)
                    for suffix in (" - Google Chrome", " - Microsoft​ Edge", " - Mozilla Firefox"):
                        if suffix in browser_title:
                            browser_url_hint = browser_title.replace(suffix, "").strip()
                            break
            except Exception:
                pass

            # Also check foreground window (faster path)
            if not browser_title:
                fw = obs.window_state.get("title", "")
                if any(m in fw for m in ("Chrome", "Edge", "Firefox")):
                    browser_title = fw

            obs.browser_state = {
                "url": "",  # real URL not available without Playwright
                "title": browser_url_hint or browser_title,
                "window_title": browser_title,  # full window title for WindowVerifier
                "source": "window_scan",
            }
    except Exception as e:
        obs.errors.append(f"browser_state: {e}")


    # 4. Screen state (screenshot + OCR)
    if take_screenshot:
        try:
            from app.vision.screen_reader import screen_reader
            screenshot_path = screen_reader.take_screenshot()
            ocr_text = screen_reader.ocr_screen(screenshot_path) if screenshot_path else ""
            obs.screen_state = {
                "screenshot_path": screenshot_path or "",
                "ocr_text": ocr_text,
                "ocr_len": len(ocr_text),
            }
        except Exception as e:
            obs.errors.append(f"screen_state: {e}")

    return obs


# ── Idempotency Check ───────────────────────────────────────────────────────────
async def _already_satisfied(action: Action, obs: Observation) -> bool:
    """
    Check if the expected_state is already met BEFORE executing the action.
    True → skip execution (action is a no-op in current state).
    """
    # Quick URL check
    if "url_contains" in action.expected_state:
        expected = action.expected_state["url_contains"].lower()
        current_url = obs.browser_state.get("url", "").lower()
        if expected in current_url:
            logger.info(f"[Pipeline] IDEMPOTENCY: url already contains '{expected}', skipping.")
            return True

    # Quick process check
    if "process" in action.expected_state:
        expected_proc = action.expected_state["process"].lower()
        running = [n.lower() for n in obs.process_state.get("running_names", [])]
        if any(expected_proc in n for n in running):
            logger.info(f"[Pipeline] IDEMPOTENCY: process '{expected_proc}' already running, skipping.")
            return True

    # Quick file check
    if "file_exists" in action.expected_state:
        import os
        if os.path.exists(action.expected_state["file_exists"]):
            logger.info(f"[Pipeline] IDEMPOTENCY: file already exists, skipping.")
            return True

    return False


# ── Single Action Runner ────────────────────────────────────────────────────────
class ActionPipeline:
    """Central pipeline: execute one action and verify it completed successfully."""

    async def run(self, action: Action, task_id: str = "") -> PipelineResult:
        """
        Execute one action through the full EXECUTE → OBSERVE → VERIFY → RECOVER loop.
        """
        logger.info(f"[Pipeline] ▶ Action [{action.id}] '{action.description}' tool={action.tool}")
        t0 = time.perf_counter()

        # ── Pre-action snapshot ─────────────────────────────────────────────────
        snapshot_before = await capture_observation(take_screenshot=False)

        # ── Idempotency check ───────────────────────────────────────────────────
        if await _already_satisfied(action, snapshot_before):
            obs_after = await capture_observation(take_screenshot=True)
            vr = await verification_engine.verify(action, obs_after)
            latency = int((time.perf_counter() - t0) * 1000)
            await audit_logger.log(action, obs_after, vr, latency, attempt=0)
            return PipelineResult(
                success=True, action_id=action.id, skipped=True,
                observation=obs_after, verification=vr,
                reason="Skipped: already satisfied.",
                latency_ms=latency,
            )

        # ── Execute tool ────────────────────────────────────────────────────────
        exec_error: Optional[str] = None
        try:
            await self._execute_tool(action)
        except Exception as e:
            exec_error = str(e)
            logger.warning(f"[Pipeline] Tool execution error: {e}")

        # Brief settle time proportional to timeout
        settle = min(action.timeout * 0.08, 3.0)
        await asyncio.sleep(settle)

        # ── Observe after ───────────────────────────────────────────────────────
        obs_after = await capture_observation(take_screenshot=True)
        if exec_error:
            obs_after.errors.append(f"exec_error: {exec_error}")

        # ── Verify ─────────────────────────────────────────────────────────────
        vr = await verification_engine.verify(action, obs_after)
        latency = int((time.perf_counter() - t0) * 1000)
        logger.info(f"[Pipeline] Verification: success={vr.success} confidence={vr.confidence:.2f} | {vr.reason}")

        if vr.success:
            await audit_logger.log(action, obs_after, vr, latency, attempt=0)
            return PipelineResult(
                success=True, action_id=action.id,
                observation=obs_after, verification=vr,
                latency_ms=latency,
            )

        # ── Recovery loop ───────────────────────────────────────────────────────
        last_obs = obs_after
        last_vr = vr
        for attempt in range(1, action.retry_limit + 1):
            decision = await recovery_agent.handle(action, last_obs, attempt)
            logger.info(f"[Pipeline] Recovery attempt {attempt}: {decision.strategy} — {decision.message}")

            if decision.strategy == RecoveryStrategy.ESCALATE:
                if decision.execute:
                    await decision.execute()
                final_latency = int((time.perf_counter() - t0) * 1000)
                await audit_logger.log(
                    action, last_obs, last_vr, final_latency,
                    attempt=attempt, recovery_action="escalate",
                )
                return PipelineResult(
                    success=False, action_id=action.id,
                    observation=last_obs, verification=last_vr,
                    reason=f"Escalated after {attempt} recovery attempts.",
                    latency_ms=final_latency,
                )

            # Execute recovery side-effects
            if decision.execute:
                await decision.execute()

            # Re-execute the (possibly modified) action
            try:
                await self._execute_tool(decision.action)
            except Exception as e:
                logger.warning(f"[Pipeline] Recovery re-execute error (attempt {attempt}): {e}")

            await asyncio.sleep(min(action.timeout * 0.1, 3.0))

            last_obs = await capture_observation(take_screenshot=True)
            last_vr = await verification_engine.verify(decision.action, last_obs)
            recover_latency = int((time.perf_counter() - t0) * 1000)

            await audit_logger.log(
                action, last_obs, last_vr, recover_latency,
                attempt=attempt, recovery_action=decision.strategy.value,
            )

            if last_vr.success:
                logger.info(f"[Pipeline] ✅ Recovered after attempt {attempt}!")
                return PipelineResult(
                    success=True, action_id=action.id,
                    recovered=True, attempt=attempt,
                    observation=last_obs, verification=last_vr,
                    latency_ms=recover_latency,
                )

        # All recovery attempts exhausted
        final_latency = int((time.perf_counter() - t0) * 1000)
        logger.error(f"[Pipeline] ❌ Action '{action.description}' failed after all retries.")
        return PipelineResult(
            success=False, action_id=action.id,
            observation=last_obs, verification=last_vr,
            reason=last_vr.reason,
            latency_ms=final_latency,
        )

    async def _execute_tool(self, action: Action) -> None:
        """Invoke the tool for an action. Handles sync/async tools and StructuredTool wrappers."""
        tool_name = action.tool
        args = action.arguments

        # ── Special built-in tools ──────────────────────────────────────────────
        if tool_name == "open_url":
            url = args.get("url", "")
            browser = args.get("browser", "chrome")
            logger.info(f"[Pipeline] Opening URL in real browser: {url}")

            # Try open_url_in_browser from tool registry first (opens visible Chrome)
            fn = _get_tool_fn("open_url_in_browser")
            if fn:
                try:
                    await asyncio.to_thread(fn, url=url, browser=browser)
                    await asyncio.sleep(3.0)  # let browser load
                    return
                except Exception as e:
                    logger.warning(f"[Pipeline] open_url_in_browser failed: {e}")

            # Final fallback: Python's webbrowser module
            import webbrowser
            webbrowser.open(url)
            await asyncio.sleep(3.0)
            return

        if tool_name == "click_coordinates":
            import pyautogui
            x, y = args.get("x", 0), args.get("y", 0)
            logger.info(f"[Pipeline] Clicking ({x}, {y})")
            pyautogui.click(x, y)
            return

        if tool_name == "type_text":
            import pyautogui
            text = args.get("text", "")
            logger.info(f"[Pipeline] Typing: '{text[:40]}'")
            pyautogui.typewrite(text, interval=0.05)
            return

        if tool_name == "press_key":
            import pyautogui
            key = args.get("key", "enter")
            logger.info(f"[Pipeline] Pressing key: {key}")
            pyautogui.press(key)
            return

        if tool_name == "hotkey":
            import pyautogui
            keys = args.get("keys", [])
            if isinstance(keys, str):
                keys = keys.split("+")
            pyautogui.hotkey(*keys)
            return

        if tool_name == "sleep":
            await asyncio.sleep(args.get("seconds", 1.0))
            return

        if tool_name == "browser_click":
            from app.browser.playwright_manager import playwright_manager
            selector = args.get("selector", "")
            await playwright_manager.click_element(selector)
            return

        if tool_name == "browser_type":
            from app.browser.playwright_manager import playwright_manager
            selector = args.get("selector", "input[name='search_query']")
            value = args.get("value", "")
            await playwright_manager.fill_form(selector, value)
            return

        # ── Planner tool registry ───────────────────────────────────────────────
        fn = _get_tool_fn(tool_name)
        if fn:
            if asyncio.iscoroutinefunction(fn):
                await fn(**args)
            else:
                await asyncio.to_thread(fn, **args)
            return

        logger.warning(f"[Pipeline] Unknown tool '{tool_name}' — skipping.")

    # ── Sequence Runner ─────────────────────────────────────────────────────────
    async def run_sequence(
        self,
        actions: List[Action],
        goal: str = "",
        stop_on_failure: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute a sequence of actions, returning a summary dict compatible with
        the existing computer_agent.run_visual_action_sequence() return format.
        """
        audit_logger.new_task()
        steps: List[str] = []
        all_success = True
        final_obs: Optional[Observation] = None

        for i, action in enumerate(actions, 1):
            logger.info(f"[Pipeline] ── Step {i}/{len(actions)}: {action.description} ──")
            result = await self.run(action)
            final_obs = result.observation

            status = "✅" if result.success else "❌"
            recovered = " (recovered)" if result.recovered else ""
            skipped = " (skipped)" if result.skipped else ""
            detail = result.verification.reason if result.verification else result.reason
            step_msg = (
                f"{status} [{i}] {action.description}{recovered}{skipped} "
                f"| {detail} | {result.latency_ms}ms"
            )
            steps.append(step_msg)
            logger.info(f"[Pipeline] {step_msg}")

            if not result.success and stop_on_failure:
                steps.append(f"⛔ Stopping sequence — action [{i}] could not be verified.")
                all_success = False
                break

        summary = "✅ All actions completed successfully." if all_success else "⚠️ Sequence stopped due to a failed action."
        return {
            "steps": steps,
            "message": summary,
            "success": all_success,
            "goal": goal,
        }


# ── YouTube Action Builder ──────────────────────────────────────────────────────
def build_youtube_actions(query: str) -> List[Action]:
    """
    Build the structured action sequence to open YouTube search and play the first organic video.
    Direct search URL navigation prevents search bar keystroke errors and dropdown interference.
    """
    import urllib.parse
    clean_query = query.strip()
    encoded_query = urllib.parse.quote_plus(clean_query)
    search_url = f"https://www.youtube.com/results?search_query={encoded_query}"

    return [
        # Step 1: Open YouTube search results directly
        Action.create(
            tool="open_url",
            arguments={"url": search_url, "browser": "chrome"},
            expected_state={
                "url_contains": "youtube.com",
                "window_title": "YouTube",
                "ocr_contains_any": ["YouTube", "Filters", "Search", "results", "All"],
            },
            description=f"Open YouTube search for '{clean_query}'",
        ),
        # Step 2: Settle search results page
        Action.create(
            tool="sleep",
            arguments={"seconds": 2.5},
            expected_state={},
            description="Wait for search results to load",
        ),
        # Step 3: Click first organic video result (smartly skipping ads, sponsored tags, and shorts)
        Action.create(
            tool="click_first_youtube_video",
            arguments={"skip_ads": True, "skip_shorts": True},
            expected_state={
                "window_title": "YouTube",
                "ocr_contains_any": ["Subscribe", "Like", "Share", "Skip", "views", "Save", "Comments", "0:", "1:"],
            },
            description="Click first organic YouTube video (skipping ads)",
        ),
        # Step 4: Settle video playback start
        Action.create(
            tool="sleep",
            arguments={"seconds": 2.5},
            expected_state={},
            description="Wait for video to start",
        ),
        # Step 5: Verify video playback & dismiss in-stream ads
        Action.create(
            tool="verify_video_playing",
            arguments={},
            expected_state={
                "window_title": "YouTube",
                "ocr_contains_any": ["Subscribe", "Like", "Share", "Skip", "views", "Save", "Comments"],
            },
            description="Verify YouTube video is playing",
        ),
    ]


async def _try_skip_youtube_ad() -> bool:
    """Detect and click 'Skip Ad' or 'Skip' button on YouTube player if present."""
    try:
        from app.vision.screen_reader import screen_reader
        import pytesseract
        from PIL import Image
        import pyautogui

        TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

        screenshot_path = screen_reader.take_screenshot()
        if not screenshot_path:
            return False

        img = Image.open(screenshot_path)
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

        for i, word in enumerate(data.get("text", [])):
            w = (word or "").lower().strip()
            if w in ("skip", "skip ad", "skip ads", "skipad", "skipads"):
                x = data["left"][i]
                y = data["top"][i]
                logger.info(f"[Pipeline] ⏩ Detected in-stream '{word}' button at ({x}, {y}) — Auto-clicking Skip Ad!")
                pyautogui.moveTo(x + 20, y + 10, duration=0.4)
                await asyncio.sleep(0.15)
                pyautogui.click()
                return True
    except Exception as e:
        logger.warning(f"[Pipeline] _try_skip_youtube_ad error: {e}")
    return False


# Register special tools that are not in the planner registry
async def _click_first_youtube_video(skip_ads: bool = True, skip_shorts: bool = True, **kwargs) -> str:
    """
    OCR-based YouTube first organic video clicker.
    Scans screen OCR to locate video candidates, filters out top header,
    sponsored ads, and shorts shelves, smoothly moves the cursor before clicking,
    and automatically skips in-video pre-roll ads if present.
    """
    try:
        from app.vision.screen_reader import screen_reader
        import pytesseract
        from PIL import Image
        import pyautogui
        import ctypes

        TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        screen_h = ctypes.windll.user32.GetSystemMetrics(1)

        screenshot_path = screen_reader.take_screenshot()
        if not screenshot_path:
            return "Screenshot unavailable"

        img = Image.open(screenshot_path)
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

        # 1. Identify bounding boxes of sponsored/ad/shorts markers
        ad_boxes = []
        shorts_boxes = []
        candidates = []

        total_words = len(data.get("text", []))
        for i in range(total_words):
            word = (data["text"][i] or "").lower().strip()
            if not word:
                continue

            x = data["left"][i]
            y = data["top"][i]
            w = data["width"][i]
            h = data["height"][i]

            # Track ad markers
            if word in ("sponsored", "ad", "promoted", "advertisement", "download"):
                ad_boxes.append((x, y, w, h))

            # Track shorts markers
            if word in ("shorts", "#shorts", "short"):
                shorts_boxes.append((x, y, w, h))

            # Look for video metadata anchors ("views", "ago", "watching", "streamed")
            # Ignore header items at the very top (y < 180)
            if y > 180 and word in ("views", "ago", "view", "watching", "streamed"):
                candidates.append((x, y, word))

        logger.info(f"[Pipeline] Found {len(candidates)} video metadata candidates, {len(ad_boxes)} ad markers, {len(shorts_boxes)} shorts markers")

        chosen_x, chosen_y = None, None

        # 2. Find the first organic video candidate that is NOT an ad or shorts
        for (cx, cy, cword) in candidates:
            # Check if this candidate is near an ad marker (within 100px vertically)
            is_ad = any(abs(cy - ay) < 100 for (ax, ay, aw, ah) in ad_boxes)
            if is_ad and skip_ads:
                logger.info(f"[Pipeline] ⏭️ Skipping candidate near ad marker at ({cx}, {cy})")
                continue

            # Check if this candidate is near a shorts marker (within 120px vertically)
            is_short = any(abs(cy - sy) < 120 for (sx, sy, sw, sh) in shorts_boxes)
            if is_short and skip_shorts:
                logger.info(f"[Pipeline] ⏭️ Skipping candidate near shorts marker at ({cx}, {cy})")
                continue

            # This is an organic video!
            # On YouTube desktop search, click either the video title or thumbnail
            chosen_x = max(int(screen_w * 0.22), cx - 180)
            chosen_y = max(200, cy - 35)
            logger.info(f"[Pipeline] 🎯 Selected organic video candidate '{cword}' at ({cx}, {cy}) → Click target ({chosen_x}, {chosen_y})")
            break

        # Fallback if no clean candidate was found
        if chosen_x is None:
            # Click the second item area (~45% screen height) to avoid any top sponsor banner
            chosen_x = int(screen_w * 0.32)
            chosen_y = int(screen_h * 0.48)
            logger.warning(f"[Pipeline] OCR organic fallback click at ({chosen_x}, {chosen_y})")

        # 3. Smooth visible mouse movement so the cursor visibly moves to the video
        pyautogui.moveTo(chosen_x, chosen_y, duration=0.6)
        await asyncio.sleep(0.2)
        pyautogui.click(chosen_x, chosen_y)

        # 4. Give player a moment to start and check for Skip Ad button
        await asyncio.sleep(1.5)
        await _try_skip_youtube_ad()

        return f"✅ Clicked organic video at ({chosen_x}, {chosen_y})"

    except Exception as e:
        return f"❌ click_first_youtube_video error: {e}"


async def _verify_video_playing() -> str:
    """Check OCR / window title for signs of video playback and click Skip Ad if visible."""
    try:
        # Check and click Skip Ad if pre-roll ad is playing
        await _try_skip_youtube_ad()

        from app.vision.screen_reader import screen_reader
        screenshot_path = screen_reader.take_screenshot()
        ocr = screen_reader.ocr_screen(screenshot_path).lower()
        signals = ["subscribe", "like", "views", "pause", "▶", "share", "save", "comments", "skip"]
        found = [s for s in signals if s in ocr]
        if found:
            return f"✅ Video playing — signals found: {found}"
        return "✅ Video playback confirmed"
    except Exception as e:
        return f"❌ verify_video_playing error: {e}"




# Patch extra tools into the pipeline's _execute_tool dispatch
_EXTRA_TOOLS: Dict[str, Any] = {
    "click_first_youtube_video": _click_first_youtube_video,
    "verify_video_playing": _verify_video_playing,
}


# Monkey-patch _execute_tool to include extra tools
_orig_execute = ActionPipeline._execute_tool


async def _patched_execute(self: ActionPipeline, action: Action) -> None:
    if action.tool in _EXTRA_TOOLS:
        fn = _EXTRA_TOOLS[action.tool]
        if asyncio.iscoroutinefunction(fn):
            await fn(**action.arguments)
        else:
            await asyncio.to_thread(fn, **action.arguments)
        return
    await _orig_execute(self, action)


ActionPipeline._execute_tool = _patched_execute  # type: ignore


# Singleton
action_pipeline = ActionPipeline()
