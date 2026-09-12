from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import logging
from pathlib import Path
import secrets
from typing import Any
from uuid import uuid4

from ecom_ops.core.database import connect, init_db
from ecom_ops.core.settings import Settings, get_settings
from ecom_ops.integrations.tiktok import TikTokClient


logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="seconds")


@dataclass(frozen=True)
class SyncSummary:
    run_id: str
    open_id: str
    videos_synced: int
    collected_at: str


class TikTokRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        init_db(db_path)

    def create_oauth_state(self, state: str, code_verifier: str = "") -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tiktok_oauth_states (state, code_verifier, created_at)
                VALUES (?, ?, ?)
                """,
                (state, code_verifier, _iso()),
            )

    def consume_oauth_state(
        self, state: str, max_age_minutes: int = 10
    ) -> tuple[bool, str]:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT created_at, used_at, code_verifier
                FROM tiktok_oauth_states WHERE state = ?
                """,
                (state,),
            ).fetchone()
            if not row or row["used_at"]:
                return False, ""
            created_at = datetime.fromisoformat(row["created_at"])
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if _now() - created_at > timedelta(minutes=max_age_minutes):
                return False, ""
            conn.execute(
                "UPDATE tiktok_oauth_states SET used_at = ? WHERE state = ?", (_iso(), state)
            )
        return True, str(row["code_verifier"] or "")

    def save_account(self, token: dict[str, Any], profile: dict[str, Any]) -> str:
        now = _now()
        open_id = str(token["open_id"])
        access_expires_at = _iso(now + timedelta(seconds=int(token.get("expires_in", 86400))))
        refresh_expires_at = _iso(
            now + timedelta(seconds=int(token.get("refresh_expires_in", 31536000)))
        )
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tiktok_accounts (
                    open_id, union_id, display_name, avatar_url, scope, access_token,
                    refresh_token, access_expires_at, refresh_expires_at, status,
                    connected_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                ON CONFLICT(open_id) DO UPDATE SET
                    union_id = excluded.union_id,
                    display_name = excluded.display_name,
                    avatar_url = excluded.avatar_url,
                    scope = excluded.scope,
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    access_expires_at = excluded.access_expires_at,
                    refresh_expires_at = excluded.refresh_expires_at,
                    status = 'active',
                    updated_at = excluded.updated_at
                """,
                (
                    open_id,
                    profile.get("union_id", ""),
                    profile.get("display_name", ""),
                    profile.get("avatar_url", ""),
                    token.get("scope", ""),
                    token["access_token"],
                    token["refresh_token"],
                    access_expires_at,
                    refresh_expires_at,
                    _iso(now),
                    _iso(now),
                ),
            )
        return open_id

    def update_tokens(self, open_id: str, token: dict[str, Any]) -> None:
        now = _now()
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE tiktok_accounts SET
                    access_token = ?, refresh_token = ?, scope = ?,
                    access_expires_at = ?, refresh_expires_at = ?, updated_at = ?
                WHERE open_id = ?
                """,
                (
                    token["access_token"],
                    token["refresh_token"],
                    token.get("scope", ""),
                    _iso(now + timedelta(seconds=int(token.get("expires_in", 86400)))),
                    _iso(
                        now
                        + timedelta(seconds=int(token.get("refresh_expires_in", 31536000)))
                    ),
                    _iso(now),
                    open_id,
                ),
            )

    def get_account(self, open_id: str | None = None) -> dict[str, Any] | None:
        query = "SELECT * FROM tiktok_accounts WHERE status = 'active'"
        params: tuple[Any, ...] = ()
        if open_id:
            query += " AND open_id = ?"
            params = (open_id,)
        query += " ORDER BY connected_at LIMIT 1"
        with connect(self.db_path) as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def list_accounts(self) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT open_id, display_name, avatar_url, scope, status, connected_at, updated_at
                FROM tiktok_accounts ORDER BY connected_at
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def begin_sync(self, open_id: str) -> str:
        run_id = uuid4().hex
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tiktok_sync_runs (id, open_id, status, started_at)
                VALUES (?, ?, 'running', ?)
                """,
                (run_id, open_id, _iso()),
            )
        return run_id

    def finish_sync(
        self, run_id: str, status: str, videos_synced: int = 0, error_message: str = ""
    ) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE tiktok_sync_runs
                SET status = ?, ended_at = ?, videos_synced = ?, error_message = ?
                WHERE id = ?
                """,
                (status, _iso(), videos_synced, error_message[:1000], run_id),
            )

    def save_video_snapshot(
        self, open_id: str, video: dict[str, Any], collected_at: str
    ) -> None:
        values = {
            "view_count": int(video.get("view_count") or 0),
            "like_count": int(video.get("like_count") or 0),
            "comment_count": int(video.get("comment_count") or 0),
            "share_count": int(video.get("share_count") or 0),
        }
        video_id = str(video["id"])
        with connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO tiktok_videos (
                    video_id, open_id, title, video_description, create_time,
                    cover_image_url, share_url, duration, view_count, like_count,
                    comment_count, share_count, last_synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    title = excluded.title,
                    video_description = excluded.video_description,
                    cover_image_url = excluded.cover_image_url,
                    share_url = excluded.share_url,
                    duration = excluded.duration,
                    view_count = excluded.view_count,
                    like_count = excluded.like_count,
                    comment_count = excluded.comment_count,
                    share_count = excluded.share_count,
                    last_synced_at = excluded.last_synced_at
                """,
                (
                    video_id,
                    open_id,
                    video.get("title", ""),
                    video.get("video_description", ""),
                    int(video.get("create_time") or 0),
                    video.get("cover_image_url", ""),
                    video.get("share_url", ""),
                    int(video.get("duration") or 0),
                    values["view_count"],
                    values["like_count"],
                    values["comment_count"],
                    values["share_count"],
                    collected_at,
                ),
            )
            conn.execute(
                """
                INSERT INTO tiktok_video_metrics (
                    video_id, open_id, collected_at, view_count, like_count,
                    comment_count, share_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id, collected_at) DO UPDATE SET
                    view_count = excluded.view_count,
                    like_count = excluded.like_count,
                    comment_count = excluded.comment_count,
                    share_count = excluded.share_count
                """,
                (
                    video_id,
                    open_id,
                    collected_at,
                    values["view_count"],
                    values["like_count"],
                    values["comment_count"],
                    values["share_count"],
                ),
            )

    def overview(self, open_id: str) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            current = conn.execute(
                """
                SELECT COUNT(*) AS video_count,
                       COALESCE(SUM(view_count), 0) AS view_count,
                       COALESCE(SUM(like_count), 0) AS like_count,
                       COALESCE(SUM(comment_count), 0) AS comment_count,
                       COALESCE(SUM(share_count), 0) AS share_count,
                       MAX(last_synced_at) AS last_synced_at
                FROM tiktok_videos WHERE open_id = ?
                """,
                (open_id,),
            ).fetchone()
            snapshots = conn.execute(
                """
                SELECT collected_at, SUM(view_count) AS view_count,
                       SUM(like_count) AS like_count, SUM(comment_count) AS comment_count,
                       SUM(share_count) AS share_count
                FROM tiktok_video_metrics WHERE open_id = ?
                GROUP BY collected_at ORDER BY collected_at DESC LIMIT 2
                """,
                (open_id,),
            ).fetchall()
        result = dict(current)
        previous = dict(snapshots[1]) if len(snapshots) > 1 else {}
        latest = dict(snapshots[0]) if snapshots else {}
        for metric in ("view_count", "like_count", "comment_count", "share_count"):
            result[f"{metric}_delta"] = int(latest.get(metric, 0) or 0) - int(
                previous.get(metric, 0) or 0
            )
        return result

    def videos(self, open_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT video_id, title, video_description, create_time, share_url,
                       view_count, like_count, comment_count, share_count, last_synced_at,
                       CASE WHEN view_count > 0 THEN
                           ROUND(100.0 * (like_count + comment_count + share_count) / view_count, 2)
                       ELSE 0 END AS engagement_rate
                FROM tiktok_videos WHERE open_id = ?
                ORDER BY create_time DESC LIMIT ?
                """,
                (open_id, min(max(limit, 1), 500)),
            ).fetchall()
        return [dict(row) for row in rows]

    def timeseries(self, open_id: str, limit: int = 288) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT collected_at, SUM(view_count) AS view_count,
                       SUM(like_count) AS like_count, SUM(comment_count) AS comment_count,
                       SUM(share_count) AS share_count
                FROM tiktok_video_metrics WHERE open_id = ?
                GROUP BY collected_at ORDER BY collected_at DESC LIMIT ?
                """,
                (open_id, min(max(limit, 1), 2000)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def latest_sync(self, open_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT id, status, started_at, ended_at, videos_synced, error_message
                FROM tiktok_sync_runs WHERE open_id = ? ORDER BY started_at DESC LIMIT 1
                """,
                (open_id,),
            ).fetchone()
        return dict(row) if row else None


