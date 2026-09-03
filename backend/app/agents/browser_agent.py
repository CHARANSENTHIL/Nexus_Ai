"""
Browser Agent — Specialized Agent for Playwright browser automation & web management.
Sole owner of PlaywrightManager interface.
"""
from app.agents.tools.browser_tools import (
    open_browser,
    open_url,
    search_web,
    read_page,
    click_element,
    fill_form,
    download_file,
    upload_file,
    take_browser_screenshot,
    get_page_text,
    close_browser,
)

BROWSER_AGENT_ROLE = (
    "a Playwright Web Automation Specialist. Navigate, search, extract text, fill forms, "
    "click elements, download files, and manage Chromium, Edge, and Firefox browser contexts cleanly."
)

browser_tools = [
    open_browser,
    open_url,
    search_web,
    read_page,
    click_element,
    fill_form,
    download_file,
    upload_file,
    take_browser_screenshot,
    get_page_text,
    close_browser,
]
