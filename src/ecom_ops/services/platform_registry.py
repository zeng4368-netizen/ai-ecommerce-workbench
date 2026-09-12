from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

import yaml

from ecom_ops.core.settings import Settings, get_settings


@dataclass(frozen=True)
class ExternalTool:
    key: str
    name: str
    role: str
    description: str
    repository: str
    license: str
    url_setting: str
    health_path: str
    capabilities: tuple[str, ...]
    safety_note: str


@dataclass(frozen=True)
class ToolStatus:
    key: str
    configured: bool
    healthy: bool
    base_url: str
    message: str


class PlatformRegistry:
    """Loads isolated open-source services and performs read-only health checks."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def tools(self) -> list[ExternalTool]:
        path = self.settings.integrations_path
        if path is None or not path.exists():
            return []
        payload: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return [
            ExternalTool(
                key=str(item["key"]),
                name=str(item["name"]),
                role=str(item.get("role", "")),
                description=str(item.get("description", "")),
                repository=str(item.get("repository", "")),
                license=str(item.get("license", "")),
                url_setting=str(item.get("url_setting", "")),
                health_path=str(item.get("health_path", "/")),
                capabilities=tuple(str(value) for value in item.get("capabilities", [])),
                safety_note=str(item.get("safety_note", "")),
            )
            for item in payload.get("tools", [])
        ]

    def base_url(self, tool: ExternalTool) -> str:
        return str(getattr(self.settings, tool.url_setting, "") or "").rstrip("/")

    def status(self, tool: ExternalTool) -> ToolStatus:
        base_url = self.base_url(tool)
        if not base_url:
            return ToolStatus(tool.key, False, False, "", "尚未配置服务地址")
        url = urljoin(f"{base_url}/", tool.health_path.lstrip("/"))
        request = Request(url, headers={"User-Agent": "EcomOpsWorkbench/0.2"}, method="GET")
        try:
            with urlopen(request, timeout=self.settings.external_health_timeout_seconds) as response:
                healthy = 200 <= int(response.status) < 400
                message = f"HTTP {response.status}" if healthy else f"服务返回 HTTP {response.status}"
        except HTTPError as exc:
            healthy = 200 <= int(exc.code) < 500
            message = f"HTTP {exc.code}" if healthy else f"服务返回 HTTP {exc.code}"
        except (URLError, TimeoutError, OSError) as exc:
            healthy = False
            message = f"无法连接：{getattr(exc, 'reason', exc)}"
        return ToolStatus(tool.key, True, healthy, base_url, message)

    def statuses(self) -> list[tuple[ExternalTool, ToolStatus]]:
        return [(tool, self.status(tool)) for tool in self.tools()]
