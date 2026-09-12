from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


REPORT_PATH = "/report/integrated/get/"

BusinessTransport = Callable[[str, dict[str, str], int], dict[str, Any]]


class TikTokBusinessAPIError(RuntimeError):
    """Raised when TikTok API for Business rejects or cannot serve a report."""


def _default_transport(url: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise TikTokBusinessAPIError(f"TikTok Business HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise TikTokBusinessAPIError(f"TikTok Business connection failed: {exc.reason}") from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise TikTokBusinessAPIError("TikTok Business returned a non-JSON response.") from exc


class TikTokBusinessClient:
    def __init__(
        self,
        access_token: str,
        advertiser_id: str,
        base_url: str = "https://business-api.tiktok.com/open_api/v1.3",
        timeout: int = 20,
        transport: BusinessTransport | None = None,
    ) -> None:
        self.access_token = access_token
        self.advertiser_id = advertiser_id
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.transport = transport or _default_transport

    def report(
        self,
        *,
        data_level: str,
        dimensions: list[str],
        metrics: list[str],
        start_date: date,
        end_date: date,
        page: int = 1,
        page_size: int = 1000,
    ) -> dict[str, Any]:
        parameters = {
            "advertiser_id": self.advertiser_id,
            "report_type": "BASIC",
            "service_type": "AUCTION",
            "data_level": data_level,
            "dimensions": json.dumps(dimensions, separators=(",", ":")),
            "metrics": json.dumps(metrics, separators=(",", ":")),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "page": page,
            "page_size": min(max(page_size, 1), 1000),
        }
        payload = self.transport(
            f"{self.base_url}{REPORT_PATH}?{urlencode(parameters)}",
            {"Access-Token": self.access_token, "Accept": "application/json"},
            self.timeout,
        )
        code = payload.get("code", 0)
        if code not in (0, "0"):
            message = payload.get("message") or payload.get("request_id") or "unknown error"
            raise TikTokBusinessAPIError(f"TikTok Business API error {code}: {message}")
        return payload.get("data", {}) or {}
