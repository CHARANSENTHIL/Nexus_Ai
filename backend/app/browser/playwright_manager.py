"""
Playwright Manager — Central manager owning Playwright browser instances and sessions.
Prevents multiple agents from instantiating redundant browser objects.
Supports Chromium, Edge, and Firefox with HTTP fallback.
"""
import os
import asyncio
import logging
import tempfile
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Try importing playwright
HAS_PLAYWRIGHT = False
try:
    from playwright.async_api import async_playwright, Playwright, Browser, Page, BrowserContext
    HAS_PLAYWRIGHT = True
    logger.info("[PlaywrightManager] Playwright library available.")
except ImportError:
    logger.info("[PlaywrightManager] Playwright library not installed. Using HTTP fallback.")


class PlaywrightManager:
    """Centralized manager for Playwright browser automation."""

    def __init__(self):
        self._playwright: Optional[Any] = None
        self._browser: Optional[Any] = None
        self._context: Optional[Any] = None
        self._page: Optional[Any] = None
        self._current_url: str = ""
        self._browser_type: str = "chromium"

    async def initialize(self, browser_name: str = "chromium", headless: bool = True) -> str:
        """Initialize or switch browser instance (chromium, msedge, firefox)."""
        if not HAS_PLAYWRIGHT:
            self._browser_type = browser_name
            return f"Browser set to '{browser_name}' (HTTP Fallback mode)."

        try:
            if not self._playwright:
                self._playwright = await async_playwright().start()

            if self._browser:
                await self._browser.close()

            b_type = browser_name.lower()
            if b_type == "msedge" or b_type == "edge":
                self._browser = await self._playwright.chromium.launch(channel="msedge", headless=headless)
            elif b_type == "firefox":
                self._browser = await self._playwright.firefox.launch(headless=headless)
            else:
                self._browser = await self._playwright.chromium.launch(headless=headless)

            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()
            self._browser_type = browser_name
            logger.info(f"[PlaywrightManager] Initialized {browser_name} (headless={headless})")
            return f"✅ Browser '{browser_name}' started successfully."
        except Exception as e:
            logger.warning(f"[PlaywrightManager] Playwright launch error ({e}). Using HTTP fallback.")
            return f"Browser initialized in HTTP mode ({e})"

    async def open_url(self, url: str) -> str:
        """Navigate to a URL."""
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "https://" + url

        self._current_url = url

        if HAS_PLAYWRIGHT and self._page:
            try:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=15000)
                title = await self._page.title()
                return f"✅ Navigated to: {url} (Title: '{title}')"
            except Exception as e:
                logger.warning(f"[PlaywrightManager] Playwright goto failed ({e}), trying httpx...")

        # HTTP fallback
        try:
            import httpx
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                resp = await client.get(url)
                return f"✅ Connected to: {url} (Status: {resp.status_code}, Bytes: {len(resp.content)})"
        except Exception as e:
            return f"❌ Failed to connect to {url}: {e}"

    async def search_web(self, query: str) -> str:
        """Search DuckDuckGo / Google for a query and return top results."""
        search_url = f"https://html.duckduckgo.com/html/?q={query.replace(' ', '+')}"
        return await self.open_url(search_url)

    async def read_page(self) -> str:
        """Extract main text content from current page."""
        if HAS_PLAYWRIGHT and self._page:
            try:
                text = await self._page.inner_text("body")
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                clean_text = "\n".join(lines[:50])
                return f"📄 Page Content ({self._current_url}):\n{clean_text[:1500]}"
            except Exception as e:
                logger.warning(f"[PlaywrightManager] inner_text error: {e}")

        # HTTP fallback
        if self._current_url:
            try:
                import httpx
                from bs4 import BeautifulSoup
                async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
                    resp = await client.get(self._current_url)
                    soup = BeautifulSoup(resp.text, "html.parser")
                    text = soup.get_text(separator="\n", strip=True)
                    lines = [l for l in text.split("\n") if len(l) > 20]
                    return f"📄 Page Content ({self._current_url}):\n" + "\n".join(lines[:30])
            except Exception as e:
                return f"Error reading page text: {e}"

        return "No active page open. Use open_url first."

    async def click_element(self, selector: str) -> str:
        """Click an HTML element by selector or text."""
        if HAS_PLAYWRIGHT and self._page:
            try:
                await self._page.click(selector, timeout=5000)
                return f"✅ Clicked element matching: '{selector}'"
            except Exception as e:
                return f"❌ Click failed on '{selector}': {e}"
        return f"Click simulated for '{selector}' (No active browser DOM context)."

    async def fill_form(self, selector: str, value: str) -> str:
        """Fill a form input field."""
        if HAS_PLAYWRIGHT and self._page:
            try:
                await self._page.fill(selector, value, timeout=5000)
                return f"✅ Filled element '{selector}' with text."
            except Exception as e:
                return f"❌ Fill failed on '{selector}': {e}"
        return f"Form fill simulated for '{selector}' = '{value}'."

    async def take_screenshot(self, save_path: Optional[str] = None) -> str:
        """Capture browser screenshot."""
        if not save_path:
            save_path = os.path.join(tempfile.gettempdir(), "browser_screenshot.png")

        if HAS_PLAYWRIGHT and self._page:
            try:
                await self._page.screenshot(path=save_path, full_page=False)
                return f"📸 Browser screenshot saved: {save_path}"
            except Exception as e:
                return f"❌ Browser screenshot failed: {e}"
        return "📸 Browser screenshot unavailable (Playwright browser session not active)."

    async def download_file(self, url: str, destination: Optional[str] = None) -> str:
        """Download file from URL."""
        if not destination:
            destination = os.path.join(os.path.expanduser("~"), "Downloads", os.path.basename(url))

        try:
            import httpx
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                resp = await client.get(url)
                with open(destination, "wb") as f:
                    f.write(resp.content)
            return f"✅ File downloaded to: {destination} ({len(resp.content)} bytes)"
        except Exception as e:
            return f"❌ Download failed for {url}: {e}"

    async def close_browser(self) -> str:
        """Close browser context."""
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None
            return "✅ Browser closed cleanly."
        except Exception as e:
            return f"Browser closed: {e}"


# Singleton instance
playwright_manager = PlaywrightManager()
