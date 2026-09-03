"""
Verifier Hierarchy — Deterministic-first verification of post-action system state.

Verification priority (highest confidence first, Vision AI last resort):
  1. ProcessVerifier    — psutil process enumeration
  2. WindowVerifier     — win32gui foreground window title
  3. BrowserVerifier    — Playwright page.url / page.title()
  4. FileVerifier       — os.path.exists / mtime / size
  5. NetworkVerifier    — httpx HTTP 200 check
  6. OCRVerifier        — pytesseract keyword scan on latest screenshot
  7. VisionVerifier     — Gemma3:4b via /api/chat (last resort)
"""

import os
import re
import base64
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx

from app.agents.action_observation import Action, Observation, VerificationCheck, VerificationResult

logger = logging.getLogger(__name__)

TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# ── Abstract Base ───────────────────────────────────────────────────────────────
class Verifier(ABC):
    """Abstract base for all verifiers."""
    name: str = "BaseVerifier"

    @abstractmethod
    async def verify(self, action: Action, obs: Observation) -> Optional[VerificationCheck]:
        """
        Return a VerificationCheck if this verifier is applicable, else None.
        Never raise — always catch and return a failed check or None.
        """

    def _applicable(self, action: Action) -> bool:
        """Subclasses override to declare when they apply."""
        return True


# ── 1. ProcessVerifier ──────────────────────────────────────────────────────────
class ProcessVerifier(Verifier):
    name = "ProcessVerifier"

    def _applicable(self, action: Action) -> bool:
        return "process" in action.expected_state

    async def verify(self, action: Action, obs: Observation) -> Optional[VerificationCheck]:
        if not self._applicable(action):
            return None
        expected_proc = action.expected_state["process"].lower()
        try:
            import psutil
            running = [p.name().lower() for p in psutil.process_iter(["name"])]
            matched = any(expected_proc in name for name in running)
            return VerificationCheck(
                name=self.name,
                passed=matched,
                confidence=0.95,
                detail=f"Process '{expected_proc}' {'found' if matched else 'NOT found'} in {len(running)} processes.",
            )
        except Exception as e:
            return VerificationCheck(name=self.name, passed=False, confidence=0.0,
                                     detail=f"psutil error: {e}")


# ── 2. WindowVerifier ───────────────────────────────────────────────────────────
class WindowVerifier(Verifier):
    name = "WindowVerifier"

    def _applicable(self, action: Action) -> bool:
        return "window_title" in action.expected_state

    async def verify(self, action: Action, obs: Observation) -> Optional[VerificationCheck]:
        if not self._applicable(action):
            return None
        expected_title = action.expected_state["window_title"].lower()
        try:
            # First check obs.browser_state.window_title (populated by window scan in capture_observation)
            browser_wt = obs.browser_state.get("window_title", "").lower()
            if browser_wt and expected_title in browser_wt:
                return VerificationCheck(
                    name=self.name, passed=True, confidence=0.92,
                    detail=f"Browser window title '{browser_wt}' contains '{expected_title}'.",
                )

            # Enumerate ALL visible windows (browser may not be foreground)
            import ctypes
            found_titles = []

            def _cb(hwnd, _):
                if ctypes.windll.user32.IsWindowVisible(hwnd):
                    buf = ctypes.create_unicode_buffer(512)
                    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 512)
                    t = buf.value
                    if t:
                        found_titles.append(t.lower())
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
            ctypes.windll.user32.EnumWindows(WNDENUMPROC(_cb), 0)

            matched = [t for t in found_titles if expected_title in t]
            if matched:
                return VerificationCheck(
                    name=self.name, passed=True, confidence=0.92,
                    detail=f"Window '{matched[0]}' contains '{expected_title}'.",
                )

            # Fallback: check foreground window
            actual_title = obs.window_state.get("title", "").lower()
            fw_match = expected_title in actual_title if actual_title else False
            return VerificationCheck(
                name=self.name,
                passed=fw_match,
                confidence=0.85 if fw_match else 0.1,
                detail=f"Foreground window '{actual_title}' {'contains' if fw_match else 'does NOT contain'} '{expected_title}'.",
            )
        except Exception as e:
            return VerificationCheck(name=self.name, passed=False, confidence=0.0,
                                     detail=f"Window check error: {e}")




