"""
Client HTTP bas niveau pour les endpoints web publics Twitter / X.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.core.exceptions import (
    ApiError,
    ApiPermissionError,
    ApiRateLimitError,
    EmptyResponseError,
    InvalidResponseError,
    ProtectedProfileError,
    UserNotFoundError,
)
from utils.http import RequestsHttpClient


_API_BASE_URLS = ("https://api.twitter.com/1.1", "https://api.x.com/1.1")
_GRAPHQL_BASE_URL = "https://x.com/i/api/graphql"
_WEB_BASE_URL = "https://twitter.com"
_DISCOVERY_PROFILE_URL = "https://x.com/OpenAI"
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_PUBLIC_BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"  # pragma: allowlist secret
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"  # pragma: allowlist secret
)


@dataclass(frozen=True)
class GraphQLOperation:
    query_id: str
    features: dict[str, bool]
    field_toggles: dict[str, bool]


_KNOWN_GRAPHQL_OPERATIONS: dict[str, GraphQLOperation] = {
    "UserByScreenName": GraphQLOperation(
        query_id="IGgvgiOx4QZndDHuD3x9TQ",
        features={
            "hidden_profile_subscriptions_enabled": True,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "responsive_web_profile_redirect_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "verified_phone_label_enabled": True,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
        },
        field_toggles={
            "withPayments": True,
            "withAuxiliaryUserLabels": True,
        },
    ),
    "UserTweets": GraphQLOperation(
        query_id="6fWQaBPK51aGyC_VC7t9GQ",
        features={
            "rweb_video_screen_enabled": True,
            "rweb_cashtags_enabled": True,
            "profile_label_improvements_pcf_label_in_post_enabled": True,
            "responsive_web_profile_redirect_enabled": True,
            "rweb_tipjar_consumption_enabled": True,
            "verified_phone_label_enabled": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": True,
            "premium_content_api_read_enabled": True,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "responsive_web_grok_analyze_button_fetch_trends_enabled": True,
            "responsive_web_grok_analyze_post_followups_enabled": True,
            "responsive_web_jetfuel_frame": True,
            "responsive_web_grok_share_attachment_enabled": True,
            "responsive_web_grok_annotations_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "content_disclosure_indicator_enabled": True,
            "content_disclosure_ai_generated_indicator_enabled": True,
            "responsive_web_grok_show_grok_translated_post": True,
            "responsive_web_grok_analysis_button_from_backend": True,
            "post_ctas_fetch_enabled": True,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_grok_image_annotation_enabled": True,
            "responsive_web_grok_imagine_annotation_enabled": True,
            "responsive_web_grok_community_note_auto_translation_is_enabled": True,
            "responsive_web_enhance_cards_enabled": True,
        },
        field_toggles={
            "withPayments": True,
            "withAuxiliaryUserLabels": True,
            "withArticleRichContentState": True,
            "withArticlePlainText": True,
            "withArticleSummaryText": True,
            "withArticleVoiceOver": True,
            "withGrokAnalyze": True,
            "withDisallowedReplyControls": True,
        },
    ),
}


class TwitterApiClient:
    """Client pour les endpoints invite / web publics de Twitter/X."""

    def __init__(self, http_client: RequestsHttpClient | None = None) -> None:
        self._http = http_client or RequestsHttpClient(user_agent=_BROWSER_USER_AGENT)
        self._guest_token: str | None = None
        self._operation_cache: dict[str, GraphQLOperation] = {}

        self._http.session.headers.update(
            {
                "Authorization": f"Bearer {_PUBLIC_BEARER_TOKEN}",
                "Origin": _WEB_BASE_URL,
                "Referer": f"{_WEB_BASE_URL}/",
                "User-Agent": _BROWSER_USER_AGENT,
                "x-twitter-active-user": "yes",
                "x-twitter-client-language": "en",
            }
        )

    def close(self) -> None:
        self._http.close()

    def fetch_user(self, username: str) -> dict[str, Any]:
        payload = self._fetch_graphql(
            "UserByScreenName",
            variables={
                "screen_name": username,
                "withSafetyModeUserFields": True,
            },
        )
        result = (((payload.get("data") or {}).get("user") or {}).get("result"))
        return self._adapt_graphql_user_result(username, result)

    def fetch_user_timeline(
        self,
        *,
        username: str | None = None,
        user_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if not username and not user_id:
            raise InvalidResponseError("Twitter timeline: username ou user_id requis.")

        if not user_id:
            user = self.fetch_user(username or "")
            user_id = str(user.get("id_str") or "").strip()
            if not user_id:
                raise InvalidResponseError("Twitter/X n'a pas retourne d'user_id.")

        payload = self._fetch_graphql(
            "UserTweets",
            variables={
                "userId": user_id,
                "count": min(max(limit + 8, 20), 200),
                "includePromotedContent": False,
                "withQuickPromoteEligibilityTweetFields": False,
                "withVoice": True,
                "withV2Timeline": True,
            },
        )
        return self._extract_graphql_timeline_tweets(payload, limit)

    def _ensure_guest_token(self) -> None:
        if self._guest_token:
            return

        last_error: Exception | None = None

        for base_url in _API_BASE_URLS:
            try:
                response = self._http.request(
                    "POST",
                    f"{base_url}/guest/activate.json",
                    params={"skip_gt_rate_limit": "true"},
                    data={},
                )

                if response.status_code == 429:
                    raise ApiRateLimitError("Rate limit Twitter/X atteint lors de l'activation invite.")
                if response.status_code >= 400:
                    raise ApiPermissionError(
                        f"Activation invite Twitter/X refusee ({response.status_code})."
                    )

                payload = response.json()
                guest_token = payload.get("guest_token") if isinstance(payload, dict) else None
                if not guest_token:
                    raise EmptyResponseError("Twitter/X n'a pas retourne de guest_token.")

                self._guest_token = str(guest_token)
                self._http.session.headers["x-guest-token"] = self._guest_token
                return
            except (ApiError, TypeError, ValueError) as exc:
                last_error = exc

        self._http.request("GET", f"{_WEB_BASE_URL}/")
        cookie_guest_token = self._http.session.cookies.get("gt")
        if cookie_guest_token:
            self._guest_token = str(cookie_guest_token)
            self._http.session.headers["x-guest-token"] = self._guest_token
            return

        raise ApiPermissionError(
            f"Impossible d'obtenir un guest token Twitter/X: {last_error or 'erreur inconnue'}"
        )

    def _fetch_graphql(self, operation_name: str, *, variables: dict[str, Any]) -> dict[str, Any]:
        self._ensure_guest_token()
        operation = self._get_graphql_operation(operation_name)
        response = self._http.request(
            "GET",
            f"{_GRAPHQL_BASE_URL}/{operation.query_id}/{operation_name}",
            params={
                "variables": json.dumps(variables, separators=(",", ":")),
                "features": json.dumps(operation.features, separators=(",", ":")),
                "fieldToggles": json.dumps(operation.field_toggles, separators=(",", ":")),
            },
        )
        payload = self._parse_response_payload(response)
        if not isinstance(payload, dict):
            raise InvalidResponseError(f"GraphQL Twitter/X {operation_name}: reponse non objet.")
        return payload

    def _get_graphql_operation(self, operation_name: str) -> GraphQLOperation:
        if operation_name in self._operation_cache:
            return self._operation_cache[operation_name]

        operation = self._discover_graphql_operation(operation_name)
        if operation is None:
            operation = _KNOWN_GRAPHQL_OPERATIONS.get(operation_name)
        if operation is None:
            raise InvalidResponseError(f"Operation GraphQL Twitter/X introuvable: {operation_name}.")

        self._operation_cache[operation_name] = operation
        return operation

    def _discover_graphql_operation(self, operation_name: str) -> GraphQLOperation | None:
        web_http = RequestsHttpClient(user_agent=_BROWSER_USER_AGENT, max_retries=1)
        try:
            html_response = web_http.request("GET", _DISCOVERY_PROFILE_URL)
            asset_urls = sorted(
                set(
                    re.findall(
                        r"https://abs\.twimg\.com/responsive-web/client-web/[^\"']+?\.js",
                        html_response.text,
                    )
                )
            )

            for asset_url in asset_urls:
                js_response = web_http.request("GET", asset_url)
                operation = self._extract_operation_from_js(js_response.text, operation_name)
                if operation is not None:
                    return operation
        except (ApiError, TypeError, ValueError):
            return None
        finally:
            web_http.close()

        return None

    @staticmethod
    def _extract_operation_from_js(js_text: str, operation_name: str) -> GraphQLOperation | None:
        marker = f'operationName:"{operation_name}"'
        idx = js_text.find(marker)
        if idx == -1:
            return None

        start = js_text.rfind('queryId:"', 0, idx)
        end = js_text.find("}}}", idx)
        if start == -1 or end == -1:
            return None

        snippet = js_text[start : end + 3]
        query_id_match = re.search(r'queryId:"([^"]+)"', snippet)
        if not query_id_match:
            return None

        feature_match = re.search(r"featureSwitches:\[([^\]]*)\]", snippet)
        field_match = re.search(r"fieldToggles:\[([^\]]*)\]", snippet)

        features = {
            item: True
            for item in re.findall(r'"([^"]+)"', feature_match.group(1) if feature_match else "")
        }
        field_toggles = {
            item: True
            for item in re.findall(r'"([^"]+)"', field_match.group(1) if field_match else "")
        }

        return GraphQLOperation(
            query_id=query_id_match.group(1),
            features=features,
            field_toggles=field_toggles,
        )

    @staticmethod
    def _adapt_graphql_user_result(username: str, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise UserNotFoundError(f"Utilisateur Twitter/X introuvable: @{username}")

        typename = result.get("__typename")
        if typename and typename != "User":
            raise UserNotFoundError(f"Utilisateur Twitter/X indisponible: {typename}")

        legacy = dict(result.get("legacy") or {})
        core = result.get("core") or {}
        avatar = result.get("avatar") or {}
        privacy = result.get("privacy") or {}
        location = result.get("location")

        legacy["id_str"] = str(result.get("rest_id") or result.get("id") or legacy.get("id_str") or "")
        legacy["screen_name"] = core.get("screen_name") or legacy.get("screen_name") or username
        legacy["name"] = core.get("name") or legacy.get("name") or legacy["screen_name"]
        legacy["created_at"] = core.get("created_at") or legacy.get("created_at")
        legacy["profile_image_url_https"] = avatar.get("image_url") or legacy.get("profile_image_url_https")
        legacy["protected"] = privacy.get("protected") if isinstance(privacy, dict) else legacy.get("protected")
        legacy["verified"] = result.get("is_blue_verified") if isinstance(result.get("is_blue_verified"), bool) else legacy.get("verified")

        if isinstance(location, dict):
            legacy["location"] = location.get("location") or location.get("name") or legacy.get("location")
        elif location:
            legacy["location"] = location

        if not legacy.get("description"):
            profile_bio = result.get("profile_bio") or {}
            legacy["description"] = profile_bio.get("description")

        return legacy

    def _extract_graphql_timeline_tweets(
        self,
        payload: dict[str, Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        timeline = (
            (((payload.get("data") or {}).get("user") or {}).get("result") or {})
            .get("timeline", {})
            .get("timeline", {})
        )
        instructions = timeline.get("instructions")
        if not isinstance(instructions, list):
            raise InvalidResponseError("Timeline GraphQL Twitter/X inattendue.")

        regular: list[dict[str, Any]] = []
        pinned: list[dict[str, Any]] = []
        seen: set[str] = set()

        for tweet_result, is_pinned in self._iter_timeline_tweet_results(instructions):
            tweet = self._adapt_graphql_tweet_result(tweet_result)
            if not tweet:
                continue

            tweet_id = str(tweet.get("id_str") or "")
            if tweet_id and tweet_id in seen:
                continue
            if tweet_id:
                seen.add(tweet_id)

            if is_pinned:
                pinned.append(tweet)
            else:
                regular.append(tweet)

            if len(regular) >= limit:
                break

        result = regular[:limit]
        if len(result) < limit:
            result.extend(pinned[: limit - len(result)])
        return result[:limit]

    def _iter_timeline_tweet_results(
        self,
        instructions: list[dict[str, Any]],
    ):
        for instruction in instructions:
            if not isinstance(instruction, dict):
                continue
            entry = instruction.get("entry")
            if isinstance(entry, dict):
                yield from self._iter_tweet_results_from_entry(entry)
            entries = instruction.get("entries")
            if isinstance(entries, list):
                for item in entries:
                    if isinstance(item, dict):
                        yield from self._iter_tweet_results_from_entry(item)

    def _iter_tweet_results_from_entry(self, entry: dict[str, Any]):
        content = entry.get("content") or {}
        item_content = content.get("itemContent") or {}
        tweet_result = ((item_content.get("tweet_results") or {}).get("result"))
        if isinstance(tweet_result, dict):
            yield tweet_result, self._is_pinned_content(content)

        items = content.get("items")
        if isinstance(items, list):
            for item in items:
                item_wrapper = item.get("item") or {}
                item_content = item_wrapper.get("itemContent") or {}
                tweet_result = ((item_content.get("tweet_results") or {}).get("result"))
                if isinstance(tweet_result, dict):
                    yield tweet_result, self._is_pinned_content(item_wrapper)

    @staticmethod
    def _is_pinned_content(content: dict[str, Any]) -> bool:
        client_info = content.get("clientEventInfo") or {}
        component = str(client_info.get("component") or "").lower()
        if "pinned" in component:
            return True

        item_content = content.get("itemContent") or {}
        social_context = item_content.get("socialContext") or {}
        return "pinned" in str(social_context.get("text") or "").lower()

    def _adapt_graphql_tweet_result(self, tweet_result: Any) -> dict[str, Any] | None:
        if not isinstance(tweet_result, dict):
            return None
        if tweet_result.get("__typename") == "TweetWithVisibilityResults":
            tweet_result = tweet_result.get("tweet")
        if not isinstance(tweet_result, dict):
            return None

        legacy = dict(tweet_result.get("legacy") or {})
        if not legacy:
            return None

        legacy["id_str"] = str(tweet_result.get("rest_id") or legacy.get("id_str") or "")
        legacy["views"] = tweet_result.get("views") or legacy.get("views")

        user_result = (((tweet_result.get("core") or {}).get("user_results") or {}).get("result"))
        if isinstance(user_result, dict):
            legacy["user"] = self._adapt_graphql_user_result(
                legacy.get("user_id_str") or "",
                user_result,
            )

        quoted_result = (((tweet_result.get("quoted_status_result") or {}).get("result")))
        if isinstance(quoted_result, dict):
            quoted_tweet = self._adapt_graphql_tweet_result(quoted_result)
            if quoted_tweet:
                legacy["quoted_status"] = quoted_tweet

        return legacy

    def _parse_response_payload(self, response) -> Any:
        if response.status_code == 404:
            raise UserNotFoundError("Utilisateur Twitter/X introuvable.")
        if response.status_code == 429:
            self._guest_token = None
            self._http.session.headers.pop("x-guest-token", None)
            raise ApiRateLimitError("Rate limit Twitter/X atteint.")
        if response.status_code in {401, 403}:
            raise ApiPermissionError(f"Acces Twitter/X refuse ({response.status_code}).")
        if response.status_code >= 400:
            raise ApiError(
                f"Erreur HTTP Twitter/X {response.status_code}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise InvalidResponseError("La reponse Twitter/X n'est pas un JSON valide.") from exc

        if isinstance(payload, dict) and payload.get("errors"):
            self._raise_api_errors(payload["errors"])

        if payload in ({}, [], None):
            raise EmptyResponseError("La reponse Twitter/X est vide.")

        return payload

    @staticmethod
    def _raise_api_errors(errors: Any) -> None:
        if not isinstance(errors, list) or not errors:
            raise InvalidResponseError("Twitter/X a retourne des erreurs illisibles.")

        error = errors[0] if isinstance(errors[0], dict) else {"message": str(errors[0])}
        code = error.get("code")
        message = str(error.get("message") or "Erreur Twitter/X inconnue.")
        lowered = message.lower()

        if code in {34, 50} or "not found" in lowered:
            raise UserNotFoundError(message)
        if code == 63 or "suspended" in lowered:
            raise UserNotFoundError(message)
        if code in {88, 226} or "rate limit" in lowered or "too many requests" in lowered:
            raise ApiRateLimitError(message)
        if code == 179 or "protected" in lowered or "authorized" in lowered:
            raise ProtectedProfileError(message)

        raise ApiError(message)
