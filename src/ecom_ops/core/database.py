from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    agent TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    input_path TEXT,
    output_path TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_key TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL,
    risk_level TEXT,
    priority_level TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS automation_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    system_name TEXT NOT NULL,
    action TEXT NOT NULL,
    selector TEXT,
    screenshot_path TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tiktok_oauth_states (
    state TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    used_at TEXT
);

CREATE TABLE IF NOT EXISTS tiktok_accounts (
    open_id TEXT PRIMARY KEY,
    union_id TEXT,
    display_name TEXT,
    avatar_url TEXT,
    scope TEXT NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    access_expires_at TEXT NOT NULL,
    refresh_expires_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    connected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tiktok_videos (
    video_id TEXT PRIMARY KEY,
    open_id TEXT NOT NULL,
    title TEXT,
    video_description TEXT,
    create_time INTEGER,
    cover_image_url TEXT,
    share_url TEXT,
    duration INTEGER,
    view_count INTEGER NOT NULL DEFAULT 0,
    like_count INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    share_count INTEGER NOT NULL DEFAULT 0,
    last_synced_at TEXT NOT NULL,
    FOREIGN KEY(open_id) REFERENCES tiktok_accounts(open_id)
);

CREATE INDEX IF NOT EXISTS idx_tiktok_videos_account
ON tiktok_videos(open_id, create_time DESC);

CREATE TABLE IF NOT EXISTS tiktok_video_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    open_id TEXT NOT NULL,
    collected_at TEXT NOT NULL,
    view_count INTEGER NOT NULL DEFAULT 0,
    like_count INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    share_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(video_id, collected_at),
    FOREIGN KEY(video_id) REFERENCES tiktok_videos(video_id),
    FOREIGN KEY(open_id) REFERENCES tiktok_accounts(open_id)
);

CREATE INDEX IF NOT EXISTS idx_tiktok_metrics_account_time
ON tiktok_video_metrics(open_id, collected_at DESC);

CREATE TABLE IF NOT EXISTS tiktok_sync_runs (
    id TEXT PRIMARY KEY,
    open_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    videos_synced INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    FOREIGN KEY(open_id) REFERENCES tiktok_accounts(open_id)
);

