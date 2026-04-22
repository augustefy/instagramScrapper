import pytest

from normalizers.twitter import detect_post_type, normalize_post, normalize_profile
from utils.url_parser import build_twitter_profile_url, parse_twitter_profile_url


@pytest.mark.parametrize(
    ("url", "expected_username"),
    [
        ("https://x.com/elonmusk", "elonmusk"),
        ("https://x.com/elonmusk/", "elonmusk"),
        ("https://twitter.com/elonmusk", "elonmusk"),
        ("https://www.twitter.com/elonmusk/", "elonmusk"),
    ],
)
def test_parse_twitter_profile_url_accepts_supported_hosts(url, expected_username):
    parsed = parse_twitter_profile_url(url)

    assert parsed.username == expected_username
    assert parsed.canonical_url == "https://x.com/elonmusk"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/elonmusk",
        "https://x.com/elonmusk/status/123456",
        "https://twitter.com/",
        "https://x.com/elon-musk",
        "https://x.com/home",
    ],
)
def test_parse_twitter_profile_url_rejects_invalid_inputs(url):
    with pytest.raises(Exception):
        parse_twitter_profile_url(url)


@pytest.mark.parametrize(
    ("tweet_data", "expected_type"),
    [
        ({"retweeted_status": {"id_str": "1"}}, "repost"),
        ({"quoted_status_id_str": "2"}, "quote"),
        ({"card": {"name": "poll2choice_text_only"}}, "poll"),
        (
            {
                "extended_entities": {
                    "media": [{"type": "video", "video_info": {"variants": []}}],
                }
            },
            "video",
        ),
        (
            {
                "extended_entities": {
                    "media": [{"type": "animated_gif", "video_info": {"variants": []}}],
                }
            },
            "gif",
        ),
        (
            {
                "extended_entities": {
                    "media": [{"type": "photo", "media_url_https": "https://img"}],
                }
            },
            "image",
        ),
        (
            {"entities": {"urls": [{"expanded_url": "https://example.com/article"}]}},
            "link",
        ),
        ({"full_text": "hello world"}, "text"),
    ],
)
def test_detect_post_type_covers_priority_rules(tweet_data, expected_type):
    assert detect_post_type(tweet_data) == expected_type


def test_detect_post_type_prefers_semantic_repost_over_media():
    tweet_data = {
        "retweeted_status": {"id_str": "42"},
        "extended_entities": {
            "media": [{"type": "photo", "media_url_https": "https://img.example/1.jpg"}]
        },
        "entities": {"urls": [{"expanded_url": "https://example.com"}]},
    }

    assert detect_post_type(tweet_data) == "repost"


def test_normalize_profile_maps_public_fields():
    raw_profile = {
        "screen_name": "elonmusk",
        "name": "Elon Musk",
        "description": "Occupy Mars",
        "created_at": "Wed Jun 02 20:12:29 +0000 2009",
        "profile_image_url_https": "https://pbs.twimg.com/profile.jpg",
        "profile_banner_url": "https://pbs.twimg.com/banner.jpg",
        "followers_count": 100,
        "friends_count": 50,
        "statuses_count": 25,
        "verified": True,
        "protected": False,
        "location": "Austin, TX",
        "listed_count": 5,
        "pinned_tweet_ids_str": ["12345"],
        "entities": {"url": {"urls": [{"expanded_url": "https://www.tesla.com"}]}},
    }

    profile = normalize_profile("elonmusk", raw_profile, include_raw=True)

    assert profile.platform == "twitter"
    assert profile.username == "elonmusk"
    assert profile.profile_url == build_twitter_profile_url("elonmusk")
    assert profile.display_name == "Elon Musk"
    assert profile.description == "Occupy Mars"
    assert profile.followers_count == 100
    assert profile.following_count == 50
    assert profile.tweets_count == 25
    assert profile.pinned_post_id == "12345"
    assert profile.website_url == "https://www.tesla.com"
    assert profile.raw == raw_profile


def test_normalize_post_maps_metrics_media_and_links():
    raw_tweet = {
        "id_str": "987654321",
        "full_text": "New launch details https://t.co/demo",
        "created_at": "Wed Jan 18 10:42:51 +0000 2023",
        "favorite_count": 150,
        "reply_count": 25,
        "retweet_count": 10,
        "quote_count": 2,
        "ext_views": {"count": "9876"},
        "conversation_id_str": "987654321",
        "possibly_sensitive": False,
        "entities": {
            "urls": [{"expanded_url": "https://www.spacex.com/launches"}],
        },
        "extended_entities": {
            "media": [
                {
                    "type": "video",
                    "video_info": {
                        "variants": [
                            {"url": "https://video.example/low.mp4", "bitrate": 256000},
                            {"url": "https://video.example/high.mp4", "bitrate": 832000},
                        ]
                    },
                }
            ]
        },
    }

    post = normalize_post("elonmusk", raw_tweet, include_raw=True)

    assert post.id == "987654321"
    assert post.platform == "twitter"
    assert post.author_username == "elonmusk"
    assert post.type == "video"
    assert post.like_count == 150
    assert post.reply_count == 25
    assert post.repost_count == 10
    assert post.quote_count == 2
    assert post.view_count == 9876
    assert post.media_urls == ["https://video.example/high.mp4"]
    assert post.external_links == ["https://www.spacex.com/launches"]
    assert post.description == "New launch details https://t.co/demo"
    assert post.raw == raw_tweet