class TikTokMonitorService:
    def __init__(
        self,
        settings: Settings | None = None,
        client: TikTokClient | None = None,
        repository: TikTokRepository | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.repository = repository or TikTokRepository(self.settings.sqlite_path)
        self.client = client or TikTokClient(
            client_key=self.settings.tiktok_client_key,
            client_secret=self.settings.tiktok_client_secret,
            redirect_uri=self.settings.tiktok_redirect_uri,
            scopes=self.settings.tiktok_scopes,
            timeout=self.settings.tiktok_request_timeout_seconds,
        )

    def create_authorization_url(self) -> str:
        self._require_config()
        state = secrets.token_urlsafe(32)
        code_verifier = ""
        code_challenge = ""
        if self.settings.tiktok_login_platform == "desktop":
            code_verifier = secrets.token_urlsafe(64)
            code_challenge = hashlib.sha256(code_verifier.encode("utf-8")).hexdigest()
        self.repository.create_oauth_state(state, code_verifier)
        return self.client.authorization_url(state, code_challenge)

    def complete_authorization(self, code: str, state: str) -> str:
        self._require_config()
        state_valid, code_verifier = self.repository.consume_oauth_state(state)
        if not state_valid:
            raise ValueError("OAuth state is invalid, expired, or already used.")
        token = self.client.exchange_code(code, code_verifier)
        profile = self.client.get_user(token["access_token"])
        return self.repository.save_account(token, profile)

    def sync(self, open_id: str | None = None) -> SyncSummary:
        self._require_config()
        account = self.repository.get_account(open_id)
        if not account:
            raise ValueError("No active TikTok account is connected.")

        run_id = self.repository.begin_sync(account["open_id"])
        collected_at = _iso()
        synced = 0
        try:
            access_token = self._valid_access_token(account)
            cursor: int | None = None
            for _ in range(self.settings.tiktok_max_pages_per_sync):
                page = self.client.list_videos(access_token, cursor=cursor, max_count=20)
                videos = page.get("videos", [])
                for video in videos:
                    self.repository.save_video_snapshot(account["open_id"], video, collected_at)
                    synced += 1
                if not page.get("has_more") or not videos:
                    break
                cursor = int(page["cursor"])
            self.repository.finish_sync(run_id, "completed", synced)
            logger.info("TikTok sync completed: account=%s videos=%s", account["open_id"], synced)
            return SyncSummary(run_id, account["open_id"], synced, collected_at)
        except Exception as exc:
            self.repository.finish_sync(run_id, "failed", synced, str(exc))
            logger.exception("TikTok sync failed for account %s", account["open_id"])
            raise

    def sync_all(self) -> list[SyncSummary]:
        return [
            self.sync(account["open_id"])
            for account in self.repository.list_accounts()
            if account["status"] == "active"
        ]

    def _valid_access_token(self, account: dict[str, Any]) -> str:
        expires_at = datetime.fromisoformat(account["access_expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at - _now() > timedelta(minutes=5):
            return str(account["access_token"])
        token = self.client.refresh_access_token(account["refresh_token"])
        self.repository.update_tokens(account["open_id"], token)
        return str(token["access_token"])

    def _require_config(self) -> None:
        if not self.settings.tiktok_configured:
            raise ValueError(
                "TikTok is not configured. Set TIKTOK_CLIENT_KEY, "
                "TIKTOK_CLIENT_SECRET and TIKTOK_REDIRECT_URI in .env."
            )
        if self.settings.tiktok_login_platform not in {"desktop", "web"}:
            raise ValueError("TIKTOK_LOGIN_PLATFORM must be 'desktop' or 'web'.")
