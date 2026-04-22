"""
Normalisation Twitter / X vers les modeles communs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from models.post import NormalizedPost
from models.profile import NormalizedProfile
from utils.url_parser import build_twitter_profile_url


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\x00", "").strip()
    return text or None


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_twitter_datetime(value: Any) -> str | None:
    if not value:
        return None

    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()

    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None

        for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
            try:
                return datetime.strptime(candidate, fmt).isoformat()
            except ValueError:
                continue

        try:
            return datetime.fromisoformat(candidate.replace("Z", "+00:00")).isoformat()
        except ValueError:
            return candidate

    return None


def _first_expanded_url(urls: list[dict[str, Any]] | None) -> str | None:
    for item in urls or []:
        candidate = _clean_text(item.get("expanded_url") or item.get("unwound_url") or item.get("url"))
        if candidate:
            return candidate
    return None


def _pick_best_video_variant(media: dict[str, Any]) -> str | None:
    variants = ((media.get("video_info") or {}).get("variants")) or []
    best_url = None
    best_bitrate = -1

    for variant in variants:
        if not isinstance(variant, dict):
            continue
        candidate = _clean_text(variant.get("url"))
        if not candidate:
            continue

        bitrate = _as_int(variant.get("bitrate")) or 0
        if bitrate >= best_bitrate:
            best_bitrate = bitrate
            best_url = candidate

    return best_url


def _extract_media_entities(tweet_data: dict[str, Any]) -> list[dict[str, Any]]:
    extended_entities = tweet_data.get("extended_entities") or {}
    media = extended_entities.get("media")
    if isinstance(media, list) and media:
        return [item for item in media if isinstance(item, dict)]

    entities = tweet_data.get("entities") or {}
    media = entities.get("media")
    if isinstance(media, list):
        return [item for item in media if isinstance(item, dict)]

    return []


def _extract_media_urls(tweet_data: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for media in _extract_media_entities(tweet_data):
        media_type = media.get("type")
        if media_type == "photo":
            candidate = _clean_text(media.get("media_url_https") or media.get("media_url"))
        else:
            candidate = _pick_best_video_variant(media) or _clean_text(
                media.get("media_url_https") or media.get("media_url")
            )

        if candidate and candidate not in urls:
            urls.append(candidate)

    return urls


def _is_twitter_internal_link(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return host in {"x.com", "www.x.com", "twitter.com", "www.twitter.com", "t.co", "pic.twitter.com"}


def _extract_external_links(tweet_data: dict[str, Any]) -> list[str]:
    entities = tweet_data.get("entities") or {}
    links: list[str] = []

    for item in entities.get("urls") or []:
        if not isinstance(item, dict):
            continue
        candidate = _clean_text(item.get("expanded_url") or item.get("unwound_url") or item.get("url"))
        if not candidate or _is_twitter_internal_link(candidate):
            continue
        if candidate not in links:
            links.append(candidate)

    return links


def _has_poll(tweet_data: dict[str, Any]) -> bool:
    card = tweet_data.get("card")
    if not isinstance(card, dict):
        return False

    name = _clean_text((card.get("name") or {}).get("name") if isinstance(card.get("name"), dict) else card.get("name"))
    if name and "poll" in name.lower():
        return True

    binding_values = card.get("binding_values") or []
    for item in binding_values:
        key = _clean_text(item.get("key")) if isinstance(item, dict) else None
        if key and "poll" in key.lower():
            return True

    return False


def detect_post_type(tweet_data: dict[str, Any]) -> str:
    """Classement centralise des types de posts Twitter/X.

    Priorite retenue:
    repost > quote > poll > video > gif > image > link > text > unknown
    """
    if not isinstance(tweet_data, dict):
        return "unknown"

    if isinstance(tweet_data.get("retweeted_status"), dict):
        return "repost"

    if tweet_data.get("is_quote_status") or tweet_data.get("quoted_status_id_str") or tweet_data.get("quoted_status"):
        return "quote"

    if _has_poll(tweet_data):
        return "poll"

    media = _extract_media_entities(tweet_data)
    media_types = {item.get("type") for item in media}

    if "video" in media_types:
        return "video"
    if "animated_gif" in media_types:
        return "gif"
    if "photo" in media_types:
        return "image"

    if _extract_external_links(tweet_data):
        return "link"

    text = _clean_text(
        tweet_data.get("full_text")
        or tweet_data.get("text")
        or ((tweet_data.get("retweeted_status") or {}).get("full_text"))
        or ((tweet_data.get("quoted_status") or {}).get("full_text"))
    )
    if text:
        return "text"

    return "unknown"


def normalize_profile(
    username: str,
    profile_data: dict[str, Any],
    *,
    include_raw: bool = False,
) -> NormalizedProfile:
    entities = profile_data.get("entities") or {}
    website_urls = (entities.get("url") or {}).get("urls") if isinstance(entities.get("url"), dict) else None
    screen_name = _clean_text(profile_data.get("screen_name")) or username
    pinned_ids = profile_data.get("pinned_tweet_ids_str")
    pinned_post_id = None
    if isinstance(pinned_ids, list) and pinned_ids:
        pinned_post_id = _clean_text(pinned_ids[0])
    elif isinstance(pinned_ids, str):
        pinned_post_id = _clean_text(pinned_ids)

    public_metrics = {
        "followers_count": _as_int(profile_data.get("followers_count")),
        "following_count": _as_int(profile_data.get("friends_count")),
        "tweets_count": _as_int(profile_data.get("statuses_count")),
        "listed_count": _as_int(profile_data.get("listed_count")),
        "favourites_count": _as_int(profile_data.get("favourites_count")),
    }

    return NormalizedProfile(
        platform="twitter",
        username=screen_name,
        profile_url=build_twitter_profile_url(screen_name),
        display_name=_clean_text(profile_data.get("name")) or screen_name,
        description=_clean_text(profile_data.get("description")),
        created_at=_parse_twitter_datetime(profile_data.get("created_at")),
        profile_image_url=_clean_text(
            profile_data.get("profile_image_url_https") or profile_data.get("profile_image_url")
        ),
        profile_banner_url=_clean_text(profile_data.get("profile_banner_url")),
        followers_count=public_metrics["followers_count"],
        following_count=public_metrics["following_count"],
        posts_count=public_metrics["tweets_count"],
        tweets_count=public_metrics["tweets_count"],
        verified=profile_data.get("verified") if isinstance(profile_data.get("verified"), bool) else None,
        pinned_post_id=pinned_post_id,
        protected=profile_data.get("protected") if isinstance(profile_data.get("protected"), bool) else None,
        location=_clean_text(profile_data.get("location")),
        website_url=_first_expanded_url(website_urls),
        listed_count=public_metrics["listed_count"],
        public_metrics={key: value for key, value in public_metrics.items() if value is not None},
        raw=profile_data if include_raw else None,
        extra={
            key: value
            for key, value in {
                "id_str": _clean_text(profile_data.get("id_str") or profile_data.get("id")),
                "favourites_count": public_metrics["favourites_count"],
            }.items()
            if value is not None
        },
    )


def normalize_post(
    username: str,
    tweet_data: dict[str, Any],
    *,
    include_raw: bool = False,
) -> NormalizedPost:
    post_id = _clean_text(tweet_data.get("id_str") or tweet_data.get("id") or tweet_data.get("rest_id")) or ""
    author_username = (
        _clean_text(((tweet_data.get("user") or {}).get("screen_name")))
        or _clean_text(((tweet_data.get("core") or {}).get("user_results") or {}).get("result", {}).get("legacy", {}).get("screen_name"))
        or username
    )
    text = _clean_text(
        tweet_data.get("full_text")
        or tweet_data.get("text")
        or ((tweet_data.get("retweeted_status") or {}).get("full_text"))
        or ((tweet_data.get("quoted_status") or {}).get("full_text"))
    )
    media_urls = _extract_media_urls(tweet_data)
    external_links = _extract_external_links(tweet_data)
    post_type = detect_post_type(tweet_data)
    view_count = _as_int(
        ((tweet_data.get("ext_views") or {}).get("count"))
        or ((tweet_data.get("views") or {}).get("count"))
        or tweet_data.get("view_count")
    )

    extra = {
        key: value
        for key, value in {
            "conversation_id": _clean_text(tweet_data.get("conversation_id_str")),
            "lang": _clean_text(tweet_data.get("lang")),
            "quoted_post_id": _clean_text(tweet_data.get("quoted_status_id_str")),
            "retweeted_post_id": _clean_text(((tweet_data.get("retweeted_status") or {}).get("id_str"))),
        }.items()
        if value is not None
    }

    return NormalizedPost(
        id=post_id,
        platform="twitter",
        author_username=author_username,
        post_url=(
            f"{build_twitter_profile_url(author_username)}/status/{post_id}"
            if post_id
            else build_twitter_profile_url(author_username)
        ),
        text=text,
        description=text,
        type=post_type,
        created_at=_parse_twitter_datetime(tweet_data.get("created_at")),
        like_count=_as_int(tweet_data.get("favorite_count")),
        reply_count=_as_int(tweet_data.get("reply_count")),
        repost_count=_as_int(tweet_data.get("retweet_count")),
        quote_count=_as_int(tweet_data.get("quote_count")),
        view_count=view_count,
        media_urls=media_urls,
        external_links=external_links,
        is_sensitive=(
            tweet_data.get("possibly_sensitive")
            if isinstance(tweet_data.get("possibly_sensitive"), bool)
            else None
        ),
        url=(media_urls[0] if media_urls else (external_links[0] if external_links else None)),
        raw=tweet_data if include_raw else None,
        extra=extra,
    )
