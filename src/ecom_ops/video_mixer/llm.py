"""Minimal OpenAI-compatible LLM client used for script labeling and sequencing."""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int = 60) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def chat_completion(
    llm: dict[str, Any], system: str, user: str, timeout: int = 90
) -> str | None:
    """Call an OpenAI-compatible /chat/completions endpoint. Returns content or None."""
    base_url = (llm.get("base_url") or "").rstrip("/")
    api_key = llm.get("api_key") or ""
    model = llm.get("model") or ""
    if not base_url or not api_key or not model:
        logger.info("LLM 未完整配置，跳过 AI 调用")
        return None
    url = f"{base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
    }
    try:
        data = _post_json(url, headers, payload, timeout=timeout)
        return data["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 调用失败，回退到启发式: %s", exc)
        return None
