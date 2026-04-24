"""
TikTok scraper backed by botasaurus (undetected Chrome via CDP).

Strategies (in order of priority):
  1. CDP network interception → /api/post/item_list/ JSON
  2. Embedded JSON in the page (#__UNIVERSAL_DATA_FOR_REHYDRATION__, #SIGI_STATE)
  3. DOM grid + scroll fallback
"""

import json
import random
import time
from pathlib import Path
from typing import Optional

from botasaurus.browser import Driver
from botasaurus_driver import cdp

from bench import Bench
from exceptions import PageLoadError, SelectorsOutdatedError
from app.core.log import setup_logging
from scrapers.base import BaseScraper, SocialPost
from scrapers.tiktok.config import (
    BASE_URL,
    USER_AGENT_POOL,
    VIEWPORT_POOL,
    LOCALE_POOL,
    REFERRER_POOL,
    HUMAN_DELAY_MIN,
    HUMAN_DELAY_MAX,
    HUMAN_LONG_DELAY_MIN,
    HUMAN_LONG_DELAY_MAX,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_PROFILE_READY,
    TIMEOUT_POPUP_DISMISS,
    SCROLL_POLL_INTERVAL,
    RESPONSE_HANDLER_WAIT,
    FIRST_POST_EXTRA_WAIT,
    VIDEO_RETRY_BACKOFF,
    MAX_RETRY_ATTEMPTS,
    RATE_LIMIT_BACKOFF_BASE,
    RATE_LIMIT_BACKOFF_FACTOR,
    RATE_LIMIT_BACKOFF_MAX,
    RATE_LIMIT_JITTER,
)
from scrapers.tiktok.scraper import _parse_num, _item_to_post, _gaussian_delay
from scrapers.tiktok.validators import validate_tiktok_url, validate_post_count

logger = setup_logging(__name__)

PLATFORM = "tiktok"
BOTA_PROFILE_NAME = "tiktok"

API_ITEM_LIST = "/api/post/item_list/"
API_USER_DETAIL = "/api/user/detail/"


