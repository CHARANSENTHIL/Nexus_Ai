"""
Vision tools for the Nexus AI agent pipeline.
Docker-safe: all tools return graceful error messages if vision is unavailable.
"""
from langchain_core.tools import tool


@tool
def take_screenshot(filename: str = "") -> dict:
    """Capture a screenshot of the entire screen. Returns the file path."""
    from app.vision.screen_reader import screen_reader
    path = screen_reader.take_screenshot(filename or None)
    if path:
        return {"success": True, "message": f"Screenshot saved: {path}", "path": path}
    return {"success": False, "error": "Screenshot unavailable (no display or mss not installed)"}


@tool
def ocr_screen(screenshot_path: str = "") -> dict:
    """Run OCR text extraction on the screen or a given screenshot file."""
    from app.vision.screen_reader import screen_reader
    text = screen_reader.ocr_screen(screenshot_path or None)
    if text:
        return {"success": True, "text": text[:2000], "char_count": len(text)}
    return {"success": False, "error": "OCR unavailable (no Tesseract or no display)"}


@tool
def find_error_on_screen(screenshot_path: str = "") -> dict:
    """Scan the screen for error messages (exceptions, tracebacks, failures)."""
    from app.vision.screen_reader import screen_reader
    result = screen_reader.find_error(screenshot_path or None)
    if result["found"]:
        return {
            "success": True,
            "errors_found": len(result["errors"]),
            "errors": result["errors"],
        }
    return {"success": True, "errors_found": 0, "message": "No errors detected on screen"}


@tool
def analyze_desktop(screenshot_path: str = "") -> dict:
    """Analyze the desktop to find file/folder names using OCR."""
    from app.vision.screen_reader import screen_reader
    result = screen_reader.analyze_desktop(screenshot_path or None)
    return result


@tool
def get_vision_status() -> dict:
    """Check what vision capabilities are available in this environment."""
    from app.vision.screen_reader import screen_reader
    return screen_reader.get_capabilities()


@tool
def autonomous_screen_loop(goal: str, max_steps: int = 5) -> dict:
    """Run an autonomous Observer-Executor closed loop: Observe screen -> PyAutoGUI action -> Verify -> Recover."""
    import asyncio
    from app.vision.computer_agent import computer_agent
    try:
        res = asyncio.run(computer_agent.run_screen_loop(goal=goal, max_steps=max_steps))
        return res
    except Exception as e:
        return {"success": False, "error": str(e)}