# ── 3. BrowserVerifier ──────────────────────────────────────────────────────────
class BrowserVerifier(Verifier):
    name = "BrowserVerifier"

    def _applicable(self, action: Action) -> bool:
        return ("url_contains" in action.expected_state or
                "page_title_contains" in action.expected_state)

    async def verify(self, action: Action, obs: Observation) -> Optional[VerificationCheck]:
        if not self._applicable(action):
            return None
        try:
            from app.browser.playwright_manager import playwright_manager
            page = playwright_manager._page
            url = ""
            title = ""

            if page:
                url = page.url
                try:
                    title = await asyncio.wait_for(page.title(), timeout=5.0)
                except Exception:
                    title = obs.browser_state.get("title", "")
            else:
                # Playwright not available — use obs populated from Chrome window title scan
                url = obs.browser_state.get("url", "")
                title = obs.browser_state.get("title", "") or obs.browser_state.get("window_title", "")

            # If we genuinely have no URL AND no title → not applicable, let other verifiers run
            if not url and not title:
                logger.info(f"[BrowserVerifier] No URL or title available (Playwright absent, no window data) → skipping")
                return None

            checks = []
            confidence = 1.0

            if "url_contains" in action.expected_state:
                expected_url = action.expected_state["url_contains"].lower()
                # Also accept match in page title (Chrome shows page title in window title)
                url_ok = expected_url in url.lower() or expected_url in title.lower()
                checks.append(f"url/title '{url or title}' {'✓' if url_ok else '✗'} contains '{expected_url}'")
                if not url_ok:
                    confidence = min(confidence, 0.2)

            if "page_title_contains" in action.expected_state:
                expected_t = action.expected_state["page_title_contains"].lower()
                title_ok = expected_t in title.lower()
                checks.append(f"title '{title}' {'✓' if title_ok else '✗'} contains '{expected_t}'")
                if not title_ok:
                    confidence = min(confidence, 0.2)

            passed = confidence >= 0.8
            return VerificationCheck(
                name=self.name,
                passed=passed,
                confidence=confidence,
                detail=" | ".join(checks),
            )
        except Exception as e:
            return VerificationCheck(name=self.name, passed=False, confidence=0.0,
                                     detail=f"Browser verify error: {e}")




# ── 4. FileVerifier ─────────────────────────────────────────────────────────────
class FileVerifier(Verifier):
    name = "FileVerifier"

    def _applicable(self, action: Action) -> bool:
        return "file_exists" in action.expected_state

    async def verify(self, action: Action, obs: Observation) -> Optional[VerificationCheck]:
        if not self._applicable(action):
            return None
        path = action.expected_state["file_exists"]
        exists = os.path.exists(path)
        detail = f"File '{path}' {'exists' if exists else 'NOT found'}."
        if exists:
            size = os.path.getsize(path)
            detail += f" Size: {size} bytes."
        return VerificationCheck(name=self.name, passed=exists, confidence=1.0, detail=detail)


# ── 5. NetworkVerifier ──────────────────────────────────────────────────────────
class NetworkVerifier(Verifier):
    name = "NetworkVerifier"

    def _applicable(self, action: Action) -> bool:
        return "http_ok" in action.expected_state

    async def verify(self, action: Action, obs: Observation) -> Optional[VerificationCheck]:
        if not self._applicable(action):
            return None
        url = action.expected_state["http_ok"]
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=8.0) as client:
                resp = await client.get(url)
                passed = resp.status_code < 400
                return VerificationCheck(
                    name=self.name,
                    passed=passed,
                    confidence=0.95,
                    detail=f"GET {url} → HTTP {resp.status_code}",
                )
        except Exception as e:
            return VerificationCheck(name=self.name, passed=False, confidence=0.0,
                                     detail=f"Network check error: {e}")


# ── 6. OCRVerifier ──────────────────────────────────────────────────────────────
class OCRVerifier(Verifier):
    name = "OCRVerifier"

    def _applicable(self, action: Action) -> bool:
        return "ocr_contains" in action.expected_state or "ocr_contains_any" in action.expected_state

    async def verify(self, action: Action, obs: Observation) -> Optional[VerificationCheck]:
        if not self._applicable(action):
            return None

        # Use OCR text already captured in observation (preferred)
        ocr_text = obs.screen_state.get("ocr_text", "").lower()

        # If not available, take a fresh screenshot and OCR it
        if not ocr_text:
            try:
                from app.vision.screen_reader import screen_reader
                screenshot_path = screen_reader.take_screenshot()
                ocr_text = screen_reader.ocr_screen(screenshot_path).lower()
            except Exception as e:
                return VerificationCheck(name=self.name, passed=False, confidence=0.0,
                                         detail=f"OCR capture error: {e}")

        # Check 'ocr_contains_any' (any single match is sufficient for success)
        if "ocr_contains_any" in action.expected_state:
            any_kws = action.expected_state["ocr_contains_any"]
            if isinstance(any_kws, str):
                any_kws = [any_kws]
            any_matched = [kw for kw in any_kws if kw.lower() in ocr_text]
            if any_matched:
                return VerificationCheck(
                    name=self.name,
                    passed=True,
                    confidence=0.88,
                    detail=f"OCR found target keyword(s): {', '.join(any_matched)}",
                )
            elif "ocr_contains" not in action.expected_state:
                return VerificationCheck(
                    name=self.name,
                    passed=False,
                    confidence=0.20,
                    detail=f"OCR: none of target keywords ({', '.join(any_kws)}) found",
                )

        # Check 'ocr_contains'
        keywords = action.expected_state.get("ocr_contains", [])
        if isinstance(keywords, str):
            keywords = [keywords]

        matched = [kw for kw in keywords if kw.lower() in ocr_text]
        ratio = len(matched) / len(keywords) if keywords else 0.0
        passed = ratio >= 0.5 or len(matched) >= 1
        confidence = 0.75 + 0.20 * ratio if passed else 0.20

        detail = (f"OCR: matched {len(matched)}/{len(keywords)} keywords "
                  f"({', '.join(matched) or 'none'} found).")
        return VerificationCheck(name=self.name, passed=passed, confidence=confidence, detail=detail)


