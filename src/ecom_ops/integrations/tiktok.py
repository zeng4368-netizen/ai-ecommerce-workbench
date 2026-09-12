from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
USER_INFO_URL = "https://open.tiktokapis.com/v2/user/info/"
VIDEO_LIST_URL = "https://open.tiktokapis.com/v2/video/list/"

VIDEO_FIELDS = (
    "id,title,video_description,create_time,cover_image_url,share_url,duration,"
    "view_count,like_count,comment_count,share_count"
)

Transport = Callable[[str, str, dict[str, str], bytes | None, int], dict[str, Any]]


class TikTokAPIError(RuntimeError):
    """Raised when TikTok returns an API or transport error."""


def _default_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None,
    timeout: int,
) -> dict[str, Any]:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed trusted API URLs
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TikTokAPIError(f"TikTok HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise TikTokAPIError(f"TikTok connection failed: {exc.reason}") from exc

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TikTokAPIError("TikTok returned a non-JSON response.") from exc


class TikTokClient:
    def __init__(
        self,
        client_key: str,
        client_secret: str,
        redirect_uri: str,
        scopes: str = "user.info.basic,video.list",
        timeout: int = 20,
        transport: Transport | None = None,
    ) -> None:
        self.client_key = client_key
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.timeout = timeout
        self.transport = transport or _default_transport

    def authorization_url(self, state: str, code_challenge: str = "") -> str:
        parameters = {
            "client_key": self.client_key,
            "response_type": "code",
            "scope": self.scopes,
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        if code_challenge:
            parameters["code_challenge"] = code_challenge
            parameters["code_challenge_method"] = "S256"
        query = urlencode(parameters)
        return f"{AUTH_URL}?{query}"

    def exchange_code(self, code: str, code_verifier: str = "") -> dict[str, Any]:
        values = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
        }
        if code_verifier:
            values["code_verifier"] = code_verifier
        return self._form_post(TOKEN_URL, values)

    def refresh_access_token(self, refresh_token: str) -> dict[str, Any]:
        return self._form_post(
            TOKEN_URL,
            {
                "client_key": self.client_key,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )

    def get_user(self, access_token: str) -> dict[str, Any]:
        fields = "open_id,union_id,avatar_url,display_name"
        payload = self._request(
            "GET",
            f"{USER_INFO_URL}?{urlencode({'fields': fields})}",
            access_token=access_token,
        )
        return payload.get("data", {}).get("user", {})

    def list_videos(
        self,
        access_token: str,
        cursor: int | None = None,
        max_count: int = 20,
    ) -> dict[str, Any]:
        body: dict[str, int] = {"max_count": min(max(max_count, 1), 20)}
        if cursor is not None:
            body["cursor"] = cursor
        payload = self._request(
            "POST",
            f"{VIDEO_LIST_URL}?{urlencode({'fields': VIDEO_FIELDS})}",
            access_token=access_token,
            json_body=body,
        )
        return payload.get("data", {})

    def _form_post(self, url: str, values: dict[str, str]) -> dict[str, Any]:
        payload = self.transport(
            "POST",
            url,
            {"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"},
            urlencode(values).encode("utf-8"),
            self.timeout,
        )
        self._raise_for_error(payload)
        return payload

    def _request(
        self,
        method: str,
        url: str,
        access_token: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(json_body).encode("utf-8") if json_body is not None else None
        headers = {"Authorization": f"Bearer {access_token}"}
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        payload = self.transport(method, url, headers, body, self.timeout)
        self._raise_for_error(payload)
        return payload

    @staticmethod
    def _raise_for_error(payload: dict[str, Any]) -> None:
        if payload.get("error") and isinstance(payload["error"], str):
            raise TikTokAPIError(
                f"{payload['error']}: {payload.get('error_description', 'Unknown OAuth error')}"
            )
        api_error = payload.get("error", {})
        if isinstance(api_error, dict) and api_error.get("code") not in {None, "ok"}:
            raise TikTokAPIError(
                f"{api_error.get('code')}: {api_error.get('message', 'Unknown API error')}"
            )
