import asyncio
import json
import logging
import random
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, BrowserContext, TimeoutError as PlaywrightTimeout

from bench import Bench
from exceptions import BrowserError, PageLoadError, SelectorsOutdatedError
from logging_setup import setup_logging
from scrapers.base import BaseScraper, SocialPost
from scrapers.tiktok.config import (
    BASE_URL,
    BLOCKED_RESOURCE_TYPES,
    WORKERS,
    MAX_RETRY_ATTEMPTS,
    GRID_RECOVERY_ATTEMPTS,
    BROWSER_PREFERENCE,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_POST_LOAD,
    TIMEOUT_PROFILE_READY,
    TIMEOUT_FIRST_POST_READY,
    TIMEOUT_POST_READY,
    TIMEOUT_GRID_RECOVERY,
    TIMEOUT_POPUP_DISMISS,
    TIMEOUT_SCROLL,
    POPUP_DISMISS_WAIT,
    SCROLL_POLL_INTERVAL,
    RESPONSE_HANDLER_WAIT,
    FIRST_POST_EXTRA_WAIT,
    VIDEO_RETRY_BACKOFF,
    STORAGE_STATE_PATH,
    USER_AGENT,
    VIEWPORT,
    LOCALE,
    TIMEZONE_ID,
    EXTRA_HTTP_HEADERS,
    HUMAN_DELAY_MIN,
    HUMAN_DELAY_MAX,
    HUMAN_LONG_DELAY_MIN,
    HUMAN_LONG_DELAY_MAX,
)
from scrapers.tiktok.validators import validate_tiktok_url, validate_post_count

logger = setup_logging(__name__)

PLATFORM = "tiktok"

# API TikTok interceptées
API_ITEM_LIST = "/api/post/item_list/"
API_USER_DETAIL = "/api/user/detail/"


def _parse_num(text: str) -> int:
    if not text:
        return 0
    text = text.strip().replace(" ", "").replace(",", ".")
    import re
    m = re.search(r"([\d.]+)\s*([MKmk])?", text)
    if not m:
        return 0
    num = float(m.group(1))
    unit = (m.group(2) or "").upper()
    if unit == "M":
        num *= 1_000_000
    elif unit == "K":
        num *= 1_000
    return int(num)


def _item_to_post(item: dict, user_followers: int, default_author: str = "") -> Optional[SocialPost]:
    try:
        video_id = item.get("id", "")
        author_info = item.get("author") or {}
        author = author_info.get("uniqueId", "") if isinstance(author_info, dict) else default_author
        if not author:
            author = default_author

        ts_raw = item.get("createTime", 0)
        timestamp = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc).isoformat() if ts_raw else ""

        url = f"{BASE_URL}/@{author}/video/{video_id}" if author and video_id else ""

        stats = item.get("stats") or item.get("statsV2") or {}

        def _st(key):
            v = stats.get(key, 0)
            return _parse_num(str(v)) if isinstance(v, str) else int(v or 0)

        return SocialPost(
            platform=PLATFORM,
            url=url,
            caption=item.get("desc", ""),
            timestamp=timestamp,
            likes_count=_st("diggCount"),
            comments_count=_st("commentCount"),
            views_count=_st("playCount"),
            media_type="photo" if item.get("imagePost") else "video",
            user_followers=user_followers,
        )
    except Exception as e:
        logger.debug(f"Erreur conversion item", extra={"error": str(e)})
        return None


