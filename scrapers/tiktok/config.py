BASE_URL = "https://www.tiktok.com"

# Resources to never block — letting some through looks more human
BLOCKED_RESOURCE_TYPES: set[str] = set()
# Resources that are always safe to abort (they add no anti-bot value)
ABORT_RESOURCE_TYPES = {"font", "media"}

BROWSER_PREFERENCE = ("chromium", "firefox")
STORAGE_STATE_PATH = ".playwright/tiktok_state.json"

WORKERS = 5
MAX_RETRY_ATTEMPTS = 3
GRID_RECOVERY_ATTEMPTS = 3

TIMEOUT_PAGE_LOAD = 25000
TIMEOUT_POST_LOAD = 18000
TIMEOUT_PROFILE_READY = 18000
TIMEOUT_FIRST_POST_READY = 22000
TIMEOUT_POST_READY = 10000
TIMEOUT_GRID_RECOVERY = 10000
TIMEOUT_POPUP_DISMISS = 3000
TIMEOUT_SCROLL = 6000

# ── Pool of realistic desktop Chrome UAs (rotated per session). ──
USER_AGENT_POOL = [
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:124.0) Gecko/20100101 Firefox/124.0",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

# Kept for backward compat (health check uses it directly)
USER_AGENT = USER_AGENT_POOL[0]

# ── Realistic desktop viewport variations. ──
VIEWPORT_POOL = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1280, "height": 800},
    {"width": 1366, "height": 768},
    {"width": 1600, "height": 900},
    {"width": 2560, "height": 1440},
]
VIEWPORT = VIEWPORT_POOL[1]

# ── Locale & timezone pools. ──
LOCALE_POOL = [
    ("en-US", "America/New_York"),
    ("en-GB", "Europe/London"),
    ("en-CA", "America/Toronto"),
    ("fr-FR", "Europe/Paris"),
]
LOCALE = LOCALE_POOL[0][0]
TIMEZONE_ID = LOCALE_POOL[0][1]

# ── Referrer pool for initial navigation. ──
REFERRER_POOL = [
    "https://www.google.com/",
    "https://www.google.fr/",
    "https://www.bing.com/",
    "https://duckduckgo.com/",
    "",  # direct navigation (no referrer)
]

# ── Full realistic HTTP headers. ──
EXTRA_HTTP_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,fr;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# ── Timing (seconds unless noted). ──
POPUP_DISMISS_WAIT = 0.0
SCROLL_POLL_INTERVAL = 0.35
RESPONSE_HANDLER_WAIT = 0.0
FIRST_POST_EXTRA_WAIT = 0.0
VIDEO_RETRY_BACKOFF = 0.0

# Human-like random delay ranges (uniform bounds fed into gaussian jitter)
# `y` = HUMAN_DELAY_MAX is the knob we benchmark. Overridable via env for tuning.
# Env vars (all optional, float):
#   TIKTOK_DELAY_MIN, TIKTOK_DELAY_MAX,
#   TIKTOK_LONG_DELAY_MIN, TIKTOK_LONG_DELAY_MAX
import os as _os


def _env_float(name: str, default: float) -> float:
    raw = _os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


HUMAN_DELAY_MIN = _env_float("TIKTOK_DELAY_MIN", 0.0)
HUMAN_DELAY_MAX = _env_float("TIKTOK_DELAY_MAX", 1.0)
HUMAN_LONG_DELAY_MIN = _env_float("TIKTOK_LONG_DELAY_MIN", 0.0)
HUMAN_LONG_DELAY_MAX = _env_float("TIKTOK_LONG_DELAY_MAX", 1.0)

# Keep min ≤ max to avoid gaussian_delay clamping edge cases
if HUMAN_DELAY_MIN > HUMAN_DELAY_MAX:
    HUMAN_DELAY_MIN = min(HUMAN_DELAY_MIN, HUMAN_DELAY_MAX)
if HUMAN_LONG_DELAY_MIN > HUMAN_LONG_DELAY_MAX:
    HUMAN_LONG_DELAY_MIN = min(HUMAN_LONG_DELAY_MIN, HUMAN_LONG_DELAY_MAX)

# Reading pause: proportional to content length (chars → seconds)
READING_CHARS_PER_SECOND = 250
READING_PAUSE_MIN = 0.0
READING_PAUSE_MAX = 0.0

# ── 429 / rate-limit backoff. ──
RATE_LIMIT_BACKOFF_BASE = 5.0    # seconds for first 429
RATE_LIMIT_BACKOFF_FACTOR = 2.2  # exponential multiplier
RATE_LIMIT_BACKOFF_MAX = 90.0    # cap
RATE_LIMIT_JITTER = 3.0          # ± random seconds added on top
