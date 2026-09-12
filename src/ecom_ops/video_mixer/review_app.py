"""Local review board for inspecting and editing an AI mashup plan."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from ecom_ops.video_mixer import media
from ecom_ops.video_mixer.config import VideoMixerConfig
from ecom_ops.video_mixer.labels import LABEL_CN
from ecom_ops.video_mixer.mixer import assemble


OUTPUT_DIR = Path("data/output/mashup")
SEGMENTS_DIR = Path("data/processed/segments")
LABEL_OPTIONS = list(LABEL_CN.values())
LABEL_TO_ID = {cn: label_id for label_id, cn in LABEL_CN.items()}


def _load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_valid(manifest: dict) -> bool:
    """A task is only usable when every source video file still exists."""
    sources = manifest.get("sources", [])
    if not sources:
        return False
    return all(Path(source.get("path", "")).exists() for source in sources)


def _manifest_label(path: Path) -> str:
    return path.stem.replace("_manifest", "")


def _sources_by_key(manifest: dict) -> dict[str, dict]:
    return {source["row_key"]: source for source in manifest.get("sources", [])}


def _plan_to_rows(plan: list[dict]) -> list[dict]:
    rows = []
    for order, item in enumerate(plan, start=1):
        rows.append(
            {
                "order": order,
                "video_key": item.get("video_key", ""),
                "segment_id": item.get("id", ""),
                "start": float(item.get("start", 0.0)),
                "end": float(item.get("end", 0.0)),
                "label_cn": item.get("label_cn") or LABEL_CN.get(item.get("label", ""), "其他"),
                "confidence": float(item.get("confidence", 0.0)),
                "video_score": float(item.get("video_score", 0.0)),
            }
        )
    return rows


def _candidate_rows(manifest: dict) -> list[dict]:
    rows: list[dict] = []
    for source in manifest.get("sources", []):
        path = SEGMENTS_DIR / source["row_key"] / "segments.json"
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for segment in data.get("segments", []):
            rows.append(
                {
                    "video_key": source["row_key"],
                    "segment_id": segment.get("id", ""),
                    "start": float(segment.get("start", 0.0)),
                    "end": float(segment.get("end", 0.0)),
                    "label_cn": segment.get("label_cn")
                    or LABEL_CN.get(segment.get("label", ""), "其他"),
                    "confidence": float(segment.get("confidence", 0.0)),
                    "video_score": float(source.get("quality_score", 0.0)),
                }
            )
    return rows


def _thumbnail(item: dict, run_id: str, index: int) -> Path:
    sources = st.session_state.get("sources_by_key", {})
    source = sources.get(item["video_key"], {})
    video_path = Path(source.get("path", ""))
    out = Path("data/processed/thumbs") / run_id / f"{index:02d}.jpg"
    if not video_path.exists():
        return out
    midpoint = (item["start"] + item["end"]) / 2
    return media.extract_thumbnail(video_path, midpoint, out)


def main() -> None:
    st.set_page_config(page_title="混剪审阅台", layout="wide")
    st.title("混剪审阅台")
    manifests = sorted(OUTPUT_DIR.glob("*_manifest.json"))
    valid_manifests = [m for m in manifests if _manifest_valid(_load_manifest(m))]
    if not valid_manifests:
        st.warning("没有可用的混剪任务（源素材文件缺失），请先运行一次混剪流水线。")
        return
    selected = st.selectbox(
        "选择混剪任务",
        valid_manifests,
        format_func=_manifest_label,
    )
    manifest = _load_manifest(selected)
    st.session_state["sources_by_key"] = _sources_by_key(manifest)

    st.subheader("当前混剪顺序")
    if "plan_rows" not in st.session_state or st.session_state.get("run") != selected.stem:
        st.session_state["plan_rows"] = _plan_to_rows(manifest.get("sequence", []))
        st.session_state["run"] = selected.stem

    plan_df = pd.DataFrame(st.session_state["plan_rows"])
    edited_df = st.data_editor(
        plan_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "order": st.column_config.NumberColumn("顺序", min_value=1, step=1),
            "video_key": st.column_config.TextColumn("素材"),
            "segment_id": st.column_config.TextColumn("片段", disabled=True),
            "start": st.column_config.NumberColumn("开始(秒)", min_value=0.0, step=0.5),
            "end": st.column_config.NumberColumn("结束(秒)", min_value=0.0, step=0.5),
            "label_cn": st.column_config.SelectboxColumn("标签", options=LABEL_OPTIONS),
            "confidence": st.column_config.NumberColumn("置信度", disabled=True),
            "video_score": st.column_config.NumberColumn("素材评分", disabled=True),
        },
        key="plan_editor",
    )
    st.session_state["plan_rows"] = edited_df.to_dict("records")

    st.subheader("候选片段")
    candidates = _candidate_rows(manifest)
    candidate_options = [
        f"{row['video_key'][:45]} | {row['start']:.1f}-{row['end']:.1f}s | {row['label_cn']}"
        for row in candidates
    ]
    chosen = st.multiselect("选择要加入计划的候选片段", candidate_options)
    if chosen and st.button("加入计划"):
        extra = [candidates[candidate_options.index(label)] for label in chosen]
        current = edited_df.to_dict("records")
        next_order = max([int(r.get("order", 0)) for r in current] + [0]) + 1
        for row in extra:
            row["order"] = next_order
            next_order += 1
        st.session_state["plan_rows"] = current + extra
        st.rerun()

    st.subheader("缩略图预览")
    thumb_cols = st.columns(min(6, max(1, len(edited_df))))
    for index, (_, item) in enumerate(edited_df.iterrows()):
        if not item.get("video_key"):
            continue
        thumb = _thumbnail(item, selected.stem, index)
        if thumb.exists():
            with thumb_cols[index % len(thumb_cols)]:
                st.image(str(thumb), caption=f"{index + 1}. {item['label_cn']}", use_container_width=True)

    if st.button("按我的修改重新导出", type="primary"):
        rows = [
            row
            for row in st.session_state["plan_rows"]
            if row.get("video_key") and row.get("start") is not None and row.get("end") is not None
        ]
        rows.sort(key=lambda row: float(row.get("order", 0)))
        plan = []
        sources = _sources_by_key(manifest)
        for row in rows:
            source = sources.get(row["video_key"], {})
            plan.append(
                {
                    "video_key": row["video_key"],
                    "video_path": source.get("path", ""),
                    "id": row.get("segment_id", ""),
                    "start": float(row["start"]),
                    "end": float(row["end"]),
                    "label": LABEL_TO_ID.get(row.get("label_cn", ""), "other"),
                    "label_cn": row.get("label_cn", "其他"),
                    "confidence": float(row.get("confidence", 0.0)),
                    "video_score": float(row.get("video_score", 0.0)),
                }
            )
        run_id = f"{selected.stem}_edited_{datetime.now().strftime('%H%M%S')}"
        cfg = VideoMixerConfig(table_path=Path("review.xlsx"))
        cfg.ensure_dirs()
        try:
            result = assemble(plan, cfg, run_id, manifest.get("sources", []))
            st.success(f"已导出：{result['output']}")
            st.video(result["output"])
        except Exception as exc:  # noqa: BLE001
            st.error(f"导出失败：{exc}")


if __name__ == "__main__":
    main()
