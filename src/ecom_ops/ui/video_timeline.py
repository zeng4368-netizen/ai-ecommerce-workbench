"""Streamlit wrapper for the local React mixer timeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit.components.v1 as components


_BUILD_DIR = Path(__file__).resolve().parents[3] / "frontend" / "video_timeline" / "dist"
_component = components.declare_component("video_mixer_timeline", path=str(_BUILD_DIR))


def video_timeline(
    timeline: dict[str, Any],
    *,
    timeline_version: int,
    segment_library: list[dict[str, Any]] | None = None,
    key: str,
) -> dict[str, Any] | None:
    return _component(
        timeline=timeline,
        timeline_version=timeline_version,
        segment_library=segment_library or [],
        key=key,
        default=None,
    )
