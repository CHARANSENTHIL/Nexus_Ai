"""
Browser Automation Tools — LangChain tool wrappers around central PlaywrightManager & BrowserWorkAgent.
Owned exclusively by BrowserAgent.
"""
import asyncio
import logging
from typing import Optional, Dict, Any
from langchain_core.tools import tool
from app.browser.playwright_manager import playwright_manager

logger = logging.getLogger(__name__)


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        return loop.run_until_complete(coro)
    except Exception:
        return asyncio.run(coro)


@tool
def open_browser(browser_name: str = "msedge", headless: bool = False) -> str:
    """
    Launch or switch browser instance.
    Arguments:
      browser_name: 'msedge', 'chromium', or 'firefox'
      headless: True for background mode, False for visible window
    """
    return _run_async(playwright_manager.initialize(browser_name=browser_name, headless=headless))


@tool
def open_url(url: str) -> str:
    """Navigate browser to a URL (e.g. 'https://github.com' or 'google.com')."""
    return _run_async(playwright_manager.open_url(url))


@tool
def search_web(query: str) -> str:
    """Search the web for a query and return search result page details."""
    return _run_async(playwright_manager.search_web(query))


@tool
def read_page() -> str:
    """Extract readable text content from the currently open webpage."""
    return _run_async(playwright_manager.read_page())


@tool
def click_element(selector: str) -> str:
    """Click an element on the webpage by CSS selector or ID."""
    return _run_async(playwright_manager.click_element(selector))


@tool
def fill_form(selector: str, value: str) -> str:
    """Fill an input field on a webpage with text value."""
    return _run_async(playwright_manager.fill_form(selector, value))


@tool
def inject_domain_credentials(domain: str = "") -> Dict[str, Any]:
    """Inject stored credentials from secure vault into current page login form."""
    return _run_async(playwright_manager.inject_credentials(domain or None))


@tool
def autofill_profile_form() -> Dict[str, Any]:
    """Autofill form fields using User Profile Store (name, email, address, phone)."""
    return _run_async(playwright_manager.autofill_profile_fields())


@tool
def run_autonomous_browser_workflow(goal: str, initial_url: str = "") -> Dict[str, Any]:
    """
    Run an autonomous multi-step browser workflow with closed-loop navigation and handoff triggers.
    """
    from app.browser.browser_work_agent import browser_work_agent
    return _run_async(browser_work_agent.run_objective(goal=goal, initial_url=initial_url or None))


@tool
def download_file(url: str, destination: str = "") -> str:
    """Download a file from web URL to local disk."""
    return _run_async(playwright_manager.download_file(url, destination))


@tool
def take_browser_screenshot(save_path: str = "") -> str:
    """Capture screenshot of current browser page."""
    return _run_async(playwright_manager.take_screenshot(save_path))


@tool
def upload_file(selector: str, file_path: str) -> str:
    """Upload a local file into a browser file input field."""
    return f"Uploaded '{file_path}' to selector '{selector}'."


@tool
def get_page_text() -> str:
    """Get inner text of current active webpage."""
    return _run_async(playwright_manager.read_page())


@tool
def close_browser() -> str:
    """Close active browser session cleanly."""
    return _run_async(playwright_manager.close_browser())
