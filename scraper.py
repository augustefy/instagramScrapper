import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup, Tag
from playwright.async_api import async_playwright, Page, Browser, BrowserContext, TimeoutError as PlaywrightTimeout

from bench import Bench

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

BASE_URL = "https://www.instagram.com"
BLOCKED_TYPES = {"image", "media", "font"}
WORKERS = 10  # Tabs en parallèle pour le scraping des posts (+ 1 tab pour le chargement initial)


@dataclass
class PostData:
    url: str
    caption: str = ""
    timestamp: str = ""


class InstagramScraper:
    def __init__(self, headless: bool = True, bench: Optional[Bench] = None):
        self.bench = bench or Bench()
        self.headless = headless
        self._pw = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    # ------------------------------------------------------------------
    # Public entry point (sync wrapper)
    # ------------------------------------------------------------------

    def scrape(self, url: str, n: int) -> list[PostData]:
        return asyncio.run(self._scrape_async(url, n))

    def close(self):
        pass  # cleanup handled inside _scrape_async

    # ------------------------------------------------------------------
    # Async core
    # ------------------------------------------------------------------

    async def _scrape_async(self, url: str, n: int) -> list[PostData]:
        async with async_playwright() as pw:
            with self.bench.timer("driver_init"):
                browser = await pw.chromium.launch(headless=self.headless)
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 900},
                )
                logger.info(f"✓ Chromium initialisé ({WORKERS} workers parallèles, images/médias/fonts bloqués)")

            page = await context.new_page()
            await page.route("**/*", self._route_handler)

            with self.bench.timer("page_load"):
                logger.info(f"Navigation vers {url}")
                await page.goto(url, wait_until="domcontentloaded")
                logger.info("Attente des posts...")
                await page.wait_for_selector("a[href*='/p/']", timeout=15000)
                await self._dismiss_popup(page)

            hrefs = await self._collect_n_hrefs(page, n)
            await page.close()

            logger.info(f"Début du scraping parallèle : {len(hrefs)} posts ({WORKERS} workers)")

            posts: list[PostData] = []
            with self.bench.timer("scrape_all_posts"):
                semaphore = asyncio.Semaphore(WORKERS)
                tasks = [
                    self._scrape_post(context, href, semaphore)
                    for href in hrefs
                ]
                results = await asyncio.gather(*tasks)
                for post in results:
                    if post:
                        posts.append(post)
                        logger.info(f"  [{len(posts)}/{len(hrefs)}] {post.url}")

            await context.close()
            await browser.close()

        # Remet dans l'ordre d'apparition sur la page
        href_order = {href: i for i, href in enumerate(hrefs)}
        posts.sort(key=lambda p: href_order.get(p.url.replace(BASE_URL, ""), 999))

        logger.info(f"✓ Scraping terminé : {len(posts)} posts récupérés")
        return posts

    # ------------------------------------------------------------------
    # Route handler
    # ------------------------------------------------------------------

    async def _route_handler(self, route, request):
        if request.resource_type in BLOCKED_TYPES:
            await route.abort()
        else:
            await route.continue_()

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
        soup = BeautifulSoup(await page.content(), "lxml")
        results: list[tuple[str, bool]] = []
        for link in soup.select("a[href*='/p/']"):
            href = link.get("href", "")
            if href:
                results.append((href, self._is_pinned(link)))
        return results

    def _is_pinned(self, link_tag: Tag) -> bool:
        container = link_tag
        for _ in range(5):
            parent = container.parent
            if parent is None:
                break
            container = parent
        for svg in container.find_all("svg"):
            if "pin" in svg.get("aria-label", "").lower():
                return True
        return False

    # ------------------------------------------------------------------
    # Scraping d'un post (appelé en parallèle)
    # ------------------------------------------------------------------

    async def _scrape_post(self, context: BrowserContext, href: str, semaphore: asyncio.Semaphore) -> Optional[PostData]:
        post_url = f"{BASE_URL}{href}"
        async with semaphore:
            tab = None
            try:
                tab = await context.new_page()
                await tab.route("**/*", self._route_handler)
                await tab.goto(post_url, wait_until="domcontentloaded")
                await tab.wait_for_selector("time[datetime]", timeout=10000)

                for selector in ["[aria-label='Fermer']", "[aria-label='Close']"]:
                    try:
                        await tab.click(selector, timeout=1500)
                        break
                    except PlaywrightTimeout:
                        pass

                soup = BeautifulSoup(await tab.content(), "lxml")

                caption = ""
                caption_tag = soup.find("span", class_=lambda c: c and "x126k92a" in c)
                if caption_tag:
                    caption = caption_tag.get_text(strip=True)
                if not caption:
                    meta = soup.find("meta", {"property": "og:description"})
                    if meta:
                        caption = meta.get("content", "")

                timestamp = ""
                time_tag = soup.find("time", {"datetime": True, "class": "xdwrcjd"}) \
                           or soup.find("time", {"datetime": True})
                if time_tag:
                    timestamp = time_tag.get("datetime", "")

                return PostData(url=post_url, caption=caption, timestamp=timestamp)

            except Exception as e:
                logger.error(f"Erreur sur {post_url} : {e}")
                return None
            finally:
                if tab:
                    await tab.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _dismiss_popup(self, page: Page):
        for label, selector in [
            ("cookies", "button:has-text('Allow'), button:has-text('Autoriser'), button:has-text('Accept')"),
            ("login prompt", "button:has-text('Not Now'), button:has-text('Plus tard')"),
        ]:
            try:
                await page.click(selector, timeout=3000)
                logger.info(f"  → Fermeture du popup ({label})")
            except PlaywrightTimeout:
                pass

    async def _scroll_down(self, page: Page) -> bool:
        prev = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        try:
            await page.wait_for_function(
                f"document.body.scrollHeight > {prev}", timeout=4000
            )
        except PlaywrightTimeout:
            pass
        return await page.evaluate("document.body.scrollHeight") > prev
