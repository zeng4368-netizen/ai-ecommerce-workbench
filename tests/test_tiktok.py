from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ecom_ops.core.settings import Settings
from ecom_ops.integrations.tiktok import AUTH_URL, TikTokClient
from ecom_ops.services.tiktok_monitor import TikTokMonitorService, TikTokRepository


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        base_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
        output_dir=tmp_path / "output",
        screenshot_dir=tmp_path / "screenshots",
        log_dir=tmp_path / "logs",
        sqlite_path=tmp_path / "processed" / "test.sqlite3",
        selectors_path=tmp_path / "selectors.yaml",
        tiktok_client_key="client-key",
        tiktok_client_secret="client-secret",
        tiktok_redirect_uri="http://127.0.0.1:8000/tiktok/oauth/callback",
        tiktok_max_pages_per_sync=2,
    )


def _token(access_token: str = "access-1") -> dict:
    return {
        "open_id": "account-1",
        "scope": "user.info.basic,video.list",
        "access_token": access_token,
        "refresh_token": "refresh-1",
        "expires_in": 86400,
        "refresh_expires_in": 31536000,
    }


def test_authorization_url_contains_csrf_state_and_scopes():
    client = TikTokClient(
        "client-key",
        "client-secret",
        "http://127.0.0.1:8000/tiktok/oauth/callback",
    )

    url = client.authorization_url("random-state")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert url.startswith(AUTH_URL)
    assert query["state"] == ["random-state"]
    assert query["scope"] == ["user.info.basic,video.list"]
    assert query["response_type"] == ["code"]


def test_desktop_authorization_uses_pkce(tmp_path):
    settings = _settings(tmp_path)
    service = TikTokMonitorService(settings)

    url = service.create_authorization_url()
    query = parse_qs(urlparse(url).query)

    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) == 64


def test_repository_builds_overview_and_sync_delta(tmp_path):
    settings = _settings(tmp_path)
    repository = TikTokRepository(settings.sqlite_path)
    repository.save_account(_token(), {"display_name": "Shop Account"})
    repository.save_video_snapshot(
        "account-1",
        {"id": "video-1", "title": "A", "view_count": 100, "like_count": 10},
        "2026-08-04T01:00:00+00:00",
    )
    repository.save_video_snapshot(
        "account-1",
        {
            "id": "video-1",
            "title": "A",
            "view_count": 145,
            "like_count": 16,
            "comment_count": 3,
            "share_count": 2,
        },
        "2026-08-04T01:05:00+00:00",
    )

    overview = repository.overview("account-1")
    videos = repository.videos("account-1")

    assert overview["video_count"] == 1
    assert overview["view_count"] == 145
    assert overview["view_count_delta"] == 45
    assert overview["like_count_delta"] == 6
    assert videos[0]["engagement_rate"] == 14.48


class FakeTikTokClient:
    def __init__(self) -> None:
        self.calls = 0

    def authorization_url(self, state: str) -> str:
        return f"https://example.test/auth?state={state}"

    def refresh_access_token(self, refresh_token: str) -> dict:
        return _token("refreshed-access")

    def list_videos(self, access_token: str, cursor=None, max_count: int = 20) -> dict:
        assert access_token in {"access-1", "refreshed-access"}
        self.calls += 1
        if self.calls == 1:
            return {
                "videos": [{"id": "video-1", "view_count": 123, "like_count": 9}],
                "has_more": True,
                "cursor": 123456,
            }
        return {
            "videos": [{"id": "video-2", "view_count": 50, "comment_count": 4}],
            "has_more": False,
        }


def test_service_syncs_paginated_video_metrics(tmp_path):
    settings = _settings(tmp_path)
    repository = TikTokRepository(settings.sqlite_path)
    token = _token()
    token["expires_in"] = int(timedelta(days=1).total_seconds())
    repository.save_account(token, {"display_name": "Shop Account"})
    client = FakeTikTokClient()
    service = TikTokMonitorService(settings, client=client, repository=repository)  # type: ignore[arg-type]

    summary = service.sync("account-1")

    assert summary.videos_synced == 2
    assert client.calls == 2
    assert repository.overview("account-1")["view_count"] == 173
    assert repository.latest_sync("account-1")["status"] == "completed"


def test_service_refreshes_near_expiry_token(tmp_path):
    settings = _settings(tmp_path)
    repository = TikTokRepository(settings.sqlite_path)
    repository.save_account(_token(), {"display_name": "Shop Account"})
    from ecom_ops.core.database import connect

    with connect(repository.db_path) as conn:
        conn.execute(
            "UPDATE tiktok_accounts SET access_expires_at = ? WHERE open_id = ?",
            ((datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat(), "account-1"),
        )
    client = FakeTikTokClient()
    service = TikTokMonitorService(settings, client=client, repository=repository)  # type: ignore[arg-type]

    service.sync("account-1")

    account = repository.get_account("account-1")
    assert account["access_token"] == "refreshed-access"
