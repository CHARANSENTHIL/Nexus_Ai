"""Browser package — central Playwright manager and browser automation service."""
from app.browser.playwright_manager import playwright_manager, PlaywrightManager

__all__ = ["playwright_manager", "PlaywrightManager"]
