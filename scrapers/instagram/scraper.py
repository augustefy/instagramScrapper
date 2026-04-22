from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Response, TimeoutError as PlaywrightTimeout

from app.core.log import get_logger
from bench import Bench
from exceptions import PageLoadError, SelectorsOutdatedError
from scrapers.base import BaseScraper, SocialPost
from scrapers.instagram.browser import BrowserSession
from scrapers.instagram.config import (
    BASE_URL,
    BLOCKED_RESOURCE_TYPES,
    MAX_RETRY_ATTEMPTS,
    RESPONSE_HANDLER_WAIT,
    SELECTORS,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_POST_LOAD,
    WORKERS,
)
from scrapers.instagram.dom import DOMParser, parse_media_api_data
from scrapers.instagram.retry import RetryPolicy
from scrapers.instagram.tabs import TabPool
from scrapers.instagram.validators import validate_instagram_url, validate_post_count

logger = get_logger(__name__)

PLATFORM = "instagram"


class InstagramScraper(BaseScraper):
    """Pipeline Playwright pour collecter un profil Instagram."""

    def __init__(
        self,
        headless: bool = True,
        bench: Bench | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.bench = bench or Bench()
        self.headless = headless
        self._retry_policy = retry_policy or RetryPolicy(MAX_RETRY_ATTEMPTS)
        self._dom = DOMParser(self.bench)

    def scrape(self, url: str, n: int) -> list[SocialPost]:
        url = validate_instagram_url(url)
        n = validate_post_count(n)

        logger.info("Scraping demarre", extra={"url": url, "target_count": n})
        return asyncio.run(self._scrape_async(url, n))

    def health_check(self) -> dict[str, Any]:
        return asyncio.run(self._health_check_async())

    async def _health_check_async(self) -> dict[str, Any]:
        session = BrowserSession(headless=self.headless)
        page: Page | None = None

        try:
            await session.start()
            page = await session.new_page()
            response = await page.goto(
                BASE_URL,
                wait_until="domcontentloaded",
                timeout=min(TIMEOUT_PAGE_LOAD, 15000),
            )
            return {
                "headless": self.headless,
                "target_url": BASE_URL,
                "http_status": response.status if response else None,
                "page_title": await page.title(),
            }
        finally:
            if page is not None:
                await page.close()
            await session.close()

    async def _scrape_async(self, url: str, n: int) -> list[SocialPost]:
        session = BrowserSession(headless=self.headless)

        try:
            with self.bench.timer("driver_init"):
                await session.start()
                logger.info(
                    "Chromium initialise",
                    extra={
                        "workers": WORKERS,
                        "blocked_resources": list(BLOCKED_RESOURCE_TYPES),
                    },
                )

            page = await session.new_page()
            with self.bench.timer("page_load"):
                await self._load_profile(page, url)

            user_followers = await self._dom.get_user_followers(page)
            hrefs = await self._dom.collect_n_hrefs(page, n)
            await page.close()

            logger.info(f"Debut du scraping parallele : {len(hrefs)} posts ({WORKERS} workers)")

            pool_size = min(WORKERS, len(hrefs))
            async with TabPool(session, pool_size) as tab_pool:
                scraped = await self._scrape_with_retries(hrefs, tab_pool, user_followers)

            posts = [scraped[href] for href in hrefs if href in scraped]
        finally:
            await session.close()

        logger.info(
            f"Scraping termine : {len(posts)} posts recuperes",
            extra={"post_count": len(posts)},
        )
        return posts

    async def _load_profile(self, page: Page, url: str) -> None:
        logger.info(f"Navigation vers {url}")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_PAGE_LOAD)
        except PlaywrightTimeout as exc:
            raise PageLoadError(f"Timeout au chargement de {url}") from exc

        logger.info("Attente des posts...")
        await self._dom.dismiss_popup(page)
        try:
            await self._dom.wait_for_post_links(page, timeout=TIMEOUT_PAGE_LOAD)
        except SelectorsOutdatedError as exc:
            logger.error(
                "Impossible de trouver les posts. Les selecteurs sont probablement obsoletes.",
                extra={"error": str(exc)},
            )
            raise

    async def _scrape_with_retries(
        self,
        hrefs: list[str],
        tab_pool: TabPool,
        user_followers: int,
    ) -> dict[str, SocialPost]:
        scraped: dict[str, SocialPost] = {}
        pending = list(hrefs)

        with self.bench.timer("scrape_all_posts"):
            for attempt in self._retry_policy.attempts():
                if not pending:
                    break
                if attempt > 1:
                    logger.info(
                        f"  Retry #{attempt} - {len(pending)} post(s) a relancer",
                        extra={"remaining": len(pending)},
                    )

                tasks = [
                    self._scrape_post(href, tab_pool, user_followers)
                    for href in pending
                ]
                results = await asyncio.gather(*tasks)

                failed: list[str] = []
                for href, post in zip(pending, results):
                    if post:
                        scraped[href] = post
                        logger.info(
                            f"  [{len(scraped)}/{len(hrefs)}] {post.url}",
                            extra={"media_type": post.media_type},
                        )
                    else:
                        failed.append(href)

                pending = failed

            if pending:
                logger.warning(
                    f"  {len(pending)} post(s) en echec apres "
                    f"{self._retry_policy.max_attempts} tentatives",
                    extra={"failed_count": len(pending)},
                )

        return scraped

    async def _scrape_post(
        self,
        href: str,
        tab_pool: TabPool,
        user_followers: int,
    ) -> SocialPost | None:
        post_url = f"{BASE_URL}{href}"
        tab = await tab_pool.acquire()
        api_data: dict[str, Any] = {}

        async def on_response(response: Response) -> None:
            if "api/v1/media" not in response.url or "info" not in response.url or api_data:
                return

            try:
                body = await response.json()
                if not isinstance(body, dict):
                    return
                parsed = parse_media_api_data(body)
            except (PlaywrightError, TypeError, ValueError, OSError) as exc:
                logger.debug(
                    "Erreur parsing API response",
                    extra={"error": str(exc), "url": response.url},
                    exc_info=True,
                )
                return

            if parsed:
                api_data.update(parsed)
                logger.debug("API data captured", extra={"api_data": api_data})

        tab.on("response", on_response)
        try:
            await tab.goto(post_url, wait_until="commit", timeout=TIMEOUT_POST_LOAD)
            await tab.wait_for_selector(SELECTORS.POST_TIME, timeout=TIMEOUT_POST_LOAD)
            await asyncio.sleep(RESPONSE_HANDLER_WAIT)

            if api_data:
                return self._post_from_data(post_url, api_data, user_followers)

            data = await self._dom.extract_post_dom_data(tab)
            if not isinstance(data, dict):
                raise ValueError("Extraction DOM Instagram inattendue.")

            dom_data_clean = {key: value for key, value in data.items() if key != "_debug_text"}
            logger.debug("Fallback DOM extraction", extra={"dom_data": dom_data_clean})
            return self._post_from_data(post_url, data, user_followers)

        except PlaywrightTimeout:
            logger.warning(f"Timeout sur {post_url}")
            return None
        except (PlaywrightError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                f"Erreur sur {post_url}: {type(exc).__name__}: {exc}",
                exc_info=True,
            )
            return None
        finally:
            tab.remove_listener("response", on_response)
            await tab_pool.release(tab)

    @staticmethod
    def _post_from_data(
        post_url: str,
        data: dict[str, Any],
        user_followers: int,
    ) -> SocialPost:
        return SocialPost(
            platform=PLATFORM,
            url=post_url,
            caption=str(data.get("caption", "")),
            timestamp=str(data.get("timestamp", "")),
            likes_count=int(data.get("likes_count") or 0),
            comments_count=int(data.get("comments_count") or 0),
            media_type=str(data.get("media_type", "")),
            user_followers=user_followers,
        )