class BotasaurusTikTokScraper(BaseScraper):
    """TikTok scraper using botasaurus (undetected-chrome + CDP)."""

    def __init__(self, headless: bool = True, bench: Optional[Bench] = None):
        self.headless = headless
        self.bench = bench or Bench()
        self._rate_limit_strikes = 0

    # ── Public API ─────────────────────────────────────────────────────

    def scrape(self, url: str, n: int) -> list[SocialPost]:
        url = validate_tiktok_url(url)
        n = validate_post_count(n)
        logger.info("Scraping TikTok démarré (botasaurus)", extra={"url": url, "target_count": n})
        return self._scrape_profile(url, n)

    def health_check(self) -> dict:
        driver = self._make_driver(headless=self.headless)
        try:
            driver.get(BASE_URL, bypass_cloudflare=False)
            return {
                "engine": "botasaurus",
                "headless": self.headless,
                "target_url": BASE_URL,
                "page_title": driver.title,
                "current_url": driver.current_url,
            }
        except Exception as e:
            return {"engine": "botasaurus", "error": str(e)}
        finally:
            driver.close()

    def setup_session(self, wait_seconds: int = 60) -> Path:
        """
        Open a visible Chrome window on TikTok so the user can solve
        challenges / log in manually, then save the session profile.
        """
        logger.info(f"Lancement de Chrome visible pour la configuration de la session TikTok ({wait_seconds}s)...")
        print("\n" + "=" * 60)
        print("SETUP SESSION TIKTOK (botasaurus)")
        print("=" * 60)
        print("Chrome s'ouvre sur TikTok.")
        print("Acceptez les popups, résolvez les CAPTCHAs si nécessaire.")
        print(f"Le navigateur se fermera automatiquement dans {wait_seconds}s.")
        print("=" * 60)

        driver = self._make_driver(headless=False)
        try:
            driver.get(BASE_URL)
            driver.long_random_sleep()
            self._dismiss_popups(driver)
            print(f"\nAttente de {wait_seconds}s... (fermez Chrome manuellement pour arrêter plus tôt)")
            time.sleep(wait_seconds)
        except KeyboardInterrupt:
            logger.info("Setup interrompu par l'utilisateur.")
        finally:
            driver.close()  # auto-saves tiny_profile cookies

        profile_path = Path("profiles") / BOTA_PROFILE_NAME / "profile.json"
        logger.info(f"Session sauvegardée : {profile_path}")
        return profile_path

    # ── Cache management ───────────────────────────────────────────────

    def _clear_cache(self, driver: Driver) -> None:
        """Flush HTTP cache via CDP before the first navigation."""
        try:
            driver.run_cdp_command(cdp.network.clear_browser_cache())
            logger.debug("Cache HTTP vidé (CDP Network.clearBrowserCache)")
        except Exception as e:
            logger.debug(f"clear_browser_cache ignoré : {e}")

    # ── Driver factory ─────────────────────────────────────────────────

    def _make_driver(self, headless: bool) -> Driver:
        ua = random.choice(USER_AGENT_POOL)
        vp = random.choice(VIEWPORT_POOL)
        locale, _ = random.choice(LOCALE_POOL)
        lang = locale.split("-")[0]

        logger.debug(f"Fingerprint botasaurus : ua={ua[:50]}… viewport={vp['width']}x{vp['height']} lang={lang}")

        return Driver(
            headless=headless,
            tiny_profile=True,
            profile=BOTA_PROFILE_NAME,
            user_agent=ua,
            window_size=(vp["width"], vp["height"]),
            lang=lang,
            # Let images through — purely HTML traffic is a bot signal
            block_images=False,
            block_images_and_css=False,
            arguments=["--mute-audio"],
        )

    # ── Core scrape pipeline ───────────────────────────────────────────

    def _scrape_profile(self, url: str, n: int) -> list[SocialPost]:
        username = url.rstrip("/").split("@")[-1]
        driver = self._make_driver(headless=self.headless)

        try:
            driver.enable_human_mode()
            self._clear_cache(driver)

            # ── 1. Register CDP network interception ───────────────────
            api_request_ids: list[str] = []

            def on_response(resp_url: str, response, event) -> None:
                if API_ITEM_LIST in resp_url or API_USER_DETAIL in resp_url:
                    try:
                        api_request_ids.append(str(event.request_id))
                    except Exception:
                        pass
                # 429 detection
                if hasattr(response, "status") and response.status == 429:
                    self._rate_limit_backoff()

            driver.after_response_received(on_response)

            # ── 2. Navigate with a randomized referrer ─────────────────
            referrer = random.choice(REFERRER_POOL)
            logger.info(f"Navigation vers {url} (referrer={referrer or 'direct'})")
            with self.bench.timer("page_load"):
                try:
                    driver.get(url, bypass_cloudflare=False)
                except Exception as e:
                    raise PageLoadError(f"Impossible de charger {url}: {e}") from e

            driver.long_random_sleep()
            self._dismiss_popups(driver)
            self._wait_for_profile_ready(driver)

            # ── 3. Strategy 1 — CDP intercepted API responses ──────────
            with self.bench.timer("api_collect"):
                api_items: list[dict] = []
                user_followers = 0

                for req_id in api_request_ids:
                    try:
                        resp = driver.collect_response(req_id)
                        if resp is None or resp.content is None:
                            continue
                        body = json.loads(resp.content)
                        if API_ITEM_LIST in req_id or "item_list" in (resp.content or ""):
                            items = body.get("itemList") or []
                            api_items.extend(items)
                            logger.debug(f"API item_list : {len(items)} items")
                        elif API_USER_DETAIL in req_id:
                            stats = (body.get("userInfo") or {}).get("stats") or {}
                            fc = stats.get("followerCount", 0)
                            if fc:
                                user_followers = fc
                    except Exception as e:
                        logger.debug(f"Collect response error: {e}")

                # The request_ids we collected don't embed the URL — re-check via content
                # Actually api_request_ids stores request_ids for ANY api url matched above,
                # so collect all and filter by content shape.
                if not api_items:
                    logger.info("Scroll pour déclencher les appels API...")
                    self._human_scroll(driver, partial=True)
                    driver.short_random_sleep()
                    # Collect newly registered request_ids
                    for req_id in api_request_ids:
                        if req_id in [r for r in api_request_ids]:
                            try:
                                resp = driver.collect_response(req_id)
                                if resp and resp.content:
                                    body = json.loads(resp.content)
                                    items = body.get("itemList") or []
                                    if items:
                                        api_items.extend(items)
                                        logger.debug(f"API item_list (post-scroll) : {len(items)} items")
                            except Exception:
                                pass

            if api_items:
                logger.info(f"API interceptée : {len(api_items)} item(s), {user_followers} followers")
                posts = []
                for item in api_items[:n]:
                    post = _item_to_post(item, user_followers, default_author=username)
                    if post:
                        posts.append(post)
                        logger.info(f"  [{len(posts)}/{n}] {post.url}")
                logger.info(f"✓ Terminé : {len(posts)} vidéo(s) (via API CDP)")
                return posts[:n]

            # ── 4. Strategy 2 — Embedded JSON in the page ─────────────
            logger.info("Fallback : JSON embarqué...")
            with self.bench.timer("extract_profile_json"):
                profile_data = self._extract_profile_json(driver)

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
                        logger.info(f"✓ Terminé : {len(posts)} vidéo(s) (via JSON embarqué)")
                        return posts[:n]
                    logger.info(f"JSON insuffisant ({len(posts)}/{n}), fallback DOM...")

            # ── 5. Strategy 3 — DOM grid + scroll ─────────────────────
            logger.info("Fallback DOM + scroll...")
            if not self._wait_for_video_links(driver):
                raise SelectorsOutdatedError(
                    "Aucune vidéo dans le DOM. TikTok bloque ou a changé son HTML."
                )

            user_followers = (profile_data or {}).get("followers", 0) or self._get_followers_dom(driver)
            hrefs = self._collect_n_hrefs(driver, n)
            logger.info(f"✓ Terminé : {len(hrefs)} lien(s) collectés (via DOM)")

            posts = []
            for href in hrefs:
                post = self._scrape_video_page(driver, href, user_followers)
                if post:
                    posts.append(post)
                    logger.info(f"  [{len(posts)}/{n}] {post.url}")
                if len(posts) >= n:
                    break

            return posts[:n]

        finally:
            driver.close()

    # ── Human interaction helpers ──────────────────────────────────────

    def _human_delay(self, long_pause: bool = False):
        if long_pause:
            time.sleep(_gaussian_delay(HUMAN_LONG_DELAY_MIN, HUMAN_LONG_DELAY_MAX))
        else:
            time.sleep(_gaussian_delay(HUMAN_DELAY_MIN, HUMAN_DELAY_MAX))

    def _human_scroll(self, driver: Driver, partial: bool = False):
        """Scroll down a variable amount, optionally scroll back up."""
        try:
            amount = random.randint(300, 700)
            driver.scroll(by=amount, smooth_scroll=True, wait=None)
            self._human_delay()
            if partial or random.random() < 0.6:
                back = random.randint(100, amount // 2)
                driver.scroll(by=-back, smooth_scroll=True, wait=None)
                self._human_delay()
        except Exception:
            pass

    def _rate_limit_backoff(self):
        self._rate_limit_strikes += 1
        base = min(
            RATE_LIMIT_BACKOFF_BASE * (RATE_LIMIT_BACKOFF_FACTOR ** (self._rate_limit_strikes - 1)),
            RATE_LIMIT_BACKOFF_MAX,
        )
        jitter = random.uniform(-RATE_LIMIT_JITTER, RATE_LIMIT_JITTER)
        delay = max(RATE_LIMIT_BACKOFF_BASE, base + jitter)
        logger.warning(f"Rate-limit détecté (strike {self._rate_limit_strikes}), backoff {delay:.1f}s")
        time.sleep(delay)

    # ── Popup dismissal ────────────────────────────────────────────────

    def _dismiss_popups(self, driver: Driver):
        popup_texts = [
            "Got it", "Compris",
            "Accept all", "Tout accepter",
            "Decline optional cookies", "Refuser",
        ]
        for text in popup_texts:
            try:
                el = driver.get_element_containing_text(text)
                if el:
                    el.click()
                    logger.info(f"  → Popup fermée : '{text}'")
                    self._human_delay()
            except Exception:
                pass

    # ── Profile readiness ──────────────────────────────────────────────

    def _wait_for_profile_ready(self, driver: Driver):
        deadline = time.time() + TIMEOUT_PROFILE_READY / 1000
        while time.time() < deadline:
            try:
                ready = driver.run_js(r"""
                    const hasEmbedded =
                        !!document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__') ||
                        !!document.querySelector('#SIGI_STATE');
                    const hasVideos = Array.from(document.querySelectorAll('a[href]'))
                        .some(a => /\/@[\w.]+\/video\/\d+/.test(a.getAttribute('href') || ''));
                    const bodyText = document.body.innerText || '';
                    return hasEmbedded || hasVideos ||
                        /Followers|Abonnés|Following/i.test(bodyText);
                """)
                if ready:
                    return
            except Exception:
                pass
            time.sleep(SCROLL_POLL_INTERVAL)

        logger.info("Profil pas encore prêt, scroll de réveil...")
        self._human_scroll(driver, partial=True)
        time.sleep(RESPONSE_HANDLER_WAIT * 2)

    # ── JSON extraction ────────────────────────────────────────────────

    def _extract_profile_json(self, driver: Driver) -> Optional[dict]:
        try:
            return driver.run_js(r"""
                function tryParse(id) {
                    const el = document.querySelector(id);
                    if (!el) return null;
                    try { return JSON.parse(el.textContent); } catch(e) { return null; }
                }

                const ud = tryParse('#__UNIVERSAL_DATA_FOR_REHYDRATION__');
                if (ud) {
                    const scope = ud['__DEFAULT_SCOPE__'] || {};
                    const detail = scope['webapp.user-detail'] || {};
                    const userInfo = detail.userInfo || {};
                    const stats = userInfo.stats || {};
                    const user = userInfo.user || {};
                    const items = userInfo.itemList || detail.itemList || [];
                    if (stats.followerCount > 0 || items.length > 0) {
                        return { source: 'universal_data', username: user.uniqueId || '',
                                 followers: stats.followerCount || 0, items: items };
                    }
                }

                const sigi = tryParse('#SIGI_STATE');
                if (sigi) {
                    const userModule = sigi.UserModule || {};
                    const users = userModule.users || {};
                    const statsMap = userModule.stats || {};
                    const username = Object.keys(users)[0] || '';
                    const userStats = statsMap[username] || {};
                    const items = Object.values(sigi.ItemModule || {});
                    if (items.length > 0 || userStats.followerCount > 0) {
                        return { source: 'sigi_state', username: username,
                                 followers: userStats.followerCount || 0, items: items };
                    }
                }

                return null;
            """)
        except Exception as e:
            logger.debug(f"JSON profil introuvable: {e}")
            return None

    # ── Followers fallback ─────────────────────────────────────────────

    def _get_followers_dom(self, driver: Driver) -> int:
        try:
            return driver.run_js(r"""
                function parseNum(t) {
                    if (!t) return 0;
                    const m = t.replace(/\s/g,'').replace(/,/g,'.').match(/([\d.]+)([MKmk])?/);
                    if (!m) return 0;
                    let n = parseFloat(m[1]);
                    if (m[2]) { const u = m[2].toUpperCase(); if (u==='M') n*=1e6; else if (u==='K') n*=1e3; }
                    return Math.floor(n);
                }
                const el = document.querySelector('[data-e2e="followers-count"]');
                if (el) return parseNum(el.innerText);
                const m = (document.body.innerText||'').match(/([\d.,]+[MKmk]?)\s*(?:Followers|Abonnés)/i);
                return m ? parseNum(m[1]) : 0;
            """) or 0
        except Exception:
            return 0

    # ── Video link collection ──────────────────────────────────────────

    def _wait_for_video_links(self, driver: Driver) -> bool:
        deadline = time.time() + TIMEOUT_PROFILE_READY / 1000
        while time.time() < deadline:
            count = self._count_video_links(driver)
            if count > 0:
                logger.info(f"  {count} vidéo(s) détectées dans le DOM")
                return True
            time.sleep(SCROLL_POLL_INTERVAL)
        return False

    def _count_video_links(self, driver: Driver) -> int:
        try:
            return driver.run_js(r"""
                return Array.from(document.querySelectorAll('a[href]'))
                    .filter(a => /\/@[\w.]+\/video\/\d+/.test(a.getAttribute('href')||'')).length;
            """) or 0
        except Exception:
            return 0

    def _collect_video_links(self, driver: Driver) -> list[str]:
        try:
            return driver.run_js(r"""
                const seen = new Set();
                return Array.from(document.querySelectorAll('a[href]'))
                    .map(a => (a.getAttribute('href')||'').replace(/^https?:\/\/(?:www\.)?tiktok\.com/,''))
                    .filter(h => {
                        if (!/\/@[\w.]+\/video\/\d+/.test(h) || seen.has(h)) return false;
                        seen.add(h); return true;
                    });
            """) or []
        except Exception:
            return []

    def _collect_n_hrefs(self, driver: Driver, n: int) -> list[str]:
        seen: set[str] = set()
        hrefs: list[str] = []
        scroll_count = 0

        while len(hrefs) < n:
            for href in self._collect_video_links(driver):
                if href not in seen:
                    seen.add(href)
                    hrefs.append(href)
                    logger.info(f"  [vidéo] {BASE_URL}{href}")
                if len(hrefs) >= n:
                    break

            if len(hrefs) >= n:
                break

            scroll_count += 1
            if not driver.can_scroll_further():
                logger.info("Fin de page atteinte")
                break
            self._human_scroll(driver, partial=False)
            time.sleep(SCROLL_POLL_INTERVAL)

        return hrefs[:n]

    # ── Individual video scrape (DOM-only) ─────────────────────────────

    def _scrape_video_page(self, driver: Driver, href: str, user_followers: int) -> Optional[SocialPost]:
        video_url = href if href.startswith("http") else f"{BASE_URL}{href}"
        try:
            driver.get(video_url)
            driver.short_random_sleep()

            data = driver.run_js(r"""
                function parseNum(t) {
                    if (!t) return 0;
                    const m = t.replace(/\s/g,'').replace(/,/g,'.').match(/([\d.]+)([MKmk])?/);
                    if (!m) return 0;
                    let n = parseFloat(m[1]);
                    if (m[2]) { const u = m[2].toUpperCase(); if (u==='M') n*=1e6; else if (u==='K') n*=1e3; }
                    return Math.floor(n);
                }
                try {
                    const s = document.querySelector('#__UNIVERSAL_DATA_FOR_REHYDRATION__');
                    if (s) {
                        const j = JSON.parse(s.textContent);
                        const item = ((j['__DEFAULT_SCOPE__']||{})['webapp.video-detail']||{}).itemInfo?.itemStruct;
                        if (item) {
                            const st = item.stats||item.statsV2||{};
                            return { caption: item.desc||'', timestamp: item.createTime ? new Date(item.createTime*1000).toISOString() : '',
                                     likes_count: parseInt(st.diggCount)||0, comments_count: parseInt(st.commentCount)||0,
                                     views_count: parseInt(st.playCount)||0, media_type: item.imagePost?'photo':'video' };
                        }
                    }
                } catch(e) {}
                const descEl = document.querySelector('[data-e2e="browse-video-desc"],[data-e2e="video-desc"]');
                const likeEl = document.querySelector('[data-e2e="browse-like-count"],[data-e2e="like-count"]');
                const timeEl = document.querySelector('time[datetime]');
                return { caption: descEl?.innerText||'', timestamp: timeEl?.getAttribute('datetime')||'',
                         likes_count: likeEl ? parseNum(likeEl.innerText) : 0,
                         comments_count: 0, views_count: 0, media_type: 'video' };
            """)

            if not data or not any([data.get("caption"), data.get("timestamp"), data.get("likes_count")]):
                return None

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
        except Exception as e:
            logger.warning(f"Erreur vidéo {video_url}: {e}")
            return None
