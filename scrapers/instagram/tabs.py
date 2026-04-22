from __future__ import annotations

import asyncio

from playwright.async_api import Page

from scrapers.instagram.browser import BrowserSession


class TabPool:
    """Small async pool that reuses pre-opened Playwright tabs."""

    def __init__(self, session: BrowserSession, size: int) -> None:
        self._session = session
        self._size = max(size, 0)
        self._queue: asyncio.Queue[Page] = asyncio.Queue()
        self._tabs: list[Page] = []

    async def __aenter__(self) -> TabPool:
        for _ in range(self._size):
            tab = await self._session.new_page()
            self._tabs.append(tab)
            await self._queue.put(tab)
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def acquire(self) -> Page:
        return await self._queue.get()

    async def release(self, tab: Page) -> None:
        await self._queue.put(tab)

    async def close(self) -> None:
        for tab in self._tabs:
            await tab.close()
        self._tabs.clear()
