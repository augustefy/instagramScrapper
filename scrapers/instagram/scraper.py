import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, BrowserContext, TimeoutError as PlaywrightTimeout

from bench import Bench
from exceptions import PageLoadError, SelectorsOutdatedError
from logging_setup import setup_logging
from scrapers.base import BaseScraper, SocialPost
from scrapers.instagram.config import (
    BASE_URL,
    BLOCKED_RESOURCE_TYPES,
    WORKERS,
    MAX_RETRY_ATTEMPTS,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_POST_LOAD,
    TIMEOUT_POPUP_DISMISS,
    TIMEOUT_SCROLL,
    POPUP_DISMISS_WAIT,
    SCROLL_POLL_INTERVAL,
    RESPONSE_HANDLER_WAIT,
    USER_AGENT,
    VIEWPORT,
    SELECTORS,
)
from scrapers.instagram.validators import validate_instagram_url, validate_post_count

logger = setup_logging(__name__)

PLATFORM = "instagram"


class InstagramScraper(BaseScraper):
    def __init__(self, headless: bool = True, bench: Optional[Bench] = None):
        self.bench = bench or Bench()
        self.headless = headless
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    # ------------------------------------------------------------------
    # Public entry point (sync wrapper)
    # ------------------------------------------------------------------

    def scrape(self, url: str, n: int) -> list[SocialPost]:
        url = validate_instagram_url(url)
        n = validate_post_count(n)

        logger.info(f"Scraping démarré", extra={"url": url, "target_count": n})
        posts = asyncio.run(self._scrape_async(url, n))
        return posts

    # ------------------------------------------------------------------
    # Async core
    # ------------------------------------------------------------------

    async def _scrape_async(self, url: str, n: int) -> list[SocialPost]:
        async with async_playwright() as pw:
            with self.bench.timer("driver_init"):
                browser = await pw.chromium.launch(headless=self.headless)
                context = await browser.new_context(
                    user_agent=USER_AGENT,
                    viewport=VIEWPORT,
                )
                await context.route("**/*", self._route_handler)
                logger.info("✓ Chromium initialisé", extra={"workers": WORKERS, "blocked_resources": list(BLOCKED_RESOURCE_TYPES)})

            page = await context.new_page()

            with self.bench.timer("page_load"):
                logger.info(f"Navigation vers {url}")
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_PAGE_LOAD)
                except PlaywrightTimeout as e:
                    raise PageLoadError(f"Timeout au chargement de {url}") from e

                logger.info("Attente des posts...")
                await self._dismiss_popup(page)
                try:
                    await self._wait_for_post_links(page, timeout=TIMEOUT_PAGE_LOAD)
                except SelectorsOutdatedError as e:
                    logger.error("Impossible de trouver les posts. Les sélecteurs sont probablement obsolètes.", extra={"error": str(e)})
                    raise

            user_followers = await self._get_user_followers(page)
            hrefs = await self._collect_n_hrefs(page, n)
            await page.close()

            logger.info(f"Début du scraping parallèle : {len(hrefs)} posts ({WORKERS} workers)")

            pool_size = min(WORKERS, len(hrefs))
            tab_pool: asyncio.Queue[Page] = asyncio.Queue()
            pooled_tabs: list[Page] = []
            for _ in range(pool_size):
                tab = await context.new_page()
                pooled_tabs.append(tab)
                await tab_pool.put(tab)

            scraped: dict[str, SocialPost] = {}
            pending = list(hrefs)
            attempt = 0

            with self.bench.timer("scrape_all_posts"):
                while pending and attempt < MAX_RETRY_ATTEMPTS:
                    attempt += 1
                    if attempt > 1:
                        logger.info(f"  Retry #{attempt} — {len(pending)} post(s) à relancer", extra={"remaining": len(pending)})

                    tasks = [self._scrape_post(href, tab_pool, user_followers) for href in pending]
                    results = await asyncio.gather(*tasks)

                    failed = []
                    for href, post in zip(pending, results):
                        if post:
                            scraped[href] = post
                            logger.info(f"  [{len(scraped)}/{len(hrefs)}] {post.url}", extra={"post_data": asdict(post)})
                        else:
                            failed.append(href)

                    pending = failed

                if pending:
                    logger.warning(f"  {len(pending)} post(s) en échec après {MAX_RETRY_ATTEMPTS} tentatives", extra={"failed_count": len(pending)})

            for tab in pooled_tabs:
                await tab.close()

            posts = [scraped[href] for href in hrefs if href in scraped]

            await context.close()
            await browser.close()

        logger.info(
            f"✓ Scraping terminé : {len(posts)} posts récupérés",
            extra={"output": [asdict(p) for p in posts]}
        )
        return posts

    # ------------------------------------------------------------------
    # Route handler
    # ------------------------------------------------------------------

    async def _route_handler(self, route, request):
        if request.resource_type in BLOCKED_RESOURCE_TYPES:
            await route.abort()
        else:
            await route.continue_()

    # ------------------------------------------------------------------
    # Récupération du nombre de followers
    # ------------------------------------------------------------------

    async def _get_user_followers(self, page: Page) -> int:
        try:
            followers = await page.evaluate(
                """() => {
                    const links = document.querySelectorAll('a[href*="/followers"]');
                    for (const link of links) {
                        const text = link.innerText;
                        if (text) {
                            const cleaned = text.match(/[\\d.]+/)?.[0] || "";
                            let num = parseFloat(cleaned);
                            if (text.includes("M")) num *= 1000000;
                            else if (text.includes("K")) num *= 1000;
                            if (num > 0) return Math.floor(num);
                        }
                    }
                    const allText = document.body.innerText;
                    const lines = allText.split('\\n');
                    for (let i = 0; i < lines.length; i++) {
                        if (lines[i].toLowerCase().includes('follower')) {
                            const match = lines[i].match(/[\\d,.]+/);
                            if (match) {
                                let num = parseFloat(match[0].replace(/,/g, ''));
                                if (lines[i].includes("M")) num *= 1000000;
                                else if (lines[i].includes("K")) num *= 1000;
                                if (num > 0) return Math.floor(num);
                            }
                        }
                    }
                    return 0;
                }"""
            )
            logger.debug(f"Followers détectés : {followers}")
            return followers
        except Exception as e:
            logger.debug(f"Erreur extraction followers", extra={"error": str(e)})
            return 0

    # ------------------------------------------------------------------
    # Collecte des hrefs (avec scroll)
    # ------------------------------------------------------------------

    async def _collect_n_hrefs(self, page: Page, n: int) -> list[str]:
        seen: set[str] = set()
        hrefs: list[str] = []
        scroll_count = 0

        while len(hrefs) < n:
            with self.bench.timer(f"collect_links#{scroll_count + 1}"):
                new_links = await self._collect_post_links(page)

            new_count = 0
            for href, pinned in new_links:
                if href in seen:
                    continue
                seen.add(href)
                if pinned:
                    logger.debug(f"  [épinglé, ignoré] {href}")
                    continue
                hrefs.append(href)
                logger.info(f"  [post] {BASE_URL}{href}")
                new_count += 1
                if len(hrefs) >= n:
                    break

            logger.info(f"  {new_count} nouveau(x) lien(s) — total : {len(hrefs)}/{n}")

            if len(hrefs) >= n:
                break

            scroll_count += 1
            with self.bench.timer(f"scroll#{scroll_count}"):
                if not await self._scroll_down(page):
                    logger.info("Fin de la page atteinte")
                    break

        return hrefs[:n]

    # ------------------------------------------------------------------
    # Collecte des liens dans la grille
    # ------------------------------------------------------------------

    async def _collect_post_links(self, page: Page) -> list[tuple[str, bool]]:
        try:
            raw = await page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]'))
                    .filter(a => /^\\/.+\\/(p|reel)\\/[A-Za-z0-9_-]+/.test(a.getAttribute('href')))
                    .map(a => {
                        const href = a.getAttribute('href');
                        const cell = a.closest('li, article, div[class]') || a.parentElement;
                        const pinned = !!(cell && Array.from(cell.children).some(
                            child => child.querySelector && child.querySelector('svg[aria-label*="pin"], svg[aria-label*="Pin"]')
                        ));
                        return [href, pinned];
                    })"""
            )
            return [(href, pinned) for href, pinned in raw]
        except Exception as e:
            logger.warning(f"Erreur lors de la collecte des liens", extra={"error": str(e)})
            return []

    # ------------------------------------------------------------------
    # Scraping d'un post (appelé en parallèle)
    # ------------------------------------------------------------------

    async def _scrape_post(self, href: str, tab_pool: "asyncio.Queue[Page]", user_followers: int) -> Optional[SocialPost]:
        post_url = f"{BASE_URL}{href}"
        tab = await tab_pool.get()

        api_data: dict = {}

        async def on_response(response):
            if "api/v1/media" in response.url and "info" in response.url and not api_data:
                try:
                    body = await response.json()
                    items = body.get("items", [])
                    if items:
                        item = items[0]
                        cap = item.get("caption") or {}
                        api_data["caption"] = cap.get("text", "") if isinstance(cap, dict) else ""
                        ts = item.get("taken_at")
                        if ts:
                            api_data["timestamp"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                        api_data["likes_count"] = item.get("like_count", 0)
                        api_data["comments_count"] = item.get("comment_count", 0)

                        if item.get("carousel_media_count"):
                            api_data["media_type"] = "carousel"
                        elif item.get("video_duration") or item.get("product_type") == "clips":
                            api_data["media_type"] = "reel" if item.get("product_type") == "clips" else "video"
                        else:
                            api_data["media_type"] = "image"

                        logger.debug("API data captured", extra={"api_data": api_data})
                except Exception as e:
                    logger.debug("Erreur parsing API response", extra={"error": str(e), "url": response.url})

        tab.on("response", on_response)
        try:
            await tab.goto(post_url, wait_until="commit", timeout=TIMEOUT_POST_LOAD)
            await tab.wait_for_selector(SELECTORS.POST_TIME, timeout=TIMEOUT_POST_LOAD)
            await asyncio.sleep(RESPONSE_HANDLER_WAIT)

            if api_data:
                return SocialPost(
                    platform=PLATFORM,
                    url=post_url,
                    caption=api_data.get("caption", ""),
                    timestamp=api_data.get("timestamp", ""),
                    likes_count=api_data.get("likes_count", 0),
                    comments_count=api_data.get("comments_count", 0),
                    media_type=api_data.get("media_type", ""),
                    user_followers=user_followers,
                )

            # Fallback : extraction directe via JS
            data = await tab.evaluate(f"""() => {{
                const time = document.querySelector("{SELECTORS.POST_TIME}");
                const captionSpan = document.querySelector("{SELECTORS.POST_CAPTION_SPAN}");
                const meta = document.querySelector("{SELECTORS.POST_META_DESCRIPTION}");

                function parseNumber(text) {{
                    if (!text) return 0;
                    let normalized = text.replace(/,/g, '.');
                    const match = normalized.match(/([\\d.]+)\\s*([MK])?/i);
                    if (!match) return 0;
                    let num = parseFloat(match[1]);
                    if (match[2]) {{
                        if (match[2].toUpperCase() === 'M') num *= 1000000;
                        if (match[2].toUpperCase() === 'K') num *= 1000;
                    }}
                    return Math.floor(num);
                }}

                let likes = 0;
                let comments = 0;
                let mediaType = "";

                const bodyText = document.body.innerText || "";
                const afficherMatch = bodyText.match(/Afficher les ([\\d\\s]+) commentaires/i);
                if (afficherMatch) {{
                    comments = parseInt(afficherMatch[1].replace(/\\s/g, ''), 10) || 0;
                }}

                const allDivs = document.querySelectorAll('div, button, [role="button"], span');
                for (const el of allDivs) {{
                    const text = (el.innerText || el.textContent || "").trim();
                    const lower = text.toLowerCase();
                    const numberMatch = text.match(/^([\\d.,]+\\s*[MK]?)$/i);
                    if (numberMatch) {{
                        const value = parseNumber(numberMatch[1]);
                        if (value > 0) {{
                            if (!likes || value > likes * 0.5) likes = value;
                            else if (!comments) comments = value;
                        }}
                    }}
                    if (lower.includes('like') && !lower.includes('unlike')) {{
                        const match = text.match(/([\\d.,]+[MK]?)/);
                        if (match) {{ const val = parseNumber(match[1]); if (val > 0) likes = val; }}
                    }}
                }}

                const ariaElements = document.querySelectorAll('[aria-label]');
                for (const el of ariaElements) {{
                    const label = (el.getAttribute('aria-label') || "").toLowerCase();
                    if (label.includes('like')) {{
                        const match = label.match(/([\\d.,]+[MK]?)/);
                        if (match) {{ const val = parseNumber(match[1]); if (val > 0 && val > likes) likes = val; }}
                    }}
                    if (label.includes('comment') && comments === 0) {{
                        const match = label.match(/([\\d.,]+[MK]?)/);
                        if (match) {{ const val = parseNumber(match[1]); if (val > 0) comments = val; }}
                    }}
                }}

                const videoEl = document.querySelector('video');
                const isCarousel = document.querySelector('[aria-label*="carousel"], [aria-label*="Carousel"]') ||
                                 document.querySelector('[role="tablist"]');
                if (videoEl) {{
                    mediaType = document.querySelector('svg[aria-label*="Reel"], svg[aria-label*="reel"]') ? "reel" : "video";
                }} else if (isCarousel) {{
                    mediaType = "carousel";
                }} else {{
                    mediaType = "image";
                }}

                return {{
                    timestamp: time ? time.getAttribute("datetime") : "",
                    caption: captionSpan ? captionSpan.innerText.trim() : (meta ? meta.getAttribute("content") : ""),
                    likes_count: likes,
                    comments_count: comments,
                    media_type: mediaType,
                    _debug_text: bodyText.substring(0, 500)
                }};
            }}""")

            dom_data_clean = {k: v for k, v in data.items() if k != "_debug_text"}
            logger.debug("Fallback DOM extraction", extra={"dom_data": dom_data_clean})
            return SocialPost(
                platform=PLATFORM,
                url=post_url,
                caption=data["caption"],
                timestamp=data["timestamp"],
                likes_count=data.get("likes_count", 0),
                comments_count=data.get("comments_count", 0),
                media_type=data.get("media_type", ""),
                user_followers=user_followers,
            )

        except PlaywrightTimeout:
            logger.warning(f"Timeout sur {post_url}")
            return None
        except Exception as e:
            logger.warning(f"Erreur sur {post_url}: {type(e).__name__}: {e}")
            return None
        finally:
            tab.remove_listener("response", on_response)
            await tab_pool.put(tab)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _dismiss_popup(self, page: Page):
        for attempt in range(4):
            clicked = False
            for label, selector in [("cookies", SELECTORS.COOKIE_BUTTON), ("login", SELECTORS.LOGIN_BUTTON)]:
                try:
                    await page.click(selector, timeout=TIMEOUT_POPUP_DISMISS)
                    logger.info(f"  → Fermeture du popup ({label}, round {attempt + 1})")
                    await asyncio.sleep(POPUP_DISMISS_WAIT)
                    clicked = True
                    break
                except PlaywrightTimeout:
                    pass
            if not clicked:
                break

    async def _wait_for_post_links(self, page: Page, timeout: int = TIMEOUT_PAGE_LOAD):
        from exceptions import SelectorsOutdatedError
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while asyncio.get_running_loop().time() < deadline:
            count = await page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]'))
                    .filter(a => /^\\/.+\\/(p|reel)\\/[A-Za-z0-9_-]+/.test(a.getAttribute('href')))
                    .length"""
            )
            if count > 0:
                logger.info(f"  {count} post(s) détectés dans le DOM")
                return
            await asyncio.sleep(SCROLL_POLL_INTERVAL)

        await page.screenshot(path="debug_screenshot.png", full_page=False)
        logger.error("Aucun post trouvé. Les sélecteurs sont probablement obsolètes.", extra={"screenshot": "debug_screenshot.png"})
        raise SelectorsOutdatedError("Aucun post trouvé. Instagram a probablement changé son HTML. Vérifiez les sélecteurs dans scrapers/instagram/config.py")

    async def _scroll_down(self, page: Page) -> bool:
        prev = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        deadline = asyncio.get_running_loop().time() + TIMEOUT_SCROLL / 1000
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(SCROLL_POLL_INTERVAL)
            if await page.evaluate("document.body.scrollHeight") > prev:
                return True
        return False
