"""
Nexus AI Vision Layer — screen capture, OCR, and error detection.
Ported from JIN/JARVIS project. Docker-safe: gracefully degrades
when display/Tesseract is unavailable (no pyautogui/pynput).
"""
import os
import re
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

TESSERACT_PATH = os.getenv("TESSERACT_PATH", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
SCREENSHOT_DIR = os.path.abspath(os.getenv("SCREENSHOT_DIR", "./screenshots"))


class ScreenReader:
    """
    Screen capture and OCR analysis.
    All methods return safe defaults if running headless (Docker).
    """

    def __init__(self):
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        self._ocr_available = False
        self._capture_available = False
        self._setup()

    def _setup(self):
        """Check available capabilities at init time."""
        # Check screen capture (mss)
        try:
            import mss
            self._capture_available = True
        except ImportError:
            logger.info("[Vision] mss not installed — screen capture disabled")

        # Check OCR (pytesseract)
        try:
            import pytesseract
            if os.path.exists(TESSERACT_PATH):
                pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
                self._ocr_available = True
            else:
                logger.info(f"[Vision] Tesseract not found at {TESSERACT_PATH} — OCR disabled")
        except ImportError:
            logger.info("[Vision] pytesseract not installed — OCR disabled")

    def take_screenshot(self, filename: str = None) -> str:
        """
        Capture the entire screen. Returns file path or empty string on failure.
        Tries mss first, then pyautogui, then PIL.ImageGrab as fallbacks.
        Docker-safe: returns empty string if no display available.
        """
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = filename or f"screenshot_{ts}.png"
        path = os.path.join(SCREENSHOT_DIR, filename)
        latest_path = os.path.join(SCREENSHOT_DIR, "latest.png")

        # Method 1: mss
        try:
            import mss
            from PIL import Image
            with mss.mss() as sct:
                monitor = sct.monitors[0]
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                img.save(path)
                img.save(latest_path)
            self._capture_available = True
            logger.info(f"[Vision] Screenshot saved (mss): {path}")
            return path
        except Exception as e1:
            logger.warning(f"[Vision] mss screenshot failed: {e1}")

        # Method 2: pyautogui.screenshot()
        try:
            import pyautogui
            img = pyautogui.screenshot()
            img.save(path)
            img.save(latest_path)
            self._capture_available = True
            logger.info(f"[Vision] Screenshot saved (pyautogui): {path}")
            return path
        except Exception as e2:
            logger.warning(f"[Vision] pyautogui screenshot failed: {e2}")

        # Method 3: PIL.ImageGrab
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(all_screens=True)
            img.save(path)
            img.save(latest_path)
            self._capture_available = True
            logger.info(f"[Vision] Screenshot saved (ImageGrab): {path}")
            return path
        except Exception as e3:
            logger.warning(f"[Vision] PIL ImageGrab failed: {e3}")

        return ""


    def ocr_screen(self, screenshot_path: str = None) -> str:
        """
        Run OCR on the screen (or a given screenshot).
        Returns extracted text or empty string.
        """
        if not self._ocr_available:
            return ""
        try:
            import pytesseract
            from PIL import Image

            if screenshot_path and os.path.exists(screenshot_path):
                img = Image.open(screenshot_path)
            else:
                path = self.take_screenshot()
                if not path:
                    return ""
                img = Image.open(path)

            text = pytesseract.image_to_string(img)
            return text
        except Exception as e:
            logger.warning(f"[Vision] OCR failed: {e}")
            return ""

    def find_error(self, screenshot_path: str = None) -> dict:
        """
        Scan screen for common error patterns via OCR.
        Returns {"found": bool, "errors": list, "full_text": str}.
        """
        text = self.ocr_screen(screenshot_path)
        if not text:
            return {"found": False, "errors": [], "full_text": ""}

        error_patterns = [
            r"(?i)(error|exception|traceback|failed|failure|crash|fatal)",
            r"(?i)(ModuleNotFoundError|ImportError|SyntaxError|TypeError|ValueError|AttributeError)",
            r"(?i)(cannot find|not found|does not exist|permission denied|access denied)",
            r"(?i)(connection refused|timeout|unreachable)",
        ]

        found_errors = []
        lines = text.splitlines()
        for i, line in enumerate(lines):
            for pattern in error_patterns:
                if re.search(pattern, line):
                    start = max(0, i - 1)
                    end = min(len(lines), i + 3)
                    context = "\n".join(lines[start:end]).strip()
                    if context and context not in found_errors:
                        found_errors.append(context)
                    break

        return {
            "found": len(found_errors) > 0,
            "errors": found_errors[:5],
            "full_text": text,
        }

    def find_errors_on_screen(self, screenshot_path: str = None) -> list:
        """Scan screen and return list of detected error strings."""
        res = self.find_error(screenshot_path)
        return res.get("errors", [])

    def find_text_on_screen(self, search_text: str, screenshot_path: str = None) -> bool:

        """Check if specific text appears on screen."""
        screen_text = self.ocr_screen(screenshot_path)
        return search_text.lower() in screen_text.lower()

    def analyze_desktop(self, screenshot_path: str = None) -> dict:
        """
        Analyze the desktop and extract file/folder names via OCR.
        Returns {"status": str, "items": list, "screenshot_path": str}.
        """
        if not self._ocr_available:
            return {
                "status": "unavailable",
                "message": "OCR not available. Install pytesseract + Tesseract.",
                "items": [],
            }

        try:
            import pytesseract
            from PIL import Image

            if screenshot_path and os.path.exists(screenshot_path):
                img = Image.open(screenshot_path)
            else:
                screenshot_path = self.take_screenshot()
                if not screenshot_path:
                    return {"status": "error", "message": "Screenshot failed", "items": []}
                img = Image.open(screenshot_path)

            data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

            items = []
            seen = set()
            valid_extensions = {
                '.py', '.js', '.java', '.cpp', '.c', '.txt', '.md', '.pdf',
                '.doc', '.docx', '.xls', '.xlsx', '.zip', '.rar', '.jpg',
                '.png', '.mp4', '.exe', '.html', '.css', '.json', '.yml',
            }
            skip_words = {
                'the', 'and', 'or', 'but', 'file', 'edit', 'view', 'run',
                'help', 'code', 'output', 'terminal', 'exit', 'input',
                'status', 'search', 'settings', 'account', 'http', 'https',
            }

            for i, text in enumerate(data["text"]):
                if not text.strip():
                    continue
                conf = int(data["conf"][i])
                if conf < 60:
                    continue
                # Skip taskbar area
                if data["top"][i] > 1400:
                    continue
                if data["height"][i] < 15:
                    continue

                name = text.strip()
                name_lower = name.lower()

                if len(name) < 3 or name_lower in skip_words:
                    continue
                if not any(c.isalpha() for c in name):
                    continue
                if name in seen:
                    continue

                has_ext = any(name_lower.endswith(ext) for ext in valid_extensions)
                has_sep = '_' in name or '-' in name

                if (has_ext and conf >= 70) or (has_sep and len(name) >= 5 and conf >= 75) or (conf >= 90 and len(name) >= 5):
                    items.append(name)
                    seen.add(name)

            return {
                "status": "success",
                "message": f"Found {len(items)} desktop items",
                "items": items,
                "screenshot_path": screenshot_path,
            }

        except Exception as e:
            logger.error(f"[Vision] analyze_desktop failed: {e}")
            return {"status": "error", "message": str(e), "items": []}

    def get_capabilities(self) -> dict:
        """Report what's available in this environment."""
        return {
            "capture": self._capture_available,
            "ocr": self._ocr_available,
            "tesseract_path": TESSERACT_PATH if self._ocr_available else None,
            "screenshot_dir": SCREENSHOT_DIR,
        }


# Singleton
screen_reader = ScreenReader()