class TikTokScraper(BaseScraper):
    def __init__(self, headless: bool = True, bench: Optional[Bench] = None):
        self.bench = bench or Bench()
        self.headless = headless
        self.storage_state_path = Path(STORAGE_STATE_PATH)

    def scrape(self, url: str, n: int) -> list[SocialPost]:
        url = validate_tiktok_url(url)
        n = validate_post_count(n)

        logger.info("Scraping TikTok démarré", extra={"url": url, "target_count": n})
        posts = asyncio.run(self._scrape_async(url, n))
        return posts

    async def _scrape_async(self, url: str, n: int) -> list[SocialPost]:
        # Extract username from URL for API calls
        username = url.rstrip("/").split("@")[-1]

        async with async_playwright() as pw:
            with self.bench.timer("driver_init"):
                browser = await self._launch_browser(pw)
                context_kwargs = {
                    "user_agent": USER_AGENT,
                    "viewport": VIEWPORT,
                    "locale": LOCALE,
                    "timezone_id": TIMEZONE_ID,
                    "extra_http_headers": EXTRA_HTTP_HEADERS,
                }
                if self.storage_state_path.exists():
                    context_kwargs["storage_state"] = str(self.storage_state_path)
                    logger.info(f"État de session réutilisé : {self.storage_state_path}")

                context = await browser.new_context(**context_kwargs)
                await context.route("**/*", self._route_handler)
                logger.info("✓ Navigateur initialisé", extra={"workers": WORKERS})

            page = await context.new_page()
            await self._simulate_human_warmup(page)

            # --- Intercept API responses ---
            api_items: list[dict] = []
            api_user_followers: list[int] = []

            async def on_response(response):
                resp_url = response.url
                if API_ITEM_LIST in resp_url:
                    try:
                        body = await response.json()
                        items = body.get("itemList") or []
                        logger.debug(f"API item_list interceptée : {len(items)} items", extra={"url": resp_url})
                        api_items.extend(items)
                    except Exception as e:
                        logger.debug(f"Erreur parsing item_list", extra={"error": str(e)})
                elif API_USER_DETAIL in resp_url:
                    try:
                        body = await response.json()
                        stats = (body.get("userInfo") or {}).get("stats") or {}
                        fc = stats.get("followerCount", 0)
                        if fc:
                            api_user_followers.append(fc)
                            logger.debug(f"API user_detail : {fc} followers")
                    except Exception as e:
                        logger.debug(f"Erreur parsing user_detail", extra={"error": str(e)})

            page.on("response", on_response)

            with self.bench.timer("page_load"):
                logger.info(f"Navigation vers {url}")
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_PAGE_LOAD)
                except PlaywrightTimeout as e:
                    raise PageLoadError(f"Timeout au chargement de {url}") from e

                await self._simulate_human_browse(page, long_pause=True)
                await self._dismiss_popup(page)
                await self._wait_for_profile_ready(page, api_items)

            # --- Strategy 1 : API interceptée ---
            with self.bench.timer("api_wait"):
                if not api_items:
                    logger.info("Pas encore d'items API, scroll pour déclencher les appels...")
                    await self._trigger_scroll(page)
                    await asyncio.sleep(RESPONSE_HANDLER_WAIT * 2)

            if api_items:
                user_followers = api_user_followers[0] if api_user_followers else 0
                logger.info(f"API interceptée : {len(api_items)} item(s), {user_followers} followers")

                posts: list[SocialPost] = []
                for item in api_items[:n]:
                    post = _item_to_post(item, user_followers, default_author=username)
                    if post:
                        posts.append(post)
                        logger.info(f"  [{len(posts)}/{n}] {post.url}")

                page.remove_listener("response", on_response)
                await self._persist_storage_state(context)
                await page.close()
                await context.close()
                await browser.close()
                logger.info(f"✓ Scraping terminé : {len(posts)} vidéos récupérées (via API)")
                return posts[:n]

            logger.info("API non interceptée, fallback JSON embarqué...")

            # --- Strategy 2 : JSON embarqué dans la page ---
            with self.bench.timer("extract_profile_json"):
                profile_data = await self._extract_profile_json(page)

            if profile_data:
                user_followers = profile_data.get("followers", 0)
                items = profile_data.get("items", [])
                logger.info(f"JSON embarqué : {len(items)} vidéo(s), {user_followers} followers")

                if items:
                    posts = []
                    for item in items[:n]:
                        post = _item_to_post(item, user_followers, default_author=username)
                        if post:
                            posts.append(post)
                            logger.info(f"  [{len(posts)}/{n}] {post.url}")

                    if len(posts) >= n:
                        page.remove_listener("response", on_response)
                        await self._persist_storage_state(context)
                        await page.close()
                        await context.close()
                        await browser.close()
                        logger.info(f"✓ Scraping terminé : {len(posts)} vidéos (via JSON embarqué)")
                        return posts[:n]

                    logger.info(f"JSON embarqué insuffisant ({len(posts)}/{n}), fallback DOM...")
                else:
                    user_followers = profile_data.get("followers", 0)
                    logger.info(f"JSON embarqué vide, fallback DOM... (followers={user_followers})")

            # --- Strategy 3 : DOM grille + scroll ---
            logger.info("Fallback : scraping DOM + scroll + vidéos individuelles")
            with self.bench.timer("wait_grid"):
                await self._recover_video_grid(page, api_items)
                try:
                    await self._wait_for_video_links(page)
                except SelectorsOutdatedError:
                    logger.info("Grille non chargée, reload...")
                    try:
                        await page.click(
                            "button:has-text('Refresh'), button:has-text('Actualiser'), "
                            "button:has-text('Retry'), button:has-text('Réessayer')",
                            timeout=3000,
                        )
                    except PlaywrightTimeout:
                        await page.reload(wait_until="domcontentloaded", timeout=TIMEOUT_PAGE_LOAD)
                    await self._dismiss_popup(page)
                    await asyncio.sleep(RESPONSE_HANDLER_WAIT * 2)
                    if api_items:
                        user_followers = api_user_followers[0] if api_user_followers else 0
                        posts = []
                        for item in api_items[:n]:
                            post = _item_to_post(item, user_followers, default_author=username)
                            if post:
                                posts.append(post)
                        if posts:
                            page.remove_listener("response", on_response)
                            await self._persist_storage_state(context)
                            await page.close()
                            await context.close()
                            await browser.close()
                            logger.info(f"✓ Scraping terminé après reload : {len(posts)} vidéos (via API)")
                            return posts[:n]
                    await self._recover_video_grid(page, api_items)
                    await self._wait_for_video_links(page)

            user_followers = (
                api_user_followers[0] if api_user_followers
                else (profile_data or {}).get("followers", 0)
                or await self._get_user_followers(page)
            )

            hrefs = await self._collect_n_hrefs(page, n)
            page.remove_listener("response", on_response)
            await page.close()

            logger.info(f"Scraping parallèle : {len(hrefs)} vidéos ({WORKERS} workers)")
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

            with self.bench.timer("scrape_all_videos"):
                while pending and attempt < MAX_RETRY_ATTEMPTS:
                    attempt += 1
                    if attempt > 1:
                        logger.info(f"  Retry #{attempt} — {len(pending)} vidéo(s) à relancer")
                    tasks = [
                        self._scrape_video(
                            href,
                            tab_pool,
                            user_followers,
                            is_first_video=(attempt == 1 and idx == 0),
                        )
                        for idx, href in enumerate(pending)
                    ]
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
                    logger.warning(f"  {len(pending)} vidéo(s) en échec après {MAX_RETRY_ATTEMPTS} tentatives")

            for tab in pooled_tabs:
                await tab.close()

            posts = [scraped[href] for href in hrefs if href in scraped]
            await self._persist_storage_state(context)
            await context.close()
            await browser.close()

        logger.info(f"✓ Scraping terminé : {len(posts)} vidéos récupérées")
        return posts

    async def _route_handler(self, route, request):
        if request.resource_type in BLOCKED_RESOURCE_TYPES:
            await route.abort()
        else:
            await route.continue_()

    async def _persist_storage_state(self, context: BrowserContext):
        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(self.storage_state_path))
        logger.debug(f"État de session sauvegardé : {self.storage_state_path}")

    async def _launch_browser(self, pw) -> Browser:
        launch_errors: list[str] = []
        for browser_name in BROWSER_PREFERENCE:
            browser_type = getattr(pw, browser_name, None)
            if browser_type is None:
                continue
            try:
                browser = await browser_type.launch(headless=self.headless)
                logger.info(f"Navigateur sélectionné : {browser_name}")
                return browser
            except Exception as exc:
                msg = f"{browser_name}: {type(exc).__name__}: {exc}"
                launch_errors.append(msg)
                logger.warning(f"Échec lancement navigateur {browser_name}", extra={"error": str(exc)})

        raise BrowserError(
            "Impossible de lancer un navigateur Playwright. "
            + " | ".join(launch_errors)
        )

    # ------------------------------------------------------------------
    # Trigger scroll pour déclencher les appels API
    # ------------------------------------------------------------------

    async def _trigger_scroll(self, page: Page):
        try:
            await page.mouse.wheel(0, random.randint(280, 520))
            await self._human_delay()
            await page.mouse.wheel(0, -random.randint(180, 360))
            await self._human_delay()
        except Exception:
            pass

    async def _human_delay(self, long_pause: bool = False):
        if long_pause:
            await asyncio.sleep(random.uniform(HUMAN_LONG_DELAY_MIN, HUMAN_LONG_DELAY_MAX))
            return
        await asyncio.sleep(random.uniform(HUMAN_DELAY_MIN, HUMAN_DELAY_MAX))

    async def _simulate_human_warmup(self, page: Page):
        try:
            x = random.randint(120, 420)
            y = random.randint(80, 280)
            await page.mouse.move(x, y, steps=random.randint(12, 24))
            await self._human_delay()
        except Exception:
            pass

    async def _simulate_human_browse(self, page: Page, long_pause: bool = False):
        try:
            await page.mouse.move(
                random.randint(150, 700),
                random.randint(120, 420),
                steps=random.randint(10, 22),
            )
            await self._human_delay(long_pause=long_pause)
            await page.mouse.wheel(0, random.randint(220, 480))
            await self._human_delay()
            await page.mouse.wheel(0, -random.randint(120, 260))
            await self._human_delay()
        except Exception:
            pass

    async def _wait_for_profile_ready(self, page: Page, api_items: list[dict]):
        deadline = asyncio.get_running_loop().time() + TIMEOUT_PROFILE_READY / 1000
        while asyncio.get_running_loop().time() < deadline:
            if api_items:
                logger.debug("Profil prêt via API interceptée")
                return

            try:
                ready = await page.evaluate(r"""() => {
                    const hasEmbeddedJson =
                        !!document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__') ||
                        !!document.querySelector('#SIGI_STATE');
                    const hasVideoLinks = Array.from(document.querySelectorAll('a[href]'))
                        .some(a => /\/@[\w.]+\/video\/\d+/.test(a.getAttribute('href') || ''));
                    const bodyText = document.body.innerText || '';
                    const hasProfileSignals =
                        hasVideoLinks ||
                        hasEmbeddedJson ||
                        /Followers|Abonnés|Following|Abonnements/i.test(bodyText);
                    return hasProfileSignals;
                }""")
                if ready:
                    logger.debug("Profil prêt via DOM/JSON embarqué")
                    return
            except Exception:
                pass

            await asyncio.sleep(SCROLL_POLL_INTERVAL)

        logger.info("Profil encore incomplet après attente initiale, scroll de réveil")
        await self._trigger_scroll(page)
        await asyncio.sleep(RESPONSE_HANDLER_WAIT * 2)

    async def _recover_video_grid(self, page: Page, api_items: list[dict]):
        for attempt in range(1, GRID_RECOVERY_ATTEMPTS + 1):
            if api_items:
                return
            if await self._has_video_links(page):
                return
            if not await self._is_grid_error_state(page):
                return

            logger.info(f"Grille TikTok en erreur, tentative de récupération #{attempt}")
            try:
                await page.click(
                    "button:has-text('Refresh'), button:has-text('Actualiser'), "
                    "button:has-text('Retry'), button:has-text('Réessayer')",
                    timeout=TIMEOUT_POPUP_DISMISS,
                )
            except PlaywrightTimeout:
                await page.reload(wait_until='domcontentloaded', timeout=TIMEOUT_PAGE_LOAD)

            await self._dismiss_popup(page)
            await self._wait_for_profile_ready(page, api_items)

            deadline = asyncio.get_running_loop().time() + TIMEOUT_GRID_RECOVERY / 1000
            while asyncio.get_running_loop().time() < deadline:
                if api_items or await self._has_video_links(page):
                    logger.info("Grille TikTok récupérée")
                    return
                await asyncio.sleep(SCROLL_POLL_INTERVAL)

            await asyncio.sleep(VIDEO_RETRY_BACKOFF * attempt)

    # ------------------------------------------------------------------
    # Extraction JSON embarqué (fallback strategy 2)
    # ------------------------------------------------------------------

    async def _extract_profile_json(self, page: Page) -> Optional[dict]:
        try:
            result = await page.evaluate(r"""() => {
                function tryParse(id) {
                    const el = document.querySelector(id);
                    if (!el) return null;
                    try { return JSON.parse(el.textContent); } catch(e) { return null; }
                }

                // __UNIVERSAL_DATA_FOR_REHYDRATION__
                const ud_json = tryParse('#__UNIVERSAL_DATA_FOR_REHYDRATION__');
                if (ud_json) {
                    const scope = ud_json['__DEFAULT_SCOPE__'] || {};
                    const ud = scope['webapp.user-detail'] || {};
                    const userInfo = ud.userInfo || {};
                    const stats = userInfo.stats || {};
                    const user = userInfo.user || {};
                    const itemList = userInfo.itemList || ud.itemList || [];
                    if (stats.followerCount > 0 || itemList.length > 0) {
                        return {
                            source: 'universal_data',
                            username: user.uniqueId || '',
                            followers: stats.followerCount || 0,
                            items: itemList,
                        };
                    }
                }

                // SIGI_STATE
                const sigi = tryParse('#SIGI_STATE');
                if (sigi) {
                    const userModule = sigi.UserModule || {};
                    const users = userModule.users || {};
                    const statsMap = userModule.stats || {};
                    const username = Object.keys(users)[0] || '';
                    const userStats = statsMap[username] || {};
                    const itemModule = sigi.ItemModule || {};
                    const items = Object.values(itemModule);
                    if (items.length > 0 || userStats.followerCount > 0) {
                        return {
                            source: 'sigi_state',
                            username: username,
                            followers: userStats.followerCount || 0,
                            items: items,
                        };
                    }
                }

                return null;
            }""")
            if result:
                logger.debug(f"Profile JSON via {result.get('source', '?')}")
            return result
        except Exception as e:
            logger.debug(f"Échec JSON profil", extra={"error": str(e)})
            return None

    # ------------------------------------------------------------------
    # Followers DOM fallback
    # ------------------------------------------------------------------

    async def _get_user_followers(self, page: Page) -> int:
        try:
            followers = await page.evaluate(r"""() => {
                function parseNum(text) {
                    if (!text) return 0;
                    let c = text.replace(/\s/g, '').replace(/,/g, '.');
                    const m = c.match(/([\d.]+)\s*([MKmk])?/);
                    if (!m) return 0;
                    let n = parseFloat(m[1]);
                    if (m[2]) {
                        const u = m[2].toUpperCase();
                        if (u === 'M') n *= 1000000;
                        else if (u === 'K') n *= 1000;
                    }
                    return Math.floor(n);
                }
                const el = document.querySelector('[data-e2e="followers-count"]');
                if (el) return parseNum(el.innerText || el.textContent || '');
                const allText = document.body.innerText || '';
                const m = allText.match(/([\d.,]+[MKmk]?)\s*(?:Followers|Abonnés)/i);
                if (m) return parseNum(m[1]);
                return 0;
            }""")
            logger.debug(f"Followers DOM : {followers}")
            return followers
        except Exception as e:
            logger.debug(f"Erreur followers DOM", extra={"error": str(e)})
            return 0

    # ------------------------------------------------------------------
    # Collecte hrefs DOM + scroll (strategy 3)
    # ------------------------------------------------------------------

    async def _collect_n_hrefs(self, page: Page, n: int) -> list[str]:
        seen: set[str] = set()
        hrefs: list[str] = []
        scroll_count = 0

        while len(hrefs) < n:
            with self.bench.timer(f"collect_links#{scroll_count + 1}"):
                new_links = await self._collect_video_links(page)

            new_count = 0
            for href in new_links:
                if href in seen:
                    continue
                seen.add(href)
                hrefs.append(href)
                logger.info(f"  [vidéo] {BASE_URL}{href}")
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

    async def _collect_video_links(self, page: Page) -> list[str]:
        try:
            return await page.evaluate(r"""() => {
                const pattern = /\/@[\w.]+\/video\/\d+/;
                const seen = new Set();
                return Array.from(document.querySelectorAll('a[href]'))
                    .map(a => {
                        let href = a.getAttribute('href') || '';
                        href = href.replace(/^https?:\/\/(?:www\.)?tiktok\.com/, '');
                        return href;
                    })
                    .filter(href => {
                        if (!pattern.test(href)) return false;
                        if (seen.has(href)) return false;
                        seen.add(href);
                        return true;
                    });
            }""")
        except Exception as e:
            logger.warning(f"Erreur collecte liens vidéo", extra={"error": str(e)})
            return []

    # ------------------------------------------------------------------
    # Scraping vidéo individuelle (strategy 3, parallèle)
    # ------------------------------------------------------------------

    async def _scrape_video(
        self,
        href: str,
        tab_pool: "asyncio.Queue[Page]",
        user_followers: int,
        is_first_video: bool = False,
    ) -> Optional[SocialPost]:
        video_url = href if href.startswith("http") else f"{BASE_URL}{href}"
        tab = await tab_pool.get()

        api_item: list[dict] = []

        async def on_resp(response):
            if "/api/item/detail/" in response.url or "/api/post/item_list/" in response.url:
                try:
                    body = await response.json()
                    item = body.get("itemInfo", {}).get("itemStruct") or {}
                    if not item:
                        items = body.get("itemList") or []
                        item = items[0] if items else {}
                    if item:
                        api_item.append(item)
                except Exception:
                    pass

        tab.on("response", on_resp)
        try:
            await tab.goto(video_url, wait_until="domcontentloaded", timeout=TIMEOUT_POST_LOAD)
            data = await self._wait_for_video_payload(tab, api_item, is_first_video=is_first_video)
            if data:
                if "item" in data:
                    return _item_to_post(data["item"], user_followers)

                logger.debug(f"Données via {data.get('source', '?')}")
                return SocialPost(
                    platform=PLATFORM,
                    url=video_url,
                    caption=data.get("caption", ""),
                    timestamp=data.get("timestamp", ""),
                    likes_count=data.get("likes_count", 0),
                    comments_count=data.get("comments_count", 0),
                    views_count=data.get("views_count", 0),
                    media_type=data.get("media_type", "video"),
                    user_followers=user_followers,
                )

            logger.debug(f"Aucune donnée exploitable pour {video_url}")
            return None

        except PlaywrightTimeout:
            logger.warning(f"Timeout sur {video_url}")
            return None
        except Exception as e:
            logger.warning(f"Erreur sur {video_url}: {type(e).__name__}: {e}")
            return None
        finally:
            tab.remove_listener("response", on_resp)
            await tab_pool.put(tab)

    async def _wait_for_video_payload(
        self,
        tab: Page,
        api_item: list[dict],
        is_first_video: bool = False,
    ) -> Optional[dict]:
        timeout_ms = TIMEOUT_FIRST_POST_READY if is_first_video else TIMEOUT_POST_READY
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        settled_first_wait = False

        while asyncio.get_running_loop().time() < deadline:
            if api_item:
                logger.debug("Vidéo prête via API interceptée")
                return {"item": api_item[0], "source": "api_intercept"}

            data = await tab.evaluate(r"""() => {
                function parseNum(text) {
                    if (!text) return 0;
                    let c = text.replace(/\s/g, '').replace(/,/g, '.');
                    const m = c.match(/([\d.]+)\s*([MKmk])?/);
                    if (!m) return 0;
                    let n = parseFloat(m[1]);
                    if (m[2]) {
                        const u = m[2].toUpperCase();
                        if (u === 'M') n *= 1000000;
                        else if (u === 'K') n *= 1000;
                    }
                    return Math.floor(n);
                }

                try {
                    const script = document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__');
                    if (script) {
                        const j = JSON.parse(script.textContent);
                        const scope = j['__DEFAULT_SCOPE__'] || {};
                        const detail = scope['webapp.video-detail'] || {};
                        const item = (detail.itemInfo || {}).itemStruct || detail.itemStruct;
                        if (item) {
                            const stats = item.stats || item.statsV2 || {};
                            const ts = item.createTime;
                            return {
                                caption: item.desc || '',
                                timestamp: ts ? new Date(parseInt(ts) * 1000).toISOString() : '',
                                likes_count: parseInt(stats.diggCount) || 0,
                                comments_count: parseInt(stats.commentCount) || 0,
                                views_count: parseInt(stats.playCount) || 0,
                                media_type: item.imagePost ? 'photo' : 'video',
                                source: 'embedded_json'
                            };
                        }
                    }
                } catch (e) {}

                try {
                    const sigiEl = document.querySelector('#SIGI_STATE');
                    if (sigiEl) {
                        const sigi = JSON.parse(sigiEl.textContent);
                        const items = sigi.ItemModule || {};
                        const firstKey = Object.keys(items)[0];
                        if (firstKey) {
                            const item = items[firstKey];
                            const stats = item.stats || {};
                            const ts = item.createTime;
                            return {
                                caption: item.desc || '',
                                timestamp: ts ? new Date(parseInt(ts) * 1000).toISOString() : '',
                                likes_count: parseInt(stats.diggCount) || 0,
                                comments_count: parseInt(stats.commentCount) || 0,
                                views_count: parseInt(stats.playCount) || 0,
                                media_type: item.imagePost ? 'photo' : 'video',
                                source: 'sigi_state'
                            };
                        }
                    }
                } catch (e) {}

                const descEl = document.querySelector('[data-e2e="browse-video-desc"], [data-e2e="video-desc"]');
                const likeEl = document.querySelector('[data-e2e="browse-like-count"], [data-e2e="like-count"]');
                const commentEl = document.querySelector('[data-e2e="browse-comment-count"], [data-e2e="comment-count"]');
                const viewEl = document.querySelector('[data-e2e="video-views"], [data-e2e="browse-video-views"]');
                const timeEl = document.querySelector('time[datetime]');
                const meta = document.querySelector('meta[property="og:description"]');

                return {
                    caption: (descEl && descEl.innerText) || (meta && meta.getAttribute('content')) || '',
                    timestamp: (timeEl && timeEl.getAttribute('datetime')) || '',
                    likes_count: likeEl ? parseNum(likeEl.innerText || '') : 0,
                    comments_count: commentEl ? parseNum(commentEl.innerText || '') : 0,
                    views_count: viewEl ? parseNum(viewEl.innerText || '') : 0,
                    media_type: 'video',
                    source: 'dom_fallback'
                };
            }""")

            if self._has_meaningful_video_data(data):
                if is_first_video and not settled_first_wait:
                    settled_first_wait = True
                    logger.debug("Première vidéo détectée, attente de stabilisation")
                    await asyncio.sleep(FIRST_POST_EXTRA_WAIT)
                    continue
                return data

            await asyncio.sleep(RESPONSE_HANDLER_WAIT)

        if is_first_video:
            logger.debug("Première vidéo toujours incomplète, backoff final")
            await asyncio.sleep(VIDEO_RETRY_BACKOFF)
            if api_item:
                return {"item": api_item[0], "source": "api_intercept_late"}

        return None

    @staticmethod
    def _has_meaningful_video_data(data: Optional[dict]) -> bool:
        if not data:
            return False
        return any(
            [
                bool(data.get("caption")),
                bool(data.get("timestamp")),
                (data.get("likes_count") or 0) > 0,
                (data.get("comments_count") or 0) > 0,
                (data.get("views_count") or 0) > 0,
            ]
        )

    # ------------------------------------------------------------------
    # Popups
    # ------------------------------------------------------------------

    async def _dismiss_popup(self, page: Page):
        selectors = [
            ("gdpr", "button:has-text('Got it'), button:has-text('Compris')"),
            ("cookies", (
                "button:has-text('Accept all'), button:has-text('Tout accepter'), "
                "button:has-text('Decline optional cookies'), button:has-text('Refuser')"
            )),
            ("login_close", (
                "[data-e2e='modal-close-inner-button'], "
                "button[aria-label='Close'], button[aria-label='Fermer']"
            )),
        ]
        for attempt in range(5):
            clicked = False
            for label, selector in selectors:
                try:
                    await page.click(selector, timeout=TIMEOUT_POPUP_DISMISS)
                    logger.info(f"  → Fermeture popup ({label}, round {attempt + 1})")
                    await asyncio.sleep(POPUP_DISMISS_WAIT)
                    await self._human_delay()
                    clicked = True
                    break
                except PlaywrightTimeout:
                    pass
            if not clicked:
                break

    async def _wait_for_video_links(self, page: Page):
        deadline = asyncio.get_running_loop().time() + TIMEOUT_PAGE_LOAD / 1000
        while asyncio.get_running_loop().time() < deadline:
            count = await self._count_video_links(page)
            if count > 0:
                logger.info(f"  {count} vidéo(s) détectées dans le DOM")
                return
            await asyncio.sleep(SCROLL_POLL_INTERVAL)

        logger.info("Capture debug TikTok en cours : debug_tiktok_screenshot.png")
        await page.screenshot(path="debug_tiktok_screenshot.png", full_page=False)
        logger.error("Aucune vidéo trouvée dans la grille")
        raise SelectorsOutdatedError(
            "Aucune vidéo trouvée. TikTok bloque le rendu ou a changé son HTML. "
            "Vérifiez debug_tiktok_screenshot.png"
        )

    async def _count_video_links(self, page: Page) -> int:
        return await page.evaluate(r"""() => {
            const pattern = /\/@[\w.]+\/video\/\d+/;
            return Array.from(document.querySelectorAll('a[href]'))
                .filter(a => pattern.test(a.getAttribute('href') || ''))
                .length;
        }""")

    async def _has_video_links(self, page: Page) -> bool:
        return (await self._count_video_links(page)) > 0

    async def _is_grid_error_state(self, page: Page) -> bool:
        try:
            return await page.evaluate(r"""() => {
                const text = document.body.innerText || '';
                return /Something went wrong|Sorry about that|Please try again later/i.test(text);
            }""")
        except Exception:
            return False

    async def _scroll_down(self, page: Page) -> bool:
        prev = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        deadline = asyncio.get_running_loop().time() + TIMEOUT_SCROLL / 1000
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(SCROLL_POLL_INTERVAL)
            if await page.evaluate("document.body.scrollHeight") > prev:
                return True
        return False
