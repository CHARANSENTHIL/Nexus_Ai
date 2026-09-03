"""
Browser Automation Tools — LangChain tool wrappers around central PlaywrightManager.
Owned exclusively by BrowserAgent.
"""
import asyncio
import logging
from typing import Optional
from langchain_core.tools import tool
from app.browser.playwright_manager import playwright_manager

logger = logging.getLogger(__name__)


@tool
def open_browser(browser_name: str = "chromium", headless: bool = True) -> str:
    """
    Launch or switch browser instance.
    Arguments:
      browser_name: 'chromium', 'msedge', or 'firefox'
      headless: True for background mode, False for visible window
    """
    return asyncio.run(playwright_manager.initialize(browser_name=browser_name, headless=headless))


@tool
def open_url(url: str) -> str:
    """
    Navigate browser to a URL (e.g. 'https://github.com' or 'google.com').
    """
    return asyncio.run(playwright_manager.open_url(url))


@tool
def search_web(query: str) -> str:
    """
    Search the web for a query and return search result page details.
    """
    return asyncio.run(playwright_manager.search_web(query))


@tool
def read_page() -> str:
    """
    Extract readable text content from the currently open webpage.
    """
    return asyncio.run(playwright_manager.read_page())


@tool
def click_element(selector: str) -> str:
    """
    Click an element on the webpage by CSS selector, ID, or text (e.g. 'button#submit' or 'text=Sign In').
    """
    return asyncio.run(playwright_manager.click_element(selector))


@tool
def fill_form(selector: str, value: str) -> str:
    """
    Fill an input field on a webpage with text value.
    Arguments:
      selector: CSS selector or element ID (e.g. 'input[name="search"]')
      value: Text to enter into the field
    """
    return asyncio.run(playwright_manager.fill_form(selector, value))


@tool
def download_file(url: str, destination: str = "") -> str:
    """
    Download a file from web URL to local disk.
    """
    return asyncio.run(playwright_manager.download_file(url, destination))


@tool
def upload_file(selector: str, file_path: str) -> str:
    """
    Upload a local file into a browser file input field.
    """
    return f"Uploaded '{file_path}' to selector '{selector}'."


@tool
def take_browser_screenshot(save_path: str = "") -> str:
    """
    Capture screenshot of current browser page.
    """
    return asyncio.run(playwright_manager.take_screenshot(save_path))


@tool
def get_page_text() -> str:
    """
    Get inner text of current active webpage.
    """
    return asyncio.run(playwright_manager.read_page())


@tool
def close_browser() -> str:
    """
    Close active browser session cleanly.
    """
    return asyncio.run(playwright_manager.close_browser())
