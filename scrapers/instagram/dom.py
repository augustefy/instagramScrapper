from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from playwright.async_api import Error as PlaywrightError, Page, TimeoutError as PlaywrightTimeout

from app.core.log import get_logger
from bench import Bench
from exceptions import SelectorsOutdatedError
from scrapers.instagram.config import (
    BASE_URL,
    POPUP_DISMISS_WAIT,
    SCROLL_POLL_INTERVAL,
    SELECTORS,
    TIMEOUT_PAGE_LOAD,
    TIMEOUT_POPUP_DISMISS,
    TIMEOUT_SCROLL,
)

logger = get_logger(__name__)


class DOMParser:
    """DOM-oriented extraction and page interaction helpers."""

    def __init__(self, bench: Bench) -> None:
        self._bench = bench

    async def dismiss_popup(self, page: Page) -> None:
        for attempt in range(4):
            clicked = False
            for label, selector in [
                ("cookies", SELECTORS.COOKIE_BUTTON),
                ("login", SELECTORS.LOGIN_BUTTON),
            ]:
                try:
                    await page.click(selector, timeout=TIMEOUT_POPUP_DISMISS)
                    logger.info(f"  -> Fermeture du popup ({label}, round {attempt + 1})")
                    await asyncio.sleep(POPUP_DISMISS_WAIT)
                    clicked = True
                    break
                except PlaywrightTimeout:
                    continue
            if not clicked:
                break

    async def wait_for_post_links(self, page: Page, timeout: int = TIMEOUT_PAGE_LOAD) -> None:
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while asyncio.get_running_loop().time() < deadline:
            count = await page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]'))
                    .filter(a => /^\\/.+\\/(p|reel)\\/[A-Za-z0-9_-]+/.test(a.getAttribute('href')))
                    .length"""
            )
            if count > 0:
                logger.info(f"  {count} post(s) detectes dans le DOM")
                return
            await asyncio.sleep(SCROLL_POLL_INTERVAL)

        await page.screenshot(path="debug_screenshot.png", full_page=False)
        logger.error(
            "Aucun post trouve. Les selecteurs sont probablement obsoletes.",
            extra={"screenshot": "debug_screenshot.png"},
        )
        raise SelectorsOutdatedError(
            "Aucun post trouve. Instagram a probablement change son HTML. "
            "Verifiez les selecteurs dans scrapers/instagram/config.py"
        )

    async def get_user_followers(self, page: Page) -> int:
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
        except (PlaywrightError, TypeError, ValueError) as exc:
            logger.debug("Erreur extraction followers", extra={"error": str(exc)}, exc_info=True)
            return 0

        logger.debug(f"Followers detectes : {followers}")
        return int(followers or 0)

    async def collect_n_hrefs(self, page: Page, n: int) -> list[str]:
        seen: set[str] = set()
        hrefs: list[str] = []
        scroll_count = 0

        while len(hrefs) < n:
            with self._bench.timer(f"collect_links#{scroll_count + 1}"):
                new_links = await self.collect_post_links(page)

            new_count = 0
            for href, pinned in new_links:
                if href in seen:
                    continue
                seen.add(href)
                if pinned:
                    logger.debug(f"  [epingle, ignore] {href}")
                    continue
                hrefs.append(href)
                logger.info(f"  [post] {BASE_URL}{href}")
                new_count += 1
                if len(hrefs) >= n:
                    break

            logger.info(f"  {new_count} nouveau(x) lien(s) - total : {len(hrefs)}/{n}")
            if len(hrefs) >= n:
                break

            scroll_count += 1
            with self._bench.timer(f"scroll#{scroll_count}"):
                if not await self.scroll_down(page):
                    logger.info("Fin de la page atteinte")
                    break

        return hrefs[:n]

    async def collect_post_links(self, page: Page) -> list[tuple[str, bool]]:
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
        except (PlaywrightError, TypeError, ValueError) as exc:
            logger.warning("Erreur lors de la collecte des liens", extra={"error": str(exc)}, exc_info=True)
            return []

        if not isinstance(raw, list):
            return []

        links: list[tuple[str, bool]] = []
        for item in raw:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                href, pinned = item
                links.append((str(href), bool(pinned)))
        return links

    async def scroll_down(self, page: Page) -> bool:
        prev = await page.evaluate("document.body.scrollHeight")
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        deadline = asyncio.get_running_loop().time() + TIMEOUT_SCROLL / 1000
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(SCROLL_POLL_INTERVAL)
            if await page.evaluate("document.body.scrollHeight") > prev:
                return True
        return False

    async def extract_post_dom_data(self, page: Page) -> dict[str, Any]:
        return await page.evaluate(f"""() => {{
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


def parse_media_api_data(body: dict[str, Any]) -> dict[str, Any] | None:
    items = body.get("items", [])
    if not items:
        return None

    item = items[0]
    if not isinstance(item, dict):
        return None

    api_data: dict[str, Any] = {}
    cap = item.get("caption") or {}
    api_data["caption"] = cap.get("text", "") if isinstance(cap, dict) else ""

    ts = item.get("taken_at")
    if ts:
        try:
            api_data["timestamp"] = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            api_data["timestamp"] = ""

    api_data["likes_count"] = item.get("like_count", 0)
    api_data["comments_count"] = item.get("comment_count", 0)

    if item.get("carousel_media_count"):
        api_data["media_type"] = "carousel"
    elif item.get("video_duration") or item.get("product_type") == "clips":
        api_data["media_type"] = "reel" if item.get("product_type") == "clips" else "video"
    else:
        api_data["media_type"] = "image"

    return api_data
