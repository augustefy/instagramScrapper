import asyncio
import json
import logging
import math
import random
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, BrowserContext, TimeoutError as PlaywrightTimeout

from bench import Bench
from exceptions import BrowserError, PageLoadError, SelectorsOutdatedError
from app.core.log import setup_logging
from scrapers.base import BaseScraper, SocialPost
from scrapers.tiktok.config import (
    BASE_URL,
    ABORT_RESOURCE_TYPES,
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
    USER_AGENT_POOL,
    VIEWPORT,
    VIEWPORT_POOL,
    LOCALE_POOL,
    REFERRER_POOL,
    EXTRA_HTTP_HEADERS,
    HUMAN_DELAY_MIN,
    HUMAN_DELAY_MAX,
    HUMAN_LONG_DELAY_MIN,
    HUMAN_LONG_DELAY_MAX,
    READING_CHARS_PER_SECOND,
    READING_PAUSE_MIN,
    READING_PAUSE_MAX,
    RATE_LIMIT_BACKOFF_BASE,
    RATE_LIMIT_BACKOFF_FACTOR,
    RATE_LIMIT_BACKOFF_MAX,
    RATE_LIMIT_JITTER,
)
from scrapers.tiktok.validators import validate_tiktok_url, validate_post_count

logger = setup_logging(__name__)

PLATFORM = "tiktok"

API_ITEM_LIST = "/api/post/item_list/"
API_USER_DETAIL = "/api/user/detail/"

# ── Stealth init script — only what's necessary, nothing that backfires. ──
_STEALTH_INIT_SCRIPT = """
(function() {
    // 1. Remove webdriver flag
    try { Object.defineProperty(navigator, 'webdriver', { get: () => undefined, configurable: true }); } catch(e) {}

    // 2. Full Chrome runtime
    if (!window.chrome) {
        window.chrome = {
            app: { isInstalled: false },
            csi: function() {},
            loadTimes: function() { return {}; },
            runtime: { connect: function(){}, sendMessage: function(){}, id: void 0 },
        };
    }

    // 3. Remove Playwright-specific leaks
    try { delete window.__playwright; } catch(e) {}
    try { delete window.__pwInitScripts; } catch(e) {}
    try { delete window.playwright; } catch(e) {}

    // 4. document.hasFocus() — always false in headless, TikTok checks this
    try { Object.defineProperty(document, 'hasFocus', { value: function() { return true; }, configurable: true }); } catch(e) {}

    // 5. Page visibility — hidden tab is a bot signal
    try { Object.defineProperty(document, 'visibilityState', { get: () => 'visible', configurable: true }); } catch(e) {}
    try { Object.defineProperty(document, 'hidden', { get: () => false, configurable: true }); } catch(e) {}

    // 6. outerWidth/outerHeight differ from inner on real browsers
    try {
        if (!window.outerWidth || window.outerWidth === window.innerWidth) {
            Object.defineProperty(window, 'outerWidth',  { get: () => window.innerWidth  + 16, configurable: true });
            Object.defineProperty(window, 'outerHeight', { get: () => window.innerHeight + 88, configurable: true });
        }
    } catch(e) {}

    // 7. Notification — headless reports "denied" which flags automation
    try {
        if (typeof Notification !== 'undefined') {
            Object.defineProperty(Notification, 'permission', { get: () => 'default', configurable: true });
        }
    } catch(e) {}
})();
"""


# ── Defensive counter parsing for TikTok display values. ──
def _parse_num(text: str) -> int:
    if not text:
        return 0
    text = text.strip().replace(" ", "").replace(",", ".")
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


# ── Map raw TikTok item to SocialPost. ──
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


# ── Gaussian-jittered random delay helper. ──
def _gaussian_delay(low: float, high: float) -> float:
    """Return a delay drawn from a gaussian centered in [low, high] with std ≈ range/6."""
    mid = (low + high) / 2
    std = (high - low) / 5
    return max(low, min(high, random.gauss(mid, std)))


