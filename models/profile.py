"""
Modele normalise d'un profil social.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class NormalizedProfile:
    platform: str
    username: str
    profile_url: str
    display_name: str | None = None
    description: str | None = None
    created_at: str | None = None
    profile_image_url: str | None = None
    profile_banner_url: str | None = None
    followers_count: int | None = None
    following_count: int | None = None
    posts_count: int | None = None
    tweets_count: int | None = None
    verified: bool | None = None
    pinned_post_id: str | None = None
    protected: bool | None = None
    location: str | None = None
    website_url: str | None = None
    listed_count: int | None = None
    subscribers: int | None = None
    total_karma: int | None = None
    public_metrics: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.raw is None:
            data.pop("raw", None)
        if not self.extra:
            data.pop("extra", None)
        return data
