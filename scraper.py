import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup
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
                await self._dismiss_popup(page)
                # Attendre les vrais posts (pattern /username/p/CODE/ ou /username/reel/CODE/)
                # wait_for_selector("a[href*='/p/']") matche aussi /privacy — on utilise evaluate()
                await self._wait_for_post_links(page, timeout=15000)

            hrefs = await self._collect_n_hrefs(page, n)
            await page.close()

            logger.info(f"Début du scraping parallèle : {len(hrefs)} posts ({WORKERS} workers)")

            posts: list[PostData] = []
            scraped: dict[str, PostData] = {}  # href → PostData
            pending = list(hrefs)
            attempt = 0
            MAX_ATTEMPTS = 3

            with self.bench.timer("scrape_all_posts"):
                while pending and attempt < MAX_ATTEMPTS:
                    attempt += 1
                    if attempt > 1:
                        logger.info(f"  Retry #{attempt} — {len(pending)} post(s) à relancer")

                    semaphore = asyncio.Semaphore(WORKERS)
                    tasks = [self._scrape_post(context, href, semaphore) for href in pending]
                    results = await asyncio.gather(*tasks)

                    failed = []
                    for href, post in zip(pending, results):
                        if post:
                            scraped[href] = post
                            logger.info(f"  [{len(scraped)}/{len(hrefs)}] {post.url}")
                        else:
                            failed.append(href)

                    pending = failed

                if pending:
                    logger.warning(f"  {len(pending)} post(s) en échec après {MAX_ATTEMPTS} tentatives")

            # Remet dans l'ordre d'apparition sur la page
            posts = [scraped[href] for href in hrefs if href in scraped]

            await context.close()
            await browser.close()

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
        raw = await page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]'))
                .filter(a => /^\\/.+\\/(p|reel)\\/[A-Za-z0-9_-]+/.test(a.getAttribute('href')))
                .map(a => {
                    const href = a.getAttribute('href');
                    // Cherche un SVG "pin" uniquement dans le conteneur direct du lien (pas la grille entière)
                    const cell = a.closest('li, article, div[class]') || a.parentElement;
                    const pinned = !!(cell && Array.from(cell.children).some(
                        child => child.querySelector && child.querySelector('svg[aria-label*="pin"], svg[aria-label*="Pin"]')
                    ));
                    return [href, pinned];
                })"""
        )

        return [(href, pinned) for href, pinned in raw]

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
        cookie_selector = (
            "button:has-text('Allow all cookies'), "
            "button:has-text('Tout accepter'), "
            "button:has-text('Allow'), "
            "button:has-text('Autoriser'), "
            "button:has-text('Accept'), "
            "button:has-text('Decline optional cookies'), "
            "button:has-text('Refuser les cookies optionnels')"
        )
        login_selector = "button:has-text('Not Now'), button:has-text('Plus tard')"

        # Boucle pour gérer plusieurs popups successifs (Instagram en affiche 2)
        for attempt in range(4):
            clicked = False
            for label, selector in [("cookies", cookie_selector), ("login", login_selector)]:
                try:
                    await page.click(selector, timeout=2000)
                    logger.info(f"  → Fermeture du popup ({label}, round {attempt + 1})")
                    await asyncio.sleep(0.8)
                    clicked = True
                    break
                except PlaywrightTimeout:
                    pass
            if not clicked:
                break

    async def _wait_for_post_links(self, page: Page, timeout: int = 15000):
        """Attend que de vrais liens de posts soient présents dans le DOM.
        Utilise un polling evaluate() pour éviter les faux matchs CSS sur /privacy."""
        deadline = asyncio.get_event_loop().time() + timeout / 1000
        while asyncio.get_event_loop().time() < deadline:
            count = await page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]'))
                    .filter(a => /^\\/.+\\/(p|reel)\\/[A-Za-z0-9_-]+/.test(a.getAttribute('href')))
                    .length"""
            )
            if count > 0:
                logger.info(f"  {count} post(s) détectés dans le DOM")
                return
            await asyncio.sleep(0.3)
        logger.warning("Timeout : aucun post trouvé après attente")
        await page.screenshot(path="debug_screenshot.png", full_page=False)
        logger.warning("Screenshot → debug_screenshot.png")

    async def _scroll_down(self, page: Page) -> bool:
        prev = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        # wait_for_function avec une string viole la CSP d'Instagram (unsafe-eval bloqué)
        # → polling manuel via evaluate()
        deadline = asyncio.get_event_loop().time() + 4.0
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.2)
            if await page.evaluate("document.body.scrollHeight") > prev:
                return True
        return False
