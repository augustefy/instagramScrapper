"""
Modeles de donnees communs a toutes les plateformes.
Reutilise SocialPost de scrapers.base pour la compatibilite.
"""

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any

from scrapers.base import SocialPost


@dataclass
class SocialProfile:
    username: str
    platform: str
    followers_count: int = 0
    following_count: int = 0
    posts_count: int = 0
    biography: str = ""
    full_name: str = ""


@dataclass
class NormalizedProfile:
    platform: str
    username: str
    profile_url: str
    display_name: str | None = None
    description: str | None = None
    created_utc: float | None = None
    icon_img: str | None = None
    total_karma: int | None = None
    subscribers: int | None = None
    public_metrics: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NormalizedPost:
    id: str
    platform: str
    author_username: str
    post_url: str
    title: str = ""
    description: str | None = None
    type: str = "unknown"
    created_utc: float | None = None
    score: int | None = None
    num_comments: int | None = None
    subreddit: str | None = None
    permalink: str | None = None
    url: str | None = None
    is_nsfw: bool = False
    raw: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def legacy_post_to_normalized(post: SocialPost) -> NormalizedPost:
    return NormalizedPost(
        id=post.url.rstrip("/").split("/")[-1] or post.url,
        platform=post.platform,
        author_username="",
        post_url=post.url,
        title=post.caption[:120] if post.caption else "",
        description=post.caption or None,
        type=post.media_type or "unknown",
        created_utc=None,
        score=post.likes_count,
        num_comments=post.comments_count,
        subreddit=None,
        permalink=None,
        url=post.url,
        is_nsfw=False,
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
        return {
            "platform": platform,
            "username": profile.username,
            "profile_url": "",
            "display_name": profile.full_name or profile.username,
            "description": profile.biography or None,
            "created_utc": None,
            "icon_img": None,
            "total_karma": None,
            "subscribers": None,
            "public_metrics": {
                "followers_count": profile.followers_count,
                "following_count": profile.following_count,
                "posts_count": profile.posts_count,
            },
            "raw": None,
        }

    if is_dataclass(profile):
        return asdict(profile)

    return {
        "platform": platform,
        "username": username,
        "profile_url": "",
        "display_name": username,
        "description": None,
        "created_utc": None,
        "icon_img": None,
        "total_karma": None,
        "subscribers": None,
        "public_metrics": {},
        "raw": None,
    }


def _post_to_dict(post: Any) -> dict[str, Any]:
    if isinstance(post, NormalizedPost):
        return post.to_dict()

    if isinstance(post, SocialPost):
        return legacy_post_to_normalized(post).to_dict()

    if is_dataclass(post):
        return asdict(post)

    if isinstance(post, dict):
        return post

    return {
        "id": str(post),
        "platform": "unknown",
        "author_username": "",
        "post_url": "",
        "title": "",
        "description": None,
        "type": "unknown",
        "created_utc": None,
        "score": None,
        "num_comments": None,
        "subreddit": None,
        "permalink": None,
        "url": None,
        "is_nsfw": False,
        "raw": {"value": repr(post)},
    }


@dataclass
class FetchPostsResult:
    posts: list[Any]
    source: str  # "api", "scraper"
    platform: str
    username: str
    profile: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": _profile_to_dict(self.profile, self.platform, self.username),
            "posts": [_post_to_dict(post) for post in self.posts],
        }