class TikTokScraper(BaseScraper):
    def __init__(self, headless: bool = True, bench: Optional[Bench] = None):
        self.bench = bench or Bench()
        self.headless = headless
        self.storage_state_path = Path(STORAGE_STATE_PATH)
        self._rate_limit_strikes = 0

    def scrape(self, url: str, n: int) -> list[SocialPost]:
        url = validate_tiktok_url(url)
        n = validate_post_count(n)
        logger.info("Scraping TikTok démarré", extra={"url": url, "target_count": n})
        posts = asyncio.run(self._scrape_async(url, n))
        return posts

    def health_check(self) -> dict:
        return asyncio.run(self._health_check_async())

    def setup_session(self, wait_seconds: int = 45) -> Path:
        """
        Lance Chrome en mode VISIBLE, navigue sur TikTok, attend que l'utilisateur
        valide manuellement les popups/challenges, puis sauvegarde la session.
        Retourne le chemin du fichier de session créé.
        """
        return asyncio.run(self._setup_session_async(wait_seconds))

    async def _setup_session_async(self, wait_seconds: int) -> Path:
        profile_dir = self.storage_state_path.parent / "chrome_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)

        # Remove stale lock files left by a previous crashed Chrome instance
        for lock_file in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            lock_path = profile_dir / lock_file
            if lock_path.exists() or lock_path.is_symlink():
                lock_path.unlink()
                logger.debug(f"Suppression du verrou Chrome : {lock_path}")

        print("\n" + "=" * 60)
        print("SETUP SESSION TIKTOK")
        print("=" * 60)
        print(f"Chrome va s'ouvrir avec un profil dédié : {profile_dir}")
        print("")
        print("Dans la fenêtre Chrome qui s'ouvre :")
        print("  1. Résoudre le CAPTCHA si il apparaît")
        print("  2. Fermer les popups cookies/GDPR")
        print("  3. Vous connecter à TikTok (recommandé)")
        print("  4. Vérifier que la grille vidéo est bien visible")
        print("")
        print(f"Vous avez {wait_seconds} secondes. La session sera sauvegardée ensuite.")
        print("=" * 60 + "\n")

        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                channel="chrome",
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-service-autorun",
                ],
                viewport={"width": 1280, "height": 900},
                user_agent=USER_AGENT,
            )
            context.on("page", lambda p: None)

            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=TIMEOUT_PAGE_LOAD)

            print(f"Attente de {wait_seconds}s — interagissez maintenant avec le navigateur...")
            for remaining in range(wait_seconds, 0, -10):
                await asyncio.sleep(10)
                print(f"  → {remaining}s restantes...")

            self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
            await context.storage_state(path=str(self.storage_state_path))
            print(f"\n✓ Session sauvegardée : {self.storage_state_path}")
            print("Vous pouvez maintenant lancer le scraper normalement.\n")

            await context.close()

        return self.storage_state_path

    # ── Session fingerprint selection ──────────────────────────────────

    @staticmethod
    def _pick_fingerprint() -> dict:
        """Pick a coherent random browser fingerprint for this session."""
        ua = random.choice(USER_AGENT_POOL)
        viewport = random.choice(VIEWPORT_POOL)
        locale, timezone_id = random.choice(LOCALE_POOL)

        # Build Accept-Language header consistent with locale
        lang_code = locale.split("-")[0]
        region_code = locale.split("-")[1].lower() if "-" in locale else ""
        accept_language = f"{locale},{lang_code};q=0.9"
        if region_code and region_code != lang_code:
            accept_language += f",{lang_code}-{region_code};q=0.8"

        headers = {**EXTRA_HTTP_HEADERS, "Accept-Language": accept_language}

        # sec-ch-ua headers for Chrome UAs
        if "Chrome/" in ua:
            chrome_ver = re.search(r"Chrome/(\d+)", ua)
            ver = chrome_ver.group(1) if chrome_ver else "124"
            headers["sec-ch-ua"] = f'"Chromium";v="{ver}", "Google Chrome";v="{ver}", "Not-A.Brand";v="99"'
            headers["sec-ch-ua-mobile"] = "?0"
            headers["sec-ch-ua-platform"] = '"macOS"' if "Macintosh" in ua else '"Windows"'

        return {
            "user_agent": ua,
            "viewport": viewport,
            "locale": locale,
            "timezone_id": timezone_id,
            "extra_http_headers": headers,
        }

    # ── Route handler ──────────────────────────────────────────────────

    async def _route_handler(self, route, request):
        resource_type = request.resource_type

        if resource_type in ABORT_RESOURCE_TYPES:
            await route.abort()
            return

        # Occasionally let through non-essential resources (images, stylesheets)
        # to mimic real browser traffic ratios.
        if resource_type in ("image", "stylesheet") and random.random() < 0.15:
            await route.abort()
            return

        await route.continue_()

    # ── Delay helpers ──────────────────────────────────────────────────

    async def _human_delay(self, long_pause: bool = False):
        if long_pause:
            delay = _gaussian_delay(HUMAN_LONG_DELAY_MIN, HUMAN_LONG_DELAY_MAX)
        else:
            delay = _gaussian_delay(HUMAN_DELAY_MIN, HUMAN_DELAY_MAX)
        await asyncio.sleep(delay)

    async def _reading_pause(self, text: str = ""):
        """Simulate reading time proportional to content length."""
        chars = len(text) if text else random.randint(80, 300)
        raw = chars / READING_CHARS_PER_SECOND
        pause = max(READING_PAUSE_MIN, min(READING_PAUSE_MAX, raw))
        pause = _gaussian_delay(pause * 0.7, pause * 1.3)
        await asyncio.sleep(pause)

    async def _rate_limit_backoff(self):
        """Exponential backoff with jitter after a 429 response."""
        self._rate_limit_strikes += 1
        base = min(
            RATE_LIMIT_BACKOFF_BASE * (RATE_LIMIT_BACKOFF_FACTOR ** (self._rate_limit_strikes - 1)),
            RATE_LIMIT_BACKOFF_MAX,
        )
        jitter = random.uniform(-RATE_LIMIT_JITTER, RATE_LIMIT_JITTER)
        delay = max(RATE_LIMIT_BACKOFF_BASE, base + jitter)
        logger.warning(f"Rate-limit détecté (strike {self._rate_limit_strikes}), backoff {delay:.1f}s")
        await asyncio.sleep(delay)

    # ── Mouse helpers ──────────────────────────────────────────────────

    @staticmethod
    def _bezier_points(
        p0: tuple, p1: tuple, p2: tuple, p3: tuple, steps: int
    ) -> list[tuple]:
        """Cubic Bézier interpolation for natural cursor trajectories."""
        points = []
        for i in range(steps + 1):
            t = i / steps
            u = 1 - t
            x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
            y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
            points.append((int(x), int(y)))
        return points

    async def _human_mouse_move(self, page: Page, x: int, y: int, *, current: tuple = (0, 0)):
        """Move mouse along a Bézier curve with small positional noise."""
        vw = page.viewport_size or {"width": 1280, "height": 900}
        cx, cy = current

        # Two random control points offset from the straight line
        cp1 = (
            cx + (x - cx) * 0.25 + random.randint(-60, 60),
            cy + (y - cy) * 0.25 + random.randint(-60, 60),
        )
        cp2 = (
            cx + (x - cx) * 0.75 + random.randint(-60, 60),
            cy + (y - cy) * 0.75 + random.randint(-60, 60),
        )
        steps = random.randint(18, 35)
        points = self._bezier_points((cx, cy), cp1, cp2, (x, y), steps)

        for px, py in points:
            await page.mouse.move(px, py)

        return (x, y)

    async def _human_hover_random(self, page: Page, current: tuple = (0, 0)) -> tuple:
        """Move mouse to a random spot on the page (idle hover)."""
        vw = page.viewport_size or {"width": 1280, "height": 900}
        tx = random.randint(100, vw["width"] - 100)
        ty = random.randint(80, vw["height"] - 80)
        try:
            current = await self._human_mouse_move(page, tx, ty, current=current)
        except Exception:
            pass
        return current

    # ── Human warmup & browse simulation ──────────────────────────────

    async def _simulate_human_warmup(self, page: Page):
        """Gentle initial mouse movement before the target page loads."""
        try:
            current = (0, 0)
            for _ in range(random.randint(1, 3)):
                current = await self._human_hover_random(page, current)
                await self._human_delay()
        except Exception:
            pass

    async def _pre_navigate_warmup(self, page: Page):
        """
        Visit a neutral site (search engine / news) before TikTok.
        Simulates organic traffic arriving from search — reduces bot score.
        """
        warmup_sites = [
            "https://www.google.com/search?q=tiktok+viral+videos",
            "https://www.bing.com/search?q=tiktok+trends",
            "https://duckduckgo.com/?q=tiktok+funny+videos",
        ]
        site = random.choice(warmup_sites)
        try:
            logger.debug(f"Pre-navigation warmup : {site}")
            await page.goto(site, wait_until="domcontentloaded", timeout=12000)
            await self._simulate_human_browse(page, long_pause=False)
            await self._human_delay(long_pause=True)
            # Simulate reading a result (hover over the page)
            current = (0, 0)
            for _ in range(random.randint(2, 4)):
                current = await self._human_hover_random(page, current)
                await self._human_delay()
        except Exception as e:
            logger.debug(f"Warmup ignoré : {e}")

    async def _simulate_human_browse(self, page: Page, long_pause: bool = False):
        """Realistic browse pattern: move, scroll down, partial scroll back, hover."""
        try:
            vw = page.viewport_size or {"width": 1280, "height": 900}
            current = (vw["width"] // 2, vw["height"] // 2)

            # Move to a random area then pause (simulates reading)
            current = await self._human_hover_random(page, current)
            await self._human_delay(long_pause=long_pause)

            # Variable scroll down (not always to the bottom)
            scroll_amount = random.randint(180, min(600, vw["height"]))
            await page.mouse.wheel(0, scroll_amount)
            await self._human_delay()

            # Sometimes hover over content mid-scroll
            if random.random() < 0.5:
                current = await self._human_hover_random(page, current)
                await self._human_delay()

            # Partial scroll back up (humans rarely stay at the bottom)
            scroll_back = random.randint(50, scroll_amount // 2)
            await page.mouse.wheel(0, -scroll_back)
            await self._human_delay()

        except Exception:
            pass

    # ── Health check ───────────────────────────────────────────────────

    async def _health_check_async(self) -> dict:
        async with async_playwright() as pw:
            browser = await self._launch_browser(pw)
            context = None
            page = None
            try:
                fp = self._pick_fingerprint()
                if self.storage_state_path.exists():
                    fp["storage_state"] = str(self.storage_state_path)
                context = await browser.new_context(**fp)
                page = await context.new_page()
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
                    "storage_state_present": self.storage_state_path.exists(),
                }
            finally:
                if page is not None:
                    await page.close()
                if context is not None:
                    await context.close()
                if browser is not None:
                    await browser.close()

    # ── Main scrape pipeline ───────────────────────────────────────────

    async def _scrape_async(self, url: str, n: int) -> list[SocialPost]:
        username = url.rstrip("/").split("@")[-1]

        profile_dir = self.storage_state_path.parent / "chrome_profile"

        if profile_dir.exists():
            for lock_file in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                lock_path = profile_dir / lock_file
                if lock_path.exists() or lock_path.is_symlink():
                    lock_path.unlink()
                    logger.debug(f"Suppression du verrou Chrome : {lock_path}")

        async with async_playwright() as pw:
            with self.bench.timer("driver_init"):
                # Si un profil persistant existe (créé par --setup-tiktok-session),
                # on l'utilise directement — c'est un vrai profil Chrome avec des vrais cookies.
                if profile_dir.exists():
                    fp = self._pick_fingerprint()
                    # Always launch visible when using the persistent profile.
                    # TikTok reliably detects headless Chrome (even --headless=new)
                    # and serves a CAPTCHA. A real visible window bypasses this entirely.
                    context = await pw.chromium.launch_persistent_context(
                        user_data_dir=str(profile_dir),
                        channel="chrome",
                        headless=False,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--no-first-run",
                            "--no-service-autorun",
                            "--disable-infobars",
                            "--disable-default-apps",
                            "--no-default-browser-check",
                        ],
                        viewport=fp["viewport"],
                        user_agent=fp["user_agent"],
                    )
                    browser = None
                    using_persistent = True
                    logger.info(f"✓ Profil persistant Chrome chargé (visible) : {profile_dir}")
                else:
                    browser = await self._launch_browser(pw)
                    fp = self._pick_fingerprint()
                    if self.storage_state_path.exists():
                        fp["storage_state"] = str(self.storage_state_path)
                        logger.info(f"État de session réutilisé : {self.storage_state_path}")
                    context = await browser.new_context(**fp)
                    using_persistent = False

                # With the persistent profile (visible Chrome) we skip init script and
                # route interception — they're detectable via CDP and cause CAPTCHAs.
                # The response event listener below is enough for API interception.
                if not using_persistent:
                    await context.add_init_script(_STEALTH_INIT_SCRIPT)
                    await context.route("**/*", self._route_handler)

                logger.info(
                    "✓ Navigateur initialisé",
                    extra={
                        "workers": WORKERS,
                        "ua": fp["user_agent"][:60],
                        "viewport": fp["viewport"],
                        "locale": fp["locale"],
                    },
                )

            page = await context.new_page()
            await self._simulate_human_warmup(page)

            # 2) Intercept API responses before DOM fallback.
            api_items: list[dict] = []
            api_user_followers: list[int] = []

            async def on_response(response):
                # Handle rate limiting globally
                if response.status == 429:
                    await self._rate_limit_backoff()
                    return

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

            # 3) Navigate with a realistic referrer (some % of sessions come from search)
            referrer = random.choice(REFERRER_POOL)

            with self.bench.timer("page_load"):
                logger.info(f"Navigation vers {url} (referrer={referrer or 'direct'})")
                try:
                    nav_kwargs: dict = {"wait_until": "domcontentloaded", "timeout": TIMEOUT_PAGE_LOAD}
                    if referrer:
                        nav_kwargs["referer"] = referrer
                    await page.goto(url, **nav_kwargs)
                except PlaywrightTimeout as e:
                    raise PageLoadError(f"Timeout au chargement de {url}") from e

                await self._simulate_human_browse(page, long_pause=True)
                await self._dismiss_popup(page)
                # Idle mouse movement while profile loads — defeats "no mouse = bot" checks
                _mouse_pos = (0, 0)
                for _ in range(random.randint(2, 5)):
                    _mouse_pos = await self._human_hover_random(page, _mouse_pos)
                    await self._human_delay()
                await self._wait_for_profile_ready(page, api_items)

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
                if browser is not None:
                    await browser.close()
                logger.info(f"✓ Scraping terminé : {len(posts)} vidéos récupérées (via API)")
                return posts[:n]

            logger.info("API non interceptée, fallback JSON embarqué...")

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
                        if browser is not None:
                            await browser.close()
                        logger.info(f"✓ Scraping terminé : {len(posts)} vidéos (via JSON embarqué)")
                        return posts[:n]

                    logger.info(f"JSON embarqué insuffisant ({len(posts)}/{n}), fallback DOM...")
                else:
                    user_followers = profile_data.get("followers", 0)
                    logger.info(f"JSON embarqué vide, fallback DOM... (followers={user_followers})")

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
                            if browser is not None:
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
            if browser is not None:
                await browser.close()

        logger.info(f"✓ Scraping terminé : {len(posts)} vidéos récupérées")
        return posts

    # ── Browser launch ─────────────────────────────────────────────────

    async def _launch_browser(self, pw) -> Browser:
        """
        Try browsers in priority order:
          1. System Chrome   (channel="chrome")    — most realistic, hardest to detect
          2. System Edge     (channel="msedge")    — fallback if Chrome not installed
          3. Playwright Firefox                    — better stealth than bundled Chromium
          4. Playwright Chromium + stealth args    — last resort
        """
        _stealth_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-service-autorun",
            "--disable-infobars",
            "--disable-extensions-except=",
            "--disable-default-apps",
            "--no-default-browser-check",
            "--disable-popup-blocking",
        ]
        candidates = [
            ("chromium", {"channel": "chrome",  "headless": self.headless, "args": _stealth_args}),
            ("chromium", {"channel": "msedge",  "headless": self.headless, "args": _stealth_args}),
            ("firefox",  {"headless": self.headless}),
            ("chromium", {"headless": self.headless, "args": _stealth_args}),
        ]

        launch_errors: list[str] = []
        for browser_name, kwargs in candidates:
            browser_type = getattr(pw, browser_name, None)
            if browser_type is None:
                continue
            try:
                browser = await browser_type.launch(**kwargs)
                label = kwargs.get("channel", browser_name)
                logger.info(f"✓ Navigateur : {label}")
                return browser
            except Exception as exc:
                label = kwargs.get("channel", browser_name)
                msg = f"{label}: {type(exc).__name__}: {exc}"
                launch_errors.append(msg)
                logger.debug(f"Navigateur {label} indisponible", extra={"error": str(exc)})

        raise BrowserError(
            "Impossible de lancer un navigateur. Essayés : "
            + " | ".join(launch_errors)
        )

    # ── Scroll helpers ─────────────────────────────────────────────────

    async def _trigger_scroll(self, page: Page):
        """Scroll down then partially back up to trigger lazy-loaded API calls."""
        try:
            vw = page.viewport_size or {"width": 1280, "height": 900}
            down = random.randint(int(vw["height"] * 0.3), int(vw["height"] * 0.7))
            await page.mouse.wheel(0, down)
            await self._human_delay()
            # Partial scroll back — humans almost never stay at the bottom
            back = random.randint(int(down * 0.2), int(down * 0.5))
            await page.mouse.wheel(0, -back)
            await self._human_delay()
        except Exception:
            pass

    async def _scroll_down(self, page: Page) -> bool:
        """Scroll toward the bottom in a human-like way, return True if new content appeared."""
        prev = await page.evaluate("document.body.scrollHeight")
        vw = page.viewport_size or {"width": 1280, "height": 900}

        # Multi-step scroll: a few wheel events instead of jumping to scrollHeight
        steps = random.randint(2, 4)
        for i in range(steps):
            chunk = random.randint(int(vw["height"] * 0.4), int(vw["height"] * 0.9))
            await page.mouse.wheel(0, chunk)

        deadline = asyncio.get_running_loop().time() + TIMEOUT_SCROLL / 1000
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(SCROLL_POLL_INTERVAL)
            if await page.evaluate("document.body.scrollHeight") > prev:
                return True
        return False

    # ── Storage state ──────────────────────────────────────────────────

    async def _persist_storage_state(self, context: BrowserContext):
        self.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(self.storage_state_path))
        logger.debug(f"État de session sauvegardé : {self.storage_state_path}")

    # ── Profile readiness ──────────────────────────────────────────────

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

    # ── Grid recovery ──────────────────────────────────────────────────

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

            # Exponential backoff between recovery attempts
            await asyncio.sleep(VIDEO_RETRY_BACKOFF * (attempt ** 1.5))

    # ── JSON extraction ────────────────────────────────────────────────

    async def _extract_profile_json(self, page: Page) -> Optional[dict]:
        try:
            result = await page.evaluate(r"""() => {
                function tryParse(id) {
                    const el = document.querySelector(id);
                    if (!el) return null;
                    try { return JSON.parse(el.textContent); } catch(e) { return null; }
                }

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

    # ── Followers DOM fallback ─────────────────────────────────────────

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

    # ── href collection with human scroll ─────────────────────────────

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

    # ── Individual video scrape ────────────────────────────────────────

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
            if response.status == 429:
                await self._rate_limit_backoff()
                return
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

    # ── Popups ─────────────────────────────────────────────────────────

    async def _dismiss_popup(self, page: Page):
        selectors = [
            # GDPR info banner (e.g. "Got it" / "Compris" / "Verstanden")
            ("gdpr", (
                "button:has-text('Got it'), button:has-text('Compris'), "
                "button:has-text('Verstanden'), button:has-text('OK')"
            )),
            # Cookie consent — all languages TikTok serves
            ("cookies_accept", (
                "button:has-text('Accept all'), "         # EN
                "button:has-text('Alle erlauben'), "      # DE
                "button:has-text('Tout accepter'), "      # FR
                "button:has-text('Aceptar todo'), "       # ES
                "button:has-text('Aceitar tudo'), "       # PT
                "button:has-text('Accetta tutto'), "      # IT
                "button:has-text('Alle accepteren'), "    # NL
                "button:has-text('Acceptera alla')"       # SV
            )),
            # Cookie consent — decline/refuse variants
            ("cookies_decline", (
                "button:has-text('Decline optional cookies'), "
                "button:has-text('Optionale Cookies ablehnen'), "
                "button:has-text('Refuser les cookies'), "
                "button:has-text('Refuser')"
            )),
            # Generic TikTok cookie banner fallback (data-e2e or last button in banner)
            ("cookies_generic", (
                "[data-e2e='cookie-banner-accept'], "
                "[data-e2e='cookie-accept'], "
                "div[class*='cookie'] button:last-child, "
                "div[class*='Cookie'] button:last-child"
            )),
            # Login modal close button
            ("login_close", (
                "[data-e2e='modal-close-inner-button'], "
                "button[aria-label='Close'], "
                "button[aria-label='Fermer'], "
                "button[aria-label='Schließen']"
            )),
        ]
        for attempt in range(6):
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

    # ── Video grid detection ───────────────────────────────────────────

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
