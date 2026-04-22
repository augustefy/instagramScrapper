from __future__ import annotations

from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from exceptions import BrowserError
from scrapers.instagram.config import BLOCKED_RESOURCE_TYPES, USER_AGENT, VIEWPORT


class BrowserSession:
    """Owns the Playwright lifecycle and shared browser context."""

    def __init__(
        self,
        *,
        headless: bool,
        user_agent: str = USER_AGENT,
        viewport: dict[str, int] | None = None,
        blocked_resource_types: set[str] | None = None,
    ) -> None:
        self.headless = headless
        self.user_agent = user_agent
        self.viewport = viewport or VIEWPORT
        self.blocked_resource_types = blocked_resource_types or BLOCKED_RESOURCE_TYPES
        self._playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None

    async def start(self) -> None:
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(
            user_agent=self.user_agent,
            viewport=self.viewport,
        )
        await self.context.route("**/*", self._route_handler)

    async def new_page(self) -> Page:
        if self.context is None:
            raise BrowserError("BrowserSession non initialisee.")
        return await self.context.new_page()

    async def close(self) -> None:
        if self.context is not None:
            await self.context.close()
            self.context = None
        if self.browser is not None:
            await self.browser.close()
            self.browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def _route_handler(self, route: Any, request: Any) -> None:
        if request.resource_type in self.blocked_resource_types:
            await route.abort()
        else:
            await route.continue_()