# ── 7. VisionVerifier ───────────────────────────────────────────────────────────
class VisionVerifier(Verifier):
    """Last-resort: Gemma3:4b vision model via /api/chat."""
    name = "VisionVerifier"

    def _applicable(self, action: Action) -> bool:
        return "vision_prompt" in action.expected_state

    async def verify(self, action: Action, obs: Observation) -> Optional[VerificationCheck]:
        if not self._applicable(action):
            return None
        prompt = action.expected_state["vision_prompt"]
        screenshot_path = obs.screen_state.get("screenshot_path", "")

        if not screenshot_path or not os.path.exists(screenshot_path):
            try:
                from app.vision.screen_reader import screen_reader
                screenshot_path = screen_reader.take_screenshot()
            except Exception as e:
                logger.info(f"[VisionVerifier] Screenshot capture skipped: {e}")
                return None
        try:
            from PIL import Image
            import io
            img = Image.open(screenshot_path)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            img_b64 = base64.b64encode(buf.getvalue()).decode()

            ollama_url = "http://localhost:11434"
            payload = {
                "model": "gemma3:4b",
                "messages": [{
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        "Reply with exactly one of: YES or NO. "
                        "YES means you can see what was asked on the screen. NO means you cannot."
                    ),
                    "images": [img_b64],
                }],
                "stream": False,
            }
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{ollama_url}/api/chat", json=payload)
                if resp.status_code != 200:
                    logger.info(f"[VisionVerifier] Gemma3 returned status {resp.status_code} → skipping vision check")
                    return None
                data = resp.json()
                answer = data.get("message", {}).get("content", "").strip().upper()
                if not answer:
                    return None
                passed = answer.startswith("YES")
                return VerificationCheck(
                    name=self.name,
                    passed=passed,
                    confidence=0.80 if passed else 0.30,
                    detail=f"Gemma3 response: '{answer[:120]}'",
                )
        except Exception as e:
            logger.info(f"[VisionVerifier] Vision model unavailable ({e}) → skipping vision check")
            return None



# ── VerificationEngine ──────────────────────────────────────────────────────────
class VerificationEngine:
    """
    Dispatches to the appropriate verifier chain based on action.expected_state keys.
    Returns a VerificationResult with aggregated outcome and all individual checks.

    Success criteria:
      - Any single check passes with confidence ≥ 0.8  (high-confidence deterministic), OR
      - Majority (>50%) of all checks pass at any confidence level
    """

    def __init__(self):
        # Order matters: fastest/most reliable first
        self._verifiers: List[Verifier] = [
            ProcessVerifier(),
            WindowVerifier(),
            BrowserVerifier(),
            FileVerifier(),
            NetworkVerifier(),
            OCRVerifier(),
            VisionVerifier(),  # last resort
        ]

    async def verify(self, action: Action, obs: Observation) -> VerificationResult:
        """Run all applicable verifiers and aggregate results."""
        checks: List[VerificationCheck] = []

        for verifier in self._verifiers:
            if not verifier._applicable(action):
                continue
            logger.info(f"[VerificationEngine] Running {verifier.name} for action '{action.description}'")
            check = await verifier.verify(action, obs)
            if check:
                checks.append(check)
                logger.info(f"[VerificationEngine] {verifier.name}: passed={check.passed} "
                            f"confidence={check.confidence:.2f} | {check.detail}")
                # Short-circuit on high-confidence success (≥0.8)
                if check.passed and check.confidence >= 0.8:
                    return VerificationResult(
                        success=True,
                        confidence=check.confidence,
                        checks=checks,
                        reason=f"✅ {verifier.name} confirmed: {check.detail}",
                    )

        if not checks:
            # No verifiers applied → treat as success (no check configured)
            return VerificationResult(
                success=True,
                confidence=0.5,
                checks=[],
                reason="No verifiers configured for this action (assumed success).",
            )

        # Majority vote among all checks
        passed_count = sum(1 for c in checks if c.passed)
        majority = passed_count > len(checks) / 2
        best_conf = max((c.confidence for c in checks if c.passed), default=0.0)
        failed_details = " | ".join(c.detail for c in checks if not c.passed)

        return VerificationResult(
            success=majority,
            confidence=best_conf if majority else 0.0,
            checks=checks,
            reason=(
                f"✅ Majority passed ({passed_count}/{len(checks)})."
                if majority
                else f"❌ Majority failed ({passed_count}/{len(checks)}): {failed_details}"
            ),
        )


# Singleton
verification_engine = VerificationEngine()