CREATE TABLE IF NOT EXISTS tiktok_ad_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    advertiser_id TEXT NOT NULL,
    stat_date TEXT NOT NULL,
    data_level TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_name TEXT,
    spend REAL NOT NULL DEFAULT 0,
    impressions INTEGER NOT NULL DEFAULT 0,
    clicks INTEGER NOT NULL DEFAULT 0,
    ctr REAL NOT NULL DEFAULT 0,
    cpc REAL NOT NULL DEFAULT 0,
    conversions REAL NOT NULL DEFAULT 0,
    cost_per_conversion REAL NOT NULL DEFAULT 0,
    video_play_actions INTEGER NOT NULL DEFAULT 0,
    video_watched_2s INTEGER NOT NULL DEFAULT 0,
    video_watched_6s INTEGER NOT NULL DEFAULT 0,
    video_views_p100 INTEGER NOT NULL DEFAULT 0,
    purchases REAL NOT NULL DEFAULT 0,
    purchase_roas REAL NOT NULL DEFAULT 0,
    raw_metrics TEXT NOT NULL DEFAULT '{}',
    collected_at TEXT NOT NULL,
    UNIQUE(advertiser_id, stat_date, data_level, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_tiktok_ads_account_date
ON tiktok_ad_reports(advertiser_id, stat_date DESC, data_level);

CREATE TABLE IF NOT EXISTS tiktok_ad_sync_runs (
    id TEXT PRIMARY KEY,
    advertiser_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    rows_synced INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS mixer_imports (
    id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    ad_source_path TEXT,
    status TEXT NOT NULL,
    row_count INTEGER NOT NULL DEFAULT 0,
    product_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS mixer_products (
    product_id TEXT PRIMARY KEY,
    product_name TEXT,
    material_count INTEGER NOT NULL DEFAULT 0,
    taxonomy_status TEXT NOT NULL DEFAULT 'missing',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mixer_videos (
    video_id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    platform_video_id TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    title TEXT,
    creator_name TEXT,
    published_at TEXT,
    authorization_status TEXT NOT NULL DEFAULT 'authorized',
    latest_score REAL NOT NULL DEFAULT 0,
    latest_tier TEXT NOT NULL DEFAULT 'C',
    low_sample INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(product_id) REFERENCES mixer_products(product_id)
);

CREATE INDEX IF NOT EXISTS idx_mixer_videos_product_score
ON mixer_videos(product_id, latest_score DESC);

CREATE TABLE IF NOT EXISTS mixer_metric_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    quality_score REAL NOT NULL,
    tier TEXT NOT NULL,
    evidence_confidence REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(import_id, video_id, product_id),
    FOREIGN KEY(import_id) REFERENCES mixer_imports(id),
    FOREIGN KEY(video_id) REFERENCES mixer_videos(video_id)
);

CREATE TABLE IF NOT EXISTS mixer_assets (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    path TEXT NOT NULL,
    source TEXT NOT NULL,
    sha256 TEXT,
    perceptual_hash TEXT,
    audio_fingerprint TEXT,
    duration REAL,
    width INTEGER,
    height INTEGER,
    status TEXT NOT NULL,
    adopted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(video_id, path),
    FOREIGN KEY(video_id) REFERENCES mixer_videos(video_id)
);

CREATE TABLE IF NOT EXISTS mixer_segments (
    id TEXT PRIMARY KEY,
    asset_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    start_seconds REAL NOT NULL,
    end_seconds REAL NOT NULL,
    safe_start_seconds REAL NOT NULL,
    safe_end_seconds REAL NOT NULL,
    stage TEXT NOT NULL,
    confidence REAL NOT NULL,
    analysis_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(asset_id) REFERENCES mixer_assets(id)
);

CREATE INDEX IF NOT EXISTS idx_mixer_segments_product_stage
ON mixer_segments(product_id, stage, confidence DESC);

CREATE TABLE IF NOT EXISTS mixer_segment_versions (
    id TEXT PRIMARY KEY,
    segment_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    start_seconds REAL NOT NULL,
    end_seconds REAL NOT NULL,
    safe_start_seconds REAL NOT NULL,
    safe_end_seconds REAL NOT NULL,
    stage TEXT NOT NULL,
    confidence REAL NOT NULL,
    analysis_json TEXT NOT NULL,
    analysis_hash TEXT NOT NULL,
    source TEXT NOT NULL,
    is_preferred INTEGER NOT NULL DEFAULT 1,
    human_verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE(segment_id, version),
    FOREIGN KEY(segment_id) REFERENCES mixer_segments(id)
);

CREATE INDEX IF NOT EXISTS idx_mixer_segment_versions_current
ON mixer_segment_versions(segment_id, is_preferred, version DESC);

CREATE TABLE IF NOT EXISTS mixer_tags (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL DEFAULT '',
    code TEXT NOT NULL,
    name_cn TEXT NOT NULL,
    category TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#607d8b',
    created_at TEXT NOT NULL,
    UNIQUE(product_id, code)
);

CREATE INDEX IF NOT EXISTS idx_mixer_tags_product_category
ON mixer_tags(product_id, category, name_cn);

CREATE TABLE IF NOT EXISTS mixer_segment_tags (
    segment_version_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1,
    source TEXT NOT NULL,
    accepted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    PRIMARY KEY(segment_version_id, tag_id),
    FOREIGN KEY(segment_version_id) REFERENCES mixer_segment_versions(id),
    FOREIGN KEY(tag_id) REFERENCES mixer_tags(id)
);

CREATE TABLE IF NOT EXISTS mixer_taxonomies (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    status TEXT NOT NULL,
    definition_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    approved_at TEXT,
    UNIQUE(product_id, version)
);

CREATE TABLE IF NOT EXISTS mixer_projects (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL,
    status TEXT NOT NULL,
    target_duration REAL NOT NULL,
    language TEXT NOT NULL DEFAULT 'ms',
    audio_mode TEXT NOT NULL DEFAULT 'voiceover',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mixer_timeline_versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    source TEXT NOT NULL,
    timeline_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, version),
    FOREIGN KEY(project_id) REFERENCES mixer_projects(id)
);

CREATE TABLE IF NOT EXISTS mixer_timeline_clips (
    timeline_version_id TEXT NOT NULL,
    clip_order INTEGER NOT NULL,
    clip_id TEXT NOT NULL,
    segment_id TEXT NOT NULL,
    segment_version_id TEXT,
    product_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_start REAL NOT NULL,
    source_end REAL NOT NULL,
    timeline_start REAL NOT NULL,
    timeline_end REAL NOT NULL,
    stage TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(timeline_version_id, clip_order),
    FOREIGN KEY(timeline_version_id) REFERENCES mixer_timeline_versions(id),
    FOREIGN KEY(segment_id) REFERENCES mixer_segments(id),
    FOREIGN KEY(segment_version_id) REFERENCES mixer_segment_versions(id)
);

CREATE INDEX IF NOT EXISTS idx_mixer_timeline_clips_segment
ON mixer_timeline_clips(segment_id, timeline_version_id);

CREATE TABLE IF NOT EXISTS mixer_jobs (
    id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    result_json TEXT,
    error_message TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    lease_until TEXT,
    heartbeat_at TEXT,
    estimated_cost REAL NOT NULL DEFAULT 0,
    actual_cost REAL NOT NULL DEFAULT 0,
    requires_confirmation INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mixer_jobs_status_created
ON mixer_jobs(status, created_at);

CREATE TABLE IF NOT EXISTS mixer_reviews (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    render_path TEXT,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES mixer_projects(id)
);

CREATE TABLE IF NOT EXISTS mixer_ai_traces (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    product_id TEXT NOT NULL,
    video_id TEXT,
    operation TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT NOT NULL,
    estimated_cost REAL NOT NULL DEFAULT 0,
    actual_cost REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mixer_renders (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL,
    original_audio_path TEXT,
    voiceover_path TEXT,
    subtitle_path TEXT,
    cover_path TEXT,
    manifest_path TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(project_id) REFERENCES mixer_projects(id)
);
"""


@contextmanager
def connect(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    with connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        oauth_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(tiktok_oauth_states)").fetchall()
        }
        if "code_verifier" not in oauth_columns:
            conn.execute(
                "ALTER TABLE tiktok_oauth_states ADD COLUMN code_verifier TEXT NOT NULL DEFAULT ''"
            )
        mixer_video_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(mixer_videos)").fetchall()
        }
        if "platform_video_id" not in mixer_video_columns:
            conn.execute(
                "ALTER TABLE mixer_videos ADD COLUMN platform_video_id TEXT NOT NULL DEFAULT ''"
            )
        conn.execute(
            """UPDATE mixer_videos SET platform_video_id=video_id
               WHERE platform_video_id=''"""
        )
        conn.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_mixer_videos_product_platform
               ON mixer_videos(product_id, platform_video_id)"""
        )
        segment_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(mixer_segments)").fetchall()
        }
        segment_migrations = {
            "origin": "TEXT NOT NULL DEFAULT 'ai'",
            "parent_segment_id": "TEXT",
            "active_version_id": "TEXT",
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "human_verified": "INTEGER NOT NULL DEFAULT 0",
            "updated_at": "TEXT",
        }
        for column, definition in segment_migrations.items():
            if column not in segment_columns:
                conn.execute(f"ALTER TABLE mixer_segments ADD COLUMN {column} {definition}")
        conn.execute(
            """UPDATE mixer_segments SET updated_at=COALESCE(updated_at, created_at)
               WHERE updated_at IS NULL"""
        )
        try:
            conn.execute(
                """CREATE VIRTUAL TABLE IF NOT EXISTS mixer_segment_search USING fts5(
                       segment_version_id UNINDEXED,
                       visual_summary,
                       transcript,
                       on_screen_text,
                       selling_points,
                       tags
                   )"""
            )
        except sqlite3.OperationalError:
            # LIKE-based search remains available when Python was built without FTS5.
            pass
        mixer_asset_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(mixer_assets)").fetchall()
        }
        if "audio_fingerprint" not in mixer_asset_columns:
            conn.execute("ALTER TABLE mixer_assets ADD COLUMN audio_fingerprint TEXT")


def create_run(db_path: Path, agent: str, input_path: str | Path | None = None) -> str:
    init_db(db_path)
    run_id = uuid4().hex
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO runs (id, agent, status, started_at, input_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, agent, "running", datetime.now().isoformat(timespec="seconds"), str(input_path or "")),
        )
    return run_id


