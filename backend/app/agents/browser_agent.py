"""
Browser Agent — Specialized Agent for Playwright browser automation, web workflows & human handoff.
Sole owner of PlaywrightManager interface.
"""
from app.agents.tools.browser_tools import (
    open_browser,
    open_url,
    search_web,
    read_page,
    click_element,
    fill_form,
    inject_domain_credentials,
    autofill_profile_form,
    run_autonomous_browser_workflow,
    download_file,
    take_browser_screenshot,
    close_browser,
)

BROWSER_AGENT_ROLE = (
    "a Playwright Web Automation Specialist. Navigate, search, extract text, fill forms, "
    "inject encrypted credentials, execute autonomous multi-step web workflows, handle CAPTCHA/2FA handoff, "
    "and manage browser contexts cleanly."
)

browser_tools = [
    open_browser,
    open_url,
    search_web,
    read_page,
    click_element,
    fill_form,
    inject_domain_credentials,
    autofill_profile_form,
    run_autonomous_browser_workflow,
    download_file,
    take_browser_screenshot,
    close_browser,
]
