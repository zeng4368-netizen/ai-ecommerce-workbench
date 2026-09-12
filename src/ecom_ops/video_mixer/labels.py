"""Segment label taxonomy used for script analysis and mashup ordering."""

from __future__ import annotations

# (id, chinese label, suggested position weight)
SEGMENT_LABELS: list[tuple[str, str, int]] = [
    ("hook", "开头钩子", 1),
    ("intro", "产品介绍", 2),
    ("showcase", "产品展示", 3),
    ("demo", "功能演示", 4),
    ("detail", "细节特写", 5),
    ("gaming", "游戏画面", 6),
    ("resolution", "分辨率展示", 7),
    ("color", "色彩展示", 8),
    ("movie", "电影画面", 9),
    ("social", "使用场景", 10),
    ("cta", "诱导下单/结尾CTA", 11),
    ("other", "其他", 99),
]

LABEL_IDS = {label_id for label_id, _, _ in SEGMENT_LABELS}
LABEL_CN = {label_id: cn for label_id, cn, _ in SEGMENT_LABELS}
LABEL_ORDER = {label_id: order for label_id, _, order in SEGMENT_LABELS}

# Keyword hints used by the heuristic labeler (fallback when no LLM is available).
KEYWORD_HINTS: list[tuple[str, list[str]]] = [
    ("hook", ["你知道吗", "别划走", "先别划", "3秒", "0.5秒", "attention", "wait", "stop"]),
    ("resolution", ["分辨率", "清晰", "4k", "2k", "1080", "画质", "高清", "像素", "resolution"]),
    ("color", ["色彩", "颜色", "色域", "鲜艳", "真实", "color", "vivid", "hdr"]),
    ("gaming", ["游戏", "电竞", "fps", "吃鸡", "王者", "原神", "game", "gaming", "gpu"]),
    ("movie", ["电影", "大片", "影院", "观影", "movie", "film", "cinema"]),
    ("detail", ["细节", "特写", "近距离", "材质", "做工", "close-up", "detail"]),
    ("intro", ["介绍", "这是", "这是一款", "我们", "产品", "大家好", "introduce", "meet"]),
    ("showcase", ["展示", "演示", "开箱", "上手", "showcase", "look", "see"]),
    ("cta", ["下单", "购买", "优惠", "价格", "链接", "冲", "拍", "下单链接", "buy", "order", "deal", "offer"]),
]

# Logical order for a well-structured mashup (hook first, CTA last).
LOGICAL_FLOW: list[str] = [
    "hook",
    "intro",
    "showcase",
    "demo",
    "detail",
    "gaming",
    "resolution",
    "color",
    "movie",
    "social",
    "cta",
]