def finish_run(db_path: Path, run_id: str, status: str, output_path: str | Path | None = None, notes: str = "") -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE runs
            SET status = ?, ended_at = ?, output_path = ?, notes = ?
            WHERE id = ?
            """,
            (status, datetime.now().isoformat(timespec="seconds"), str(output_path or ""), notes, run_id),
        )


def log_decision(
    db_path: Path,
    run_id: str,
    subject_type: str,
    subject_key: str,
    decision: str,
    reason: str,
    risk_level: str = "",
    priority_level: str = "",
) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO decisions
                (run_id, subject_type, subject_key, decision, reason, risk_level, priority_level, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                subject_type,
                subject_key,
                decision,
                reason,
                risk_level,
                priority_level,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )


def log_artifact(db_path: Path, run_id: str, artifact_type: str, path: str | Path) -> None:
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO artifacts (run_id, artifact_type, path, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, artifact_type, str(path), datetime.now().isoformat(timespec="seconds")),
        )


def log_automation_step(
    db_path: Path,
    system_name: str,
    action: str,
    status: str,
    selector: str = "",
    screenshot_path: str | Path | None = None,
    run_id: str | None = None,
) -> None:
    init_db(db_path)
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO automation_steps
                (run_id, system_name, action, selector, screenshot_path, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                system_name,
                action,
                selector,
                str(screenshot_path or ""),
                status,
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
