"""SQLite persistence for the automatic video mixer."""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from ecom_ops.core.database import connect, init_db
from ecom_ops.core.settings import get_settings
from ecom_ops.video_mixer.domain import (
    SALES_STAGES,
    SALES_STAGE_CN,
    SEGMENT_SOURCE_CN,
    SEGMENT_STATUS_CN,
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _rows(rows: list) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


PRODUCT_TAG_CN = {
    "price_hook": "价格钩子",
    "vesa_installation": "VESA 安装",
    "rotation": "旋转功能",
    "multi_joint_adjustment": "多关节调节",
    "clean_desk": "桌面整洁",
    "installation": "安装过程",
    "compatibility": "兼容性",
    "feature_demo": "功能演示",
    "final_result": "最终效果",
    "monitor_arm": "显示器支架",
}


def _json_hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _tag_name(code: str, names: dict[str, str] | None = None) -> str:
    if names and names.get(code):
        return str(names[code])
    if code in PRODUCT_TAG_CN:
        return PRODUCT_TAG_CN[code]
    if any("\u4e00" <= char <= "\u9fff" for char in code):
        return code
    return code.replace("_", " ")


class MixerRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or get_settings().sqlite_path)
        init_db(self.db_path)
        self._backfill_segment_library()

    def _backfill_segment_library(self) -> None:
        """Upgrade legacy segment/timeline rows without changing their public IDs."""
        with connect(self.db_path) as conn:
            legacy_segments = conn.execute(
                """SELECT * FROM mixer_segments
                   WHERE active_version_id IS NULL
                      OR NOT EXISTS (
                        SELECT 1 FROM mixer_segment_versions v WHERE v.segment_id=mixer_segments.id
                      )"""
            ).fetchall()
            for row in legacy_segments:
                try:
                    item = json.loads(row["analysis_json"])
                except (TypeError, json.JSONDecodeError):
                    item = {}
                item.update(
                    segment_id=row["id"],
                    asset_id=row["asset_id"],
                    video_id=row["video_id"],
                    product_id=row["product_id"],
                    start_seconds=float(row["start_seconds"]),
                    end_seconds=float(row["end_seconds"]),
                    safe_start_seconds=float(row["safe_start_seconds"]),
                    safe_end_seconds=float(row["safe_end_seconds"]),
                    stage=row["stage"],
                    confidence=float(row["confidence"]),
                )
                source = str(item.get("analysis_source") or row["origin"] or "legacy")
                self._create_segment_version_conn(
                    conn,
                    item,
                    source=source,
                    human_verified=bool(row["human_verified"]),
                    prefer=True,
                )

            timeline_rows = conn.execute(
                """SELECT v.* FROM mixer_timeline_versions v
                   WHERE NOT EXISTS (
                     SELECT 1 FROM mixer_timeline_clips c
                     WHERE c.timeline_version_id=v.id
                   )"""
            ).fetchall()
            for row in timeline_rows:
                try:
                    timeline = json.loads(row["timeline_json"])
                except (TypeError, json.JSONDecodeError):
                    continue
                self._save_timeline_clips_conn(conn, str(row["id"]), timeline)

    def _create_segment_version_conn(
        self,
        conn,
        item: dict[str, Any],
        *,
        source: str,
        human_verified: bool,
        prefer: bool,
    ) -> dict[str, Any]:
        segment_id = str(item["segment_id"])
        payload = dict(item)
        payload["segment_id"] = segment_id
        payload["start_seconds"] = float(payload["start_seconds"])
        payload["end_seconds"] = float(payload["end_seconds"])
        payload["safe_start_seconds"] = float(
            payload.get("safe_start_seconds", payload["start_seconds"])
        )
        payload["safe_end_seconds"] = float(
            payload.get("safe_end_seconds", payload["end_seconds"])
        )
        payload["confidence"] = float(payload.get("confidence", 0))
        payload["analysis_source"] = source
        payload["human_verified"] = bool(human_verified)
        analysis_hash = _json_hash(payload)
        duplicate = conn.execute(
            """SELECT * FROM mixer_segment_versions
               WHERE segment_id=? AND analysis_hash=? AND source=?
               ORDER BY version DESC LIMIT 1""",
            (segment_id, analysis_hash, source),
        ).fetchone()
        if duplicate:
            if prefer:
                conn.execute(
                    "UPDATE mixer_segment_versions SET is_preferred=0 WHERE segment_id=?",
                    (segment_id,),
                )
                conn.execute(
                    "UPDATE mixer_segment_versions SET is_preferred=1 WHERE id=?",
                    (duplicate["id"],),
                )
                self._activate_segment_version_conn(conn, dict(duplicate))
            return dict(duplicate)

        version = int(
            conn.execute(
                "SELECT COALESCE(MAX(version), 0)+1 FROM mixer_segment_versions WHERE segment_id=?",
                (segment_id,),
            ).fetchone()[0]
        )
        version_id = uuid4().hex
        if prefer:
            conn.execute(
                "UPDATE mixer_segment_versions SET is_preferred=0 WHERE segment_id=?",
                (segment_id,),
            )
        conn.execute(
            """INSERT INTO mixer_segment_versions
               (id, segment_id, version, start_seconds, end_seconds,
                safe_start_seconds, safe_end_seconds, stage, confidence,
                analysis_json, analysis_hash, source, is_preferred,
                human_verified, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                version_id,
                segment_id,
                version,
                payload["start_seconds"],
                payload["end_seconds"],
                payload["safe_start_seconds"],
                payload["safe_end_seconds"],
                payload.get("stage", "product_reveal"),
                payload["confidence"],
                json.dumps(payload, ensure_ascii=False),
                analysis_hash,
                source,
                int(prefer),
                int(human_verified),
                _now(),
            ),
        )
        version_row = conn.execute(
            "SELECT * FROM mixer_segment_versions WHERE id=?", (version_id,)
        ).fetchone()
        if prefer and version_row:
            self._activate_segment_version_conn(conn, dict(version_row))
        self._save_version_tags_conn(conn, version_id, payload, source, human_verified)
        self._refresh_segment_search_conn(conn, version_id, payload)
        return dict(version_row) if version_row else {"id": version_id, "version": version}

    @staticmethod
    def _activate_segment_version_conn(conn, version: dict[str, Any]) -> None:
        conn.execute(
            """UPDATE mixer_segments SET
                 start_seconds=?, end_seconds=?, safe_start_seconds=?, safe_end_seconds=?,
                 stage=?, confidence=?, analysis_json=?, active_version_id=?,
                 human_verified=?, updated_at=?
               WHERE id=?""",
            (
                version["start_seconds"],
                version["end_seconds"],
                version["safe_start_seconds"],
                version["safe_end_seconds"],
                version["stage"],
                version["confidence"],
                version["analysis_json"],
                version["id"],
                version["human_verified"],
                _now(),
                version["segment_id"],
            ),
        )

    @staticmethod
    def _refresh_segment_search_conn(
        conn, version_id: str, payload: dict[str, Any]
    ) -> None:
        try:
            conn.execute(
                "DELETE FROM mixer_segment_search WHERE segment_version_id=?", (version_id,)
            )
            conn.execute(
                """INSERT INTO mixer_segment_search
                   (segment_version_id, visual_summary, transcript, on_screen_text,
                    selling_points, tags) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    version_id,
                    str(payload.get("visual_summary", "")),
                    str(payload.get("transcript", "")),
                    " ".join(payload.get("on_screen_text", []) or []),
                    " ".join(payload.get("selling_points", []) or []),
                    " ".join(payload.get("product_tags", []) or []),
                ),
            )
        except Exception:  # FTS5 is optional; indexed SQL filters still work.
            return

    @staticmethod
    def _save_version_tags_conn(
        conn,
        version_id: str,
        payload: dict[str, Any],
        source: str,
        human_verified: bool,
    ) -> None:
        product_id = str(payload.get("product_id", ""))
        tags: list[tuple[str, str, str, str]] = []
        stage = str(payload.get("stage", "product_reveal"))
        tags.append(("", f"stage:{stage}", SALES_STAGE_CN.get(stage, stage), "销售阶段"))
        names = payload.get("product_tag_names") or {}
        for raw_tag in payload.get("product_tags", []) or []:
            code = str(raw_tag).strip()
            if code:
                tags.append((product_id, code, _tag_name(code, names), "商品标签"))
        for tag_product_id, code, name_cn, category in tags:
            row = conn.execute(
                "SELECT id FROM mixer_tags WHERE product_id=? AND code=?",
                (tag_product_id, code),
            ).fetchone()
            tag_id = str(row["id"]) if row else uuid4().hex
            if not row:
                conn.execute(
                    """INSERT INTO mixer_tags
                       (id, product_id, code, name_cn, category, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (tag_id, tag_product_id, code, name_cn, category, _now()),
                )
            conn.execute(
                """INSERT OR REPLACE INTO mixer_segment_tags
                   (segment_version_id, tag_id, confidence, source, accepted, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    version_id,
                    tag_id,
                    float(payload.get("confidence", 0)),
                    source,
                    int(human_verified),
                    _now(),
                ),
            )

    @staticmethod
    def _save_timeline_clips_conn(
        conn, timeline_version_id: str, timeline: dict[str, Any]
    ) -> None:
        conn.execute(
            "DELETE FROM mixer_timeline_clips WHERE timeline_version_id=?",
            (timeline_version_id,),
        )
        for index, clip in enumerate(timeline.get("clips", [])):
            segment_id = str(clip.get("segment_id", ""))
            if not segment_id:
                continue
            segment = conn.execute(
                "SELECT active_version_id FROM mixer_segments WHERE id=?", (segment_id,)
            ).fetchone()
            if not segment:
                continue
            conn.execute(
                """INSERT INTO mixer_timeline_clips
                   (timeline_version_id, clip_order, clip_id, segment_id,
                    segment_version_id, product_id, video_id, source_path,
                    source_start, source_end, timeline_start, timeline_end,
                    stage, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timeline_version_id,
                    index,
                    str(clip.get("clip_id") or f"{timeline_version_id}:{index}"),
                    segment_id,
                    segment["active_version_id"],
                    str(clip.get("product_id", timeline.get("product_id", ""))),
                    str(clip.get("video_id", "")),
                    str(clip.get("source_path", "")),
                    float(clip.get("source_start", 0)),
                    float(clip.get("source_end", 0)),
                    float(clip.get("timeline_start", 0)),
                    float(clip.get("timeline_end", 0)),
                    str(clip.get("stage", "product_reveal")),
                    _now(),
                ),
            )

    def create_import(self, source_path: Path, ad_source_path: Path | None = None) -> str:
        import_id = uuid4().hex
        with connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO mixer_imports
                   (id, source_path, ad_source_path, status, created_at)
                   VALUES (?, ?, ?, 'running', ?)""",
                (import_id, str(source_path), str(ad_source_path or ""), _now()),
            )
        return import_id

    def finish_import(
        self,
        import_id: str,
        *,
        status: str,
        row_count: int = 0,
        product_count: int = 0,
        error_message: str = "",
    ) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """UPDATE mixer_imports
                   SET status=?, row_count=?, product_count=?, error_message=?, completed_at=?
                   WHERE id=?""",
                (status, row_count, product_count, error_message, _now(), import_id),
            )

    def save_scored_video(
        self,
        import_id: str,
        *,
        product_id: str,
        video_id: str,
        url: str,
        metrics: dict[str, Any],
        quality_score: float,
        tier: str,
        evidence_confidence: float,
        low_sample: bool,
        product_name: str = "",
        title: str = "",
        creator_name: str = "",
    ) -> None:
        now = _now()
        platform_video_id = video_id
        video_id = f"{product_id}:{platform_video_id}"
        payload = json.dumps(metrics, ensure_ascii=False, default=str)
        with connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO mixer_products
                   (product_id, product_name, material_count, updated_at)
                   VALUES (?, ?, 0, ?)
                   ON CONFLICT(product_id) DO UPDATE SET
                     product_name=COALESCE(NULLIF(excluded.product_name, ''), product_name),
                     updated_at=excluded.updated_at""",
                (product_id, product_name, now),
            )
            conn.execute(
                """INSERT INTO mixer_videos
                   (video_id, product_id, platform_video_id, url, title, creator_name, latest_score,
                    latest_tier, low_sample, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(video_id) DO UPDATE SET
                     product_id=excluded.product_id, url=excluded.url,
                     title=excluded.title, creator_name=excluded.creator_name,
                     latest_score=excluded.latest_score, latest_tier=excluded.latest_tier,
                     low_sample=excluded.low_sample, updated_at=excluded.updated_at""",
                (
                    video_id,
                    product_id,
                    platform_video_id,
                    url,
                    title,
                    creator_name,
                    quality_score,
                    tier,
                    int(low_sample),
                    now,
                    now,
                ),
            )
            conn.execute(
                """INSERT INTO mixer_metric_snapshots
                   (import_id, video_id, product_id, metrics_json, quality_score,
                    tier, evidence_confidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(import_id, video_id, product_id) DO UPDATE SET
                     metrics_json=excluded.metrics_json,
                     quality_score=excluded.quality_score,
                     tier=excluded.tier,
                     evidence_confidence=excluded.evidence_confidence""",
                (
                    import_id,
                    video_id,
                    product_id,
                    payload,
                    quality_score,
                    tier,
                    evidence_confidence,
                    now,
                ),
            )

    def save_scored_videos(self, import_id: str, items: list[dict[str, Any]]) -> None:
        """Persist a large scored batch in one SQLite transaction."""
        now = _now()
        with connect(self.db_path) as conn:
            for item in items:
                platform_video_id = item["video_id"]
                storage_video_id = f"{item['product_id']}:{platform_video_id}"
                conn.execute(
                    """INSERT INTO mixer_products
                       (product_id, product_name, material_count, updated_at)
                       VALUES (?, ?, 0, ?)
                       ON CONFLICT(product_id) DO UPDATE SET
                         product_name=COALESCE(NULLIF(excluded.product_name, ''), product_name),
                         updated_at=excluded.updated_at""",
                    (item["product_id"], item.get("product_name", ""), now),
                )
                conn.execute(
                    """INSERT INTO mixer_videos
                       (video_id, product_id, platform_video_id, url, title, creator_name, latest_score,
                        latest_tier, low_sample, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(video_id) DO UPDATE SET
                         product_id=excluded.product_id, url=excluded.url,
                         title=excluded.title, creator_name=excluded.creator_name,
                         latest_score=excluded.latest_score, latest_tier=excluded.latest_tier,
                         low_sample=excluded.low_sample, updated_at=excluded.updated_at""",
                    (
                        storage_video_id,
                        item["product_id"],
                        platform_video_id,
                        item["url"],
                        item.get("title", ""),
                        item.get("creator_name", ""),
                        item["quality_score"],
                        item["tier"],
                        int(item["low_sample"]),
                        now,
                        now,
                    ),
                )
                conn.execute(
                    """INSERT INTO mixer_metric_snapshots
                       (import_id, video_id, product_id, metrics_json, quality_score,
                        tier, evidence_confidence, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(import_id, video_id, product_id) DO UPDATE SET
                         metrics_json=excluded.metrics_json,
                         quality_score=excluded.quality_score,
                         tier=excluded.tier,
                         evidence_confidence=excluded.evidence_confidence""",
                    (
                        import_id,
                        storage_video_id,
                        item["product_id"],
                        json.dumps(item["metrics"], ensure_ascii=False, default=str),
                        item["quality_score"],
                        item["tier"],
                        item["evidence_confidence"],
                        now,
                    ),
                )

    def refresh_product_counts(self) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """UPDATE mixer_products
                   SET material_count=(
                     SELECT COUNT(*) FROM mixer_videos v
                     WHERE v.product_id=mixer_products.product_id
                   ), updated_at=?""",
                (_now(),),
            )

    def imports(self, limit: int = 30) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return _rows(
                conn.execute(
                    "SELECT * FROM mixer_imports ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            )

    def products(self, limit: int = 500) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return _rows(
                conn.execute(
                    """SELECT p.*,
                       SUM(CASE WHEN v.latest_tier='S' THEN 1 ELSE 0 END) AS s_count,
                       SUM(CASE WHEN v.latest_tier='A' THEN 1 ELSE 0 END) AS a_count
                       FROM mixer_products p
                       LEFT JOIN mixer_videos v ON v.product_id=p.product_id
                       GROUP BY p.product_id
                       ORDER BY p.material_count DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            )

    def product(self, product_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM mixer_products WHERE product_id=?", (product_id,)
            ).fetchone()
            return dict(row) if row else None

    def product_videos(self, product_id: str, limit: int = 30) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return _rows(
                conn.execute(
                    """SELECT * FROM mixer_videos WHERE product_id=?
                       ORDER BY latest_score DESC LIMIT ?""",
                    (product_id, limit),
                ).fetchall()
            )

    def save_asset(
        self,
        *,
        video_id: str,
        product_id: str,
        path: Path,
        source: str,
        sha256: str,
        status: str = "ready",
        **metadata: Any,
    ) -> str:
        asset_id = uuid4().hex
        with connect(self.db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM mixer_assets WHERE video_id=? AND path=?",
                (video_id, str(path)),
            ).fetchone()
            if existing:
                return str(existing["id"])
            conn.execute(
                """INSERT INTO mixer_assets
                   (id, video_id, product_id, path, source, sha256, perceptual_hash,
                    audio_fingerprint, duration, width, height, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    asset_id,
                    video_id,
                    product_id,
                    str(path),
                    source,
                    sha256,
                    metadata.get("perceptual_hash"),
                    metadata.get("audio_fingerprint"),
                    metadata.get("duration"),
                    metadata.get("width"),
                    metadata.get("height"),
                    status,
                    _now(),
                ),
            )
        return asset_id

    def product_assets(self, product_id: str) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return _rows(
                conn.execute(
                    """SELECT * FROM mixer_assets WHERE product_id=?
                       ORDER BY created_at DESC""",
                    (product_id,),
                ).fetchall()
            )

    def save_segments(self, segments: list[dict[str, Any]]) -> int:
        saved = 0
        with connect(self.db_path) as conn:
            for item in segments:
                source = str(item.get("analysis_source") or "ai")
                existing = conn.execute(
                    "SELECT human_verified FROM mixer_segments WHERE id=?",
                    (item["segment_id"],),
                ).fetchone()
                prefer_ai_version = not (existing and bool(existing["human_verified"]))
                conn.execute(
                    """INSERT INTO mixer_segments
                       (id, asset_id, video_id, product_id, start_seconds, end_seconds,
                        safe_start_seconds, safe_end_seconds, stage, confidence, analysis_json,
                        origin, status, human_verified, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                         start_seconds=excluded.start_seconds,
                         end_seconds=excluded.end_seconds,
                         safe_start_seconds=excluded.safe_start_seconds,
                         safe_end_seconds=excluded.safe_end_seconds,
                         stage=excluded.stage, confidence=excluded.confidence,
                         analysis_json=excluded.analysis_json,
                         updated_at=excluded.updated_at
                       WHERE mixer_segments.human_verified=0""",
                    (
                        item["segment_id"],
                        item["asset_id"],
                        item["video_id"],
                        item["product_id"],
                        item["start_seconds"],
                        item["end_seconds"],
                        item["safe_start_seconds"],
                        item["safe_end_seconds"],
                        item["stage"],
                        item["confidence"],
                        json.dumps(item, ensure_ascii=False),
                        source,
                        _now(),
                        _now(),
                    ),
                )
                self._create_segment_version_conn(
                    conn,
                    item,
                    source=source,
                    human_verified=False,
                    prefer=prefer_ai_version,
                )
                saved += 1
        return saved

    def product_segments(self, product_id: str) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            rows = conn.execute(
                """SELECT s.*, a.path AS source_path, v.latest_score AS video_score
                   FROM mixer_segments s
                   JOIN mixer_assets a ON a.id=s.asset_id
                   JOIN mixer_videos v ON v.video_id=s.video_id
                   WHERE s.product_id=? ORDER BY v.latest_score DESC, s.confidence DESC""",
                (product_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = json.loads(row["analysis_json"])
            item.update(
                asset_id=row["asset_id"],
                source_path=row["source_path"],
                video_score=row["video_score"],
            )
            result.append(item)
        return result

    def product_tags(self, product_id: str) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return _rows(
                conn.execute(
                    """SELECT id, product_id, code, name_cn, category, color
                       FROM mixer_tags WHERE product_id IN ('', ?)
                       ORDER BY category, name_cn""",
                    (product_id,),
                ).fetchall()
            )

    def asset(self, asset_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM mixer_assets WHERE id=?", (asset_id,)).fetchone()
            return dict(row) if row else None

    def segment(self, segment_id: str) -> dict[str, Any] | None:
        rows = self.search_segments(segment_id=segment_id, include_inactive=True, limit=1)
        return rows[0] if rows else None

    def search_segments(
        self,
        product_id: str = "",
        *,
        segment_id: str = "",
        stage: str = "",
        tag: str = "",
        duration_min: float = 0,
        duration_max: float = 60,
        confidence_min: float = 0,
        human_verified: bool | None = None,
        usage: str = "all",
        query: str = "",
        include_inactive: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        where = ["1=1"]
        params: list[Any] = []
        if product_id:
            where.append("s.product_id=?")
            params.append(product_id)
        if segment_id:
            where.append("s.id=?")
            params.append(segment_id)
        if not include_inactive:
            where.append("s.status='active'")
        if stage:
            where.append("s.stage=?")
            params.append(stage)
        where.append("(s.end_seconds-s.start_seconds)>=?")
        params.append(float(duration_min))
        where.append("(s.end_seconds-s.start_seconds)<=?")
        params.append(float(duration_max))
        where.append("s.confidence>=?")
        params.append(float(confidence_min))
        if human_verified is not None:
            where.append("s.human_verified=?")
            params.append(int(human_verified))
        if tag:
            where.append(
                """EXISTS (
                     SELECT 1 FROM mixer_segment_tags st
                     JOIN mixer_tags t ON t.id=st.tag_id
                     WHERE st.segment_version_id=s.active_version_id
                       AND (t.code=? OR t.name_cn=?)
                   )"""
            )
            params.extend([tag, tag])
        if usage == "used":
            where.append("COALESCE(u.usage_count, 0)>0")
        elif usage == "unused":
            where.append("COALESCE(u.usage_count, 0)=0")
        if query.strip():
            needle = f"%{query.strip()}%"
            where.append(
                """(s.analysis_json LIKE ? OR v.title LIKE ? OR EXISTS (
                     SELECT 1 FROM mixer_segment_tags st
                     JOIN mixer_tags t ON t.id=st.tag_id
                     WHERE st.segment_version_id=s.active_version_id AND t.name_cn LIKE ?
                   ))"""
            )
            params.extend([needle, needle, needle])
        params.extend([max(1, min(int(limit), 500)), max(0, int(offset))])
        sql = f"""
            SELECT s.*, a.path AS source_path, a.duration AS asset_duration,
                   a.width, a.height, v.latest_score AS video_score,
                   v.latest_tier AS video_tier, v.title AS video_title,
                   av.version AS active_version, av.source AS version_source,
                   COALESCE(u.usage_count, 0) AS usage_count,
                   COALESCE((
                     SELECT GROUP_CONCAT(t.name_cn, '、')
                     FROM mixer_segment_tags st
                     JOIN mixer_tags t ON t.id=st.tag_id
                     WHERE st.segment_version_id=s.active_version_id
                       AND t.category='商品标签'
                   ), '') AS tag_names
            FROM mixer_segments s
            JOIN mixer_assets a ON a.id=s.asset_id
            JOIN mixer_videos v ON v.video_id=s.video_id
            LEFT JOIN mixer_segment_versions av ON av.id=s.active_version_id
            LEFT JOIN (
              SELECT segment_id, COUNT(DISTINCT timeline_version_id) AS usage_count
              FROM mixer_timeline_clips GROUP BY segment_id
            ) u ON u.segment_id=s.id
            WHERE {' AND '.join(where)}
            ORDER BY s.human_verified DESC, v.latest_score DESC, s.confidence DESC,
                     s.start_seconds
            LIMIT ? OFFSET ?
        """
        with connect(self.db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                analysis = json.loads(item.pop("analysis_json"))
            except (TypeError, json.JSONDecodeError):
                analysis = {}
            item["analysis"] = analysis
            item["duration_seconds"] = round(
                float(item["end_seconds"]) - float(item["start_seconds"]), 3
            )
            item["stage_cn"] = SALES_STAGE_CN.get(item["stage"], item["stage"])
            source = str(item.get("version_source") or item.get("origin") or "ai")
            item["source_cn"] = SEGMENT_SOURCE_CN.get(source, source)
            item["status_cn"] = SEGMENT_STATUS_CN.get(item["status"], item["status"])
            item["tags"] = [tag for tag in str(item.pop("tag_names", "")).split("、") if tag]
            item["verified_cn"] = "人工已确认" if item["human_verified"] else "待人工确认"
            item["preview_url"] = f"http://127.0.0.1:8000/mixer/assets/{item['asset_id']}/media"
            result.append(item)
        return result

    def update_segment(
        self, segment_id: str, changes: dict[str, Any], *, source: str = "human"
    ) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT s.*, a.duration AS asset_duration
                   FROM mixer_segments s JOIN mixer_assets a ON a.id=s.asset_id
                   WHERE s.id=?""",
                (segment_id,),
            ).fetchone()
            if not row:
                raise KeyError(segment_id)
            try:
                payload = json.loads(row["analysis_json"])
            except (TypeError, json.JSONDecodeError):
                payload = {}
            payload.update(
                segment_id=segment_id,
                asset_id=row["asset_id"],
                video_id=row["video_id"],
                product_id=row["product_id"],
                start_seconds=float(changes.get("start_seconds", row["start_seconds"])),
                end_seconds=float(changes.get("end_seconds", row["end_seconds"])),
                safe_start_seconds=float(
                    changes.get("safe_start_seconds", changes.get("start_seconds", row["start_seconds"]))
                ),
                safe_end_seconds=float(
                    changes.get("safe_end_seconds", changes.get("end_seconds", row["end_seconds"]))
                ),
                stage=str(changes.get("stage", row["stage"])),
                confidence=float(changes.get("confidence", row["confidence"])),
            )
            for key in (
                "visual_summary",
                "transcript",
                "on_screen_text",
                "selling_points",
                "product_tags",
                "product_tag_names",
                "quality_issues",
                "continuity_in",
                "continuity_out",
            ):
                if key in changes:
                    payload[key] = changes[key]
            if payload["stage"] not in SALES_STAGES:
                raise ValueError("未知的销售阶段。")
            asset_duration = float(row["asset_duration"] or payload["end_seconds"])
            if not (0 <= payload["start_seconds"] < payload["end_seconds"] <= asset_duration + 0.05):
                raise ValueError("片段起止时间超出原视频范围。")
            if payload["end_seconds"] - payload["start_seconds"] < 0.1:
                raise ValueError("片段时长不能短于 0.1 秒。")
            self._create_segment_version_conn(
                conn,
                payload,
                source=source,
                human_verified=True,
                prefer=True,
            )
            conn.execute(
                "UPDATE mixer_segments SET status='active', origin=?, updated_at=? WHERE id=?",
                (source, _now(), segment_id),
            )
        updated = self.segment(segment_id)
        if not updated:
            raise KeyError(segment_id)
        return updated

    def split_segment(self, segment_id: str, at_seconds: float) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM mixer_segments WHERE id=?", (segment_id,)).fetchone()
            if not row:
                raise KeyError(segment_id)
            start = float(row["start_seconds"])
            end = float(row["end_seconds"])
            at = float(at_seconds)
            if at - start < 0.1 or end - at < 0.1:
                raise ValueError("分割点必须距离片段两端至少 0.1 秒。")
            try:
                base = json.loads(row["analysis_json"])
            except (TypeError, json.JSONDecodeError):
                base = {}
            child_ids: list[str] = []
            for child_start, child_end in ((start, at), (at, end)):
                child_id = uuid4().hex
                child = dict(base)
                child.update(
                    segment_id=child_id,
                    asset_id=row["asset_id"],
                    video_id=row["video_id"],
                    product_id=row["product_id"],
                    start_seconds=child_start,
                    end_seconds=child_end,
                    safe_start_seconds=child_start,
                    safe_end_seconds=child_end,
                    stage=row["stage"],
                    confidence=float(row["confidence"]),
                    parent_segment_id=segment_id,
                    boundary_note="人工分割",
                )
                conn.execute(
                    """INSERT INTO mixer_segments
                       (id, asset_id, video_id, product_id, start_seconds, end_seconds,
                        safe_start_seconds, safe_end_seconds, stage, confidence,
                        analysis_json, origin, parent_segment_id, status, human_verified,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'human_split', ?, 'active', 1, ?, ?)""",
                    (
                        child_id,
                        row["asset_id"],
                        row["video_id"],
                        row["product_id"],
                        child_start,
                        child_end,
                        child_start,
                        child_end,
                        row["stage"],
                        row["confidence"],
                        json.dumps(child, ensure_ascii=False),
                        segment_id,
                        _now(),
                        _now(),
                    ),
                )
                self._create_segment_version_conn(
                    conn,
                    child,
                    source="human_split",
                    human_verified=True,
                    prefer=True,
                )
                child_ids.append(child_id)
            conn.execute(
                "UPDATE mixer_segments SET status='superseded', updated_at=? WHERE id=?",
                (_now(), segment_id),
            )
        return [item for child_id in child_ids if (item := self.segment(child_id))]

    def segment_usage(self, segment_id: str) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return _rows(
                conn.execute(
                    """SELECT c.timeline_version_id, c.clip_order, c.source_start,
                              c.source_end, v.project_id, v.version, v.source,
                              p.status AS project_status, v.created_at
                       FROM mixer_timeline_clips c
                       JOIN mixer_timeline_versions v ON v.id=c.timeline_version_id
                       JOIN mixer_projects p ON p.id=v.project_id
                       WHERE c.segment_id=? ORDER BY v.created_at DESC""",
                    (segment_id,),
                ).fetchall()
            )

    def save_taxonomy(
        self, product_id: str, definition: dict[str, Any], *, approved: bool = False
    ) -> dict[str, Any]:
        with connect(self.db_path) as conn:
            version = int(
                conn.execute(
                    "SELECT COALESCE(MAX(version), 0)+1 FROM mixer_taxonomies WHERE product_id=?",
                    (product_id,),
                ).fetchone()[0]
            )
            taxonomy_id = uuid4().hex
            status = "approved" if approved else "pending"
            conn.execute(
                """INSERT INTO mixer_taxonomies
                   (id, product_id, version, status, definition_json, created_at, approved_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    taxonomy_id,
                    product_id,
                    version,
                    status,
                    json.dumps(definition, ensure_ascii=False),
                    _now(),
                    _now() if approved else None,
                ),
            )
            conn.execute(
                "UPDATE mixer_products SET taxonomy_status=?, updated_at=? WHERE product_id=?",
                (status, _now(), product_id),
            )
        return {"id": taxonomy_id, "product_id": product_id, "version": version, "status": status}

    def approve_taxonomy(self, taxonomy_id: str) -> None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT product_id FROM mixer_taxonomies WHERE id=?", (taxonomy_id,)
            ).fetchone()
            if not row:
                raise KeyError(taxonomy_id)
            conn.execute(
                "UPDATE mixer_taxonomies SET status='approved', approved_at=? WHERE id=?",
                (_now(), taxonomy_id),
            )
            conn.execute(
                "UPDATE mixer_products SET taxonomy_status='approved', updated_at=? WHERE product_id=?",
                (_now(), row["product_id"]),
            )

    def latest_taxonomy(self, product_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT * FROM mixer_taxonomies WHERE product_id=?
                   ORDER BY version DESC LIMIT 1""",
                (product_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["definition"] = json.loads(item.pop("definition_json"))
        return item

    def create_job(
        self,
        job_type: str,
        payload: dict[str, Any],
        *,
        estimated_cost: float = 0,
        requires_confirmation: bool = False,
        max_attempts: int = 3,
    ) -> dict[str, Any]:
        job_id = uuid4().hex
        status = "awaiting_confirmation" if requires_confirmation else "queued"
        now = _now()
        with connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO mixer_jobs
                   (id, job_type, status, payload_json, max_attempts, estimated_cost,
                    requires_confirmation, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    job_type,
                    status,
                    json.dumps(payload, ensure_ascii=False),
                    max_attempts,
                    estimated_cost,
                    int(requires_confirmation),
                    now,
                    now,
                ),
            )
        return self.job(job_id) or {}

    def confirm_job(self, job_id: str) -> None:
        with connect(self.db_path) as conn:
            updated = conn.execute(
                """UPDATE mixer_jobs SET status='queued', updated_at=?
                   WHERE id=? AND status='awaiting_confirmation'""",
                (_now(), job_id),
            ).rowcount
            if not updated:
                raise ValueError("Job is not awaiting confirmation.")

    def claim_job(self, worker_id: str, lease_seconds: int = 300) -> dict[str, Any] | None:
        now = datetime.now()
        lease_until = (now + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
        with connect(self.db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT * FROM mixer_jobs
                   WHERE status='queued' AND attempts < max_attempts
                     AND (
                       job_type != 'render_project'
                       OR NOT EXISTS (
                         SELECT 1 FROM mixer_jobs running
                         WHERE running.status='running'
                           AND running.job_type='render_project'
                       )
                     )
                     AND (
                       job_type != 'analyze_product'
                       OR (
                         SELECT COUNT(*) FROM mixer_jobs running
                         WHERE running.status='running'
                           AND running.job_type='analyze_product'
                       ) < 2
                     )
                   ORDER BY created_at LIMIT 1"""
            ).fetchone()
            if not row:
                return None
            conn.execute(
                """UPDATE mixer_jobs
                   SET status='running', attempts=attempts+1, lease_until=?,
                       heartbeat_at=?, updated_at=?
                   WHERE id=?""",
                (lease_until, now.isoformat(timespec="seconds"), _now(), row["id"]),
            )
        job = self.job(str(row["id"]))
        if job is not None:
            job["worker_id"] = worker_id
        return job

    def heartbeat(self, job_id: str, lease_seconds: int = 300) -> None:
        now = datetime.now()
        with connect(self.db_path) as conn:
            conn.execute(
                """UPDATE mixer_jobs SET heartbeat_at=?, lease_until=?, updated_at=?
                   WHERE id=? AND status='running'""",
                (
                    now.isoformat(timespec="seconds"),
                    (now + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds"),
                    _now(),
                    job_id,
                ),
            )

    def recover_expired_jobs(self, at: datetime | None = None) -> int:
        cutoff = (at or datetime.now()).isoformat(timespec="seconds")
        with connect(self.db_path) as conn:
            return conn.execute(
                """UPDATE mixer_jobs SET status='queued', lease_until=NULL, updated_at=?
                   WHERE status='running' AND lease_until < ? AND attempts < max_attempts""",
                (_now(), cutoff),
            ).rowcount

    def complete_job(
        self, job_id: str, result: dict[str, Any], *, actual_cost: float = 0
    ) -> None:
        with connect(self.db_path) as conn:
            conn.execute(
                """UPDATE mixer_jobs SET status='completed', result_json=?,
                   actual_cost=?, lease_until=NULL, updated_at=? WHERE id=?""",
                (json.dumps(result, ensure_ascii=False), actual_cost, _now(), job_id),
            )

    def fail_job(self, job_id: str, error: str, *, pause: bool = False) -> None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT attempts, max_attempts FROM mixer_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if not row:
                raise KeyError(job_id)
            status = "paused" if pause else (
                "failed" if row["attempts"] >= row["max_attempts"] else "queued"
            )
            conn.execute(
                """UPDATE mixer_jobs SET status=?, error_message=?, lease_until=NULL,
                   updated_at=? WHERE id=?""",
                (status, error, _now(), job_id),
            )

    def job(self, job_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM mixer_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        item["result"] = json.loads(item["result_json"]) if item.get("result_json") else None
        return item

    def jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            ids = [
                str(row["id"])
                for row in conn.execute(
                    "SELECT id FROM mixer_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            ]
        return [item for job_id in ids if (item := self.job(job_id))]

    def estimated_cost_today(self) -> float:
        today = datetime.now().date().isoformat()
        with connect(self.db_path) as conn:
            value = conn.execute(
                """SELECT COALESCE(SUM(estimated_cost), 0) FROM mixer_jobs
                   WHERE substr(created_at, 1, 10)=?
                     AND status NOT IN ('failed', 'cancelled')""",
                (today,),
            ).fetchone()[0]
        return float(value or 0)

    def create_project(
        self,
        product_id: str,
        *,
        target_duration: float = 30,
        language: str = "ms",
        audio_mode: str = "voiceover",
    ) -> dict[str, Any]:
        project_id = uuid4().hex
        now = _now()
        with connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO mixer_projects
                   (id, product_id, status, target_duration, language, audio_mode,
                    created_at, updated_at)
                   VALUES (?, ?, 'draft', ?, ?, ?, ?, ?)""",
                (project_id, product_id, target_duration, language, audio_mode, now, now),
            )
        return self.project(project_id) or {}

    def project(self, project_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM mixer_projects WHERE id=?", (project_id,)
            ).fetchone()
            return dict(row) if row else None

    def projects(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return _rows(
                conn.execute(
                    "SELECT * FROM mixer_projects ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            )

    def save_timeline(
        self, project_id: str, timeline: dict[str, Any], *, source: str
    ) -> dict[str, Any]:
        timeline = json.loads(json.dumps(timeline, ensure_ascii=False))
        cursor = 0.0
        for clip in timeline.get("clips", []):
            clip["clip_id"] = str(clip.get("clip_id") or uuid4().hex)
            clip_start = float(clip.get("source_start", 0))
            clip_end = float(clip.get("source_end", 0))
            if clip_end <= clip_start:
                raise ValueError("时间线片段结束时间必须晚于开始时间。")
            clip["source_start"] = clip_start
            clip["source_end"] = clip_end
            clip["timeline_start"] = round(cursor, 3)
            cursor += clip_end - clip_start
            clip["timeline_end"] = round(cursor, 3)
        timeline["duration"] = round(cursor, 3)
        with connect(self.db_path) as conn:
            version = int(
                conn.execute(
                    """SELECT COALESCE(MAX(version), 0)+1
                       FROM mixer_timeline_versions WHERE project_id=?""",
                    (project_id,),
                ).fetchone()[0]
            )
            version_id = uuid4().hex
            conn.execute(
                """INSERT INTO mixer_timeline_versions
                   (id, project_id, version, source, timeline_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    version_id,
                    project_id,
                    version,
                    source,
                    json.dumps(timeline, ensure_ascii=False),
                    _now(),
                ),
            )
            self._save_timeline_clips_conn(conn, version_id, timeline)
            conn.execute(
                "UPDATE mixer_projects SET updated_at=? WHERE id=?", (_now(), project_id)
            )
        return {"id": version_id, "project_id": project_id, "version": version}

    def latest_timeline(self, project_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                """SELECT * FROM mixer_timeline_versions WHERE project_id=?
                   ORDER BY version DESC LIMIT 1""",
                (project_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["timeline"] = json.loads(item.pop("timeline_json"))
        return item

    def review(
        self, project_id: str, decision: str, *, reason: str = "", render_path: str = ""
    ) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise ValueError("Decision must be approved or rejected.")
        review_id = uuid4().hex
        with connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO mixer_reviews
                   (id, project_id, render_path, decision, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (review_id, project_id, render_path, decision, reason, _now()),
            )
            conn.execute(
                "UPDATE mixer_projects SET status=?, updated_at=? WHERE id=?",
                (decision, _now(), project_id),
            )
        return {"id": review_id, "project_id": project_id, "decision": decision}

    def create_render(self, project_id: str) -> str:
        render_id = uuid4().hex
        with connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO mixer_renders (id, project_id, status, created_at)
                   VALUES (?, ?, 'running', ?)""",
                (render_id, project_id, _now()),
            )
            conn.execute(
                "UPDATE mixer_projects SET status='rendering', updated_at=? WHERE id=?",
                (_now(), project_id),
            )
        return render_id

    def finish_render(
        self,
        render_id: str,
        *,
        status: str,
        original_audio_path: str = "",
        voiceover_path: str = "",
        subtitle_path: str = "",
        cover_path: str = "",
        manifest_path: str = "",
        error_message: str = "",
    ) -> None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT project_id FROM mixer_renders WHERE id=?", (render_id,)
            ).fetchone()
            if not row:
                raise KeyError(render_id)
            conn.execute(
                """UPDATE mixer_renders SET status=?, original_audio_path=?,
                   voiceover_path=?, subtitle_path=?, cover_path=?, manifest_path=?,
                   error_message=?, completed_at=? WHERE id=?""",
                (
                    status,
                    original_audio_path,
                    voiceover_path,
                    subtitle_path,
                    cover_path,
                    manifest_path,
                    error_message,
                    _now(),
                    render_id,
                ),
            )
            conn.execute(
                "UPDATE mixer_projects SET status=?, updated_at=? WHERE id=?",
                ("review" if status == "completed" else "render_failed", _now(), row["project_id"]),
            )

    def render(self, render_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM mixer_renders WHERE id=?", (render_id,)
            ).fetchone()
            return dict(row) if row else None

    def renders(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return _rows(
                conn.execute(
                    """SELECT r.*, p.product_id FROM mixer_renders r
                       JOIN mixer_projects p ON p.id=r.project_id
                       ORDER BY r.created_at DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            )

    def reviews(self, limit: int = 100) -> list[dict[str, Any]]:
        with connect(self.db_path) as conn:
            return _rows(
                conn.execute(
                    "SELECT * FROM mixer_reviews ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
            )

    def save_ai_trace(
        self,
        *,
        product_id: str,
        video_id: str = "",
        operation: str,
        model: str,
        prompt_version: str,
        input_hash: str,
        request: dict[str, Any],
        response: dict[str, Any],
        job_id: str = "",
        estimated_cost: float = 0,
        actual_cost: float = 0,
    ) -> str:
        trace_id = uuid4().hex
        with connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO mixer_ai_traces
                   (id, job_id, product_id, video_id, operation, provider, model,
                    prompt_version, input_hash, request_json, response_json,
                    estimated_cost, actual_cost, created_at)
                   VALUES (?, ?, ?, ?, ?, 'openai', ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trace_id,
                    job_id,
                    product_id,
                    video_id,
                    operation,
                    model,
                    prompt_version,
                    input_hash,
                    json.dumps(request, ensure_ascii=False, default=str),
                    json.dumps(response, ensure_ascii=False, default=str),
                    estimated_cost,
                    actual_cost,
                    _now(),
                ),
            )
        return trace_id
