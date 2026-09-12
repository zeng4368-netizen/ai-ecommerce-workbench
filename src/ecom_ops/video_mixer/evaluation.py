"""Offline gold-set evaluation for segment labels and boundaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _f1(tp: int, fp: int, fn: int) -> float:
    denominator = 2 * tp + fp + fn
    return 2 * tp / denominator if denominator else 1.0


def evaluate_gold_set(
    gold: list[dict[str, Any]], predictions: list[dict[str, Any]]
) -> dict[str, Any]:
    predicted = {item["segment_id"]: item for item in predictions}
    pairs = [(item, predicted[item["segment_id"]]) for item in gold if item["segment_id"] in predicted]
    stages = sorted({item["stage"] for item in gold} | {item["stage"] for item in predictions})
    stage_scores = []
    for stage in stages:
        tp = sum(g["stage"] == stage and p["stage"] == stage for g, p in pairs)
        fp = sum(g["stage"] != stage and p["stage"] == stage for g, p in pairs)
        fn = sum(g["stage"] == stage and p["stage"] != stage for g, p in pairs)
        stage_scores.append(_f1(tp, fp, fn))

    boundary_hits = sum(
        abs(float(g["start_seconds"]) - float(p["start_seconds"])) <= 0.75
        and abs(float(g["end_seconds"]) - float(p["end_seconds"])) <= 0.75
        for g, p in pairs
    )
    tag_scores = []
    for gold_item, prediction in pairs:
        expected = set(gold_item.get("product_tags", []))
        actual = set(prediction.get("product_tags", []))
        tag_scores.append(_f1(len(expected & actual), len(actual - expected), len(expected - actual)))

    macro_stage_f1 = sum(stage_scores) / len(stage_scores) if stage_scores else 0.0
    boundary_accuracy = boundary_hits / len(pairs) if pairs else 0.0
    product_tag_f1 = sum(tag_scores) / len(tag_scores) if tag_scores else 0.0
    product_count = len({item["product_id"] for item in gold})
    return {
        "gold_segments": len(gold),
        "gold_products": product_count,
        "matched_segments": len(pairs),
        "coverage": len(pairs) / len(gold) if gold else 0.0,
        "macro_stage_f1": macro_stage_f1,
        "boundary_within_0_75_seconds": boundary_accuracy,
        "product_tag_f1": product_tag_f1,
        "dataset_ready": len(gold) >= 50 and product_count >= 5,
        "passed": (
            len(gold) >= 50
            and product_count >= 5
            and macro_stage_f1 >= 0.85
            and boundary_accuracy >= 0.80
            and product_tag_f1 >= 0.75
        ),
    }
