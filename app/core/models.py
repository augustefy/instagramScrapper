"""
Modeles de donnees communs a toutes les plateformes.
Reexporte les dataclasses normalisees depuis le package racine `models`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from models.post import NormalizedPost
from models.profile import NormalizedProfile
from scrapers.base import SocialPost


@dataclass
class SocialProfile:
    """Profil minimal historique partage avec certaines couches legacy."""

    username: str
    platform: str
    followers_count: int = 0
    following_count: int = 0
    posts_count: int = 0
    biography: str = ""
    full_name: str = ""


PostResult = NormalizedPost | SocialPost
ProfileResult = NormalizedProfile | SocialProfile | None


def legacy_post_to_normalized(post: SocialPost) -> NormalizedPost:
    return NormalizedPost(
        id=post.url.rstrip("/").split("/")[-1] or post.url,
        platform=post.platform,
        author_username="",
        post_url=post.url,
        text=post.caption or None,
        description=post.caption or None,
        type=post.media_type or "unknown",
        created_at=post.timestamp or None,
        like_count=post.likes_count or 0,
        reply_count=post.comments_count or 0,
        repost_count=None,
        quote_count=None,
        view_count=post.views_count,
        media_urls=[],
        external_links=[],
        is_sensitive=None,
        raw={
            "timestamp": post.timestamp,
            "views_count": post.views_count,
            "user_followers": post.user_followers,
        },
    )


def _profile_to_dict(profile: Any, platform: str, username: str) -> dict[str, Any]:
    if isinstance(profile, NormalizedProfile):
        return profile.to_dict()

    if isinstance(profile, SocialProfile):
        normalized = NormalizedProfile(
            platform=platform,
            username=profile.username,
            profile_url="",
            display_name=profile.full_name or profile.username,
            description=profile.biography or None,
            followers_count=profile.followers_count,
            following_count=profile.following_count,
            posts_count=profile.posts_count,
            public_metrics={
                "followers_count": profile.followers_count,
                "following_count": profile.following_count,
                "posts_count": profile.posts_count,
            },
        )
        return normalized.to_dict()

    if is_dataclass(profile):
        return asdict(profile)

    return NormalizedProfile(
        platform=platform,
        username=username,
        profile_url="",
        display_name=username,
    ).to_dict()


def _post_to_dict(post: Any) -> dict[str, Any]:
    if isinstance(post, NormalizedPost):
        return post.to_dict()

    if isinstance(post, SocialPost):
        return legacy_post_to_normalized(post).to_dict()

    if is_dataclass(post):
        return asdict(post)

    if isinstance(post, dict):
        return post

    return NormalizedPost(
        id=str(post),
        platform="unknown",
        author_username="",
        post_url="",
        type="unknown",
        raw={"value": repr(post)},
    ).to_dict()


@dataclass
class FetchPostsResult:
    posts: list[PostResult]
    source: str  # "api", "scraper", "guest_api", ...
    platform: str
    username: str
    profile: ProfileResult = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": _profile_to_dict(self.profile, self.platform, self.username),
            "posts": [_post_to_dict(post) for post in self.posts],
        }
