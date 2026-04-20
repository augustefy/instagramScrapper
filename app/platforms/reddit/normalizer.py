"""
Normalisation des donnees Reddit vers des modeles multi-plateformes.
"""

from __future__ import annotations

from html import unescape
from typing import Any

from app.core.models import NormalizedPost, NormalizedProfile
from app.platforms.reddit.url import build_profile_url


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def _first_gallery_media_url(post_data: dict[str, Any]) -> str | None:
    media_metadata = post_data.get("media_metadata")
    gallery_data = post_data.get("gallery_data")

    if not isinstance(media_metadata, dict) or not isinstance(gallery_data, dict):
        return None

    items = gallery_data.get("items") or []
    for item in items:
        media_id = item.get("media_id")
        if not media_id:
            continue

        metadata = media_metadata.get(media_id) or {}
        previews = metadata.get("p") or []
        if previews:
            candidate = previews[-1].get("u")
            if candidate:
                return unescape(candidate)

        source = metadata.get("s") or {}
        candidate = source.get("u")
        if candidate:
            return unescape(candidate)

    return None


def detect_post_type(post_data: dict[str, Any]) -> str:
    if post_data.get("is_self") is True:
        return "text"
    if post_data.get("post_hint") == "image":
        return "image"
    if post_data.get("is_video") is True or ((post_data.get("media") or {}).get("reddit_video")):
        return "video"
    if post_data.get("is_gallery") is True:
        return "gallery"
    if post_data.get("post_hint") == "link":
        return "link"
    return "unknown"


def normalize_profile(
    username: str,
    about_data: dict[str, Any],
    *,
    include_raw: bool = False,
) -> NormalizedProfile:
    subreddit = about_data.get("subreddit") or {}

    public_metrics = {
        "comment_karma": int(about_data.get("comment_karma") or 0),
        "link_karma": int(about_data.get("link_karma") or 0),
        "awardee_karma": int(about_data.get("awardee_karma") or 0),
        "awarder_karma": int(about_data.get("awarder_karma") or 0),
    }

    return NormalizedProfile(
        platform="reddit",
        username=username,
        profile_url=build_profile_url(username),
        display_name=_clean_text(subreddit.get("title")) or username,
        description=(
            _clean_text(subreddit.get("public_description"))
            or _clean_text(subreddit.get("description"))
            or _clean_text(about_data.get("subreddit_description"))
        ),
        created_utc=about_data.get("created_utc"),
        icon_img=_clean_text(subreddit.get("icon_img")) or _clean_text(about_data.get("icon_img")),
        total_karma=about_data.get("total_karma"),
        subscribers=subreddit.get("subscribers"),
        public_metrics=public_metrics,
        raw=about_data if include_raw else None,
    )


def normalize_post(
    username: str,
    post_data: dict[str, Any],
    *,
    include_raw: bool = False,
) -> NormalizedPost:
    permalink = post_data.get("permalink")
    full_permalink = f"https://www.reddit.com{permalink}" if permalink else None
    post_type = detect_post_type(post_data)

    media_url = None
    if post_type == "image":
        media_url = post_data.get("url_overridden_by_dest") or post_data.get("url")
    elif post_type == "video":
        media = post_data.get("media") or {}
        secure_media = post_data.get("secure_media") or {}
        reddit_video = (
            media.get("reddit_video")
            or secure_media.get("reddit_video")
            or ((media.get("oembed") or {}).get("thumbnail_url") and {})
        )
        media_url = (
            (reddit_video or {}).get("fallback_url")
            or post_data.get("url_overridden_by_dest")
            or post_data.get("url")
        )
    elif post_type == "gallery":
        media_url = _first_gallery_media_url(post_data) or post_data.get("url")
    elif post_type == "link":
        media_url = post_data.get("url_overridden_by_dest") or post_data.get("url")
    elif post_type == "text":
        media_url = None
    else:
        media_url = post_data.get("url_overridden_by_dest") or post_data.get("url")

    return NormalizedPost(
        id=str(post_data.get("id") or ""),
        platform="reddit",
        author_username=username,
        post_url=full_permalink or build_profile_url(username),
        title=_clean_text(post_data.get("title")) or "",
        description=_clean_text(post_data.get("selftext")),
        type=post_type,
        created_utc=post_data.get("created_utc"),
        score=post_data.get("score"),
        num_comments=post_data.get("num_comments"),
        subreddit=_clean_text(post_data.get("subreddit")),
        permalink=permalink,
        url=media_url,
        is_nsfw=bool(post_data.get("over_18")),
        raw=post_data if include_raw else None,
    )
