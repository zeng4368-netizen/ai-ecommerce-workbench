from __future__ import annotations

from pathlib import Path

from ecom_ops.core.settings import Settings
from ecom_ops.services.platform_registry import PlatformRegistry


def test_platform_registry_loads_isolated_tools(tmp_path: Path) -> None:
    config = tmp_path / "integrations.yaml"
    config.write_text(
        """
tools:
  - key: postiz
    name: Postiz
    role: Publishing
    description: Social operations
    repository: https://github.com/gitroomhq/postiz-app
    license: AGPL-3.0
    url_setting: postiz_url
    health_path: /
    capabilities: [Scheduling, Analytics]
    safety_note: Read only from the workbench.
  - key: multica
    name: Multica
    role: Agent orchestration
    description: AI task management
    repository: https://github.com/multica-ai/multica
    license: Multica License
    url_setting: multica_url
    health_path: /
    capabilities: [Task board, Codex runtime]
    safety_note: User confirmation is required.
""".strip(),
        encoding="utf-8",
    )
    settings = Settings(
        base_dir=tmp_path,
        raw_dir=tmp_path / "raw",
        processed_dir=tmp_path / "processed",
        output_dir=tmp_path / "output",
        screenshot_dir=tmp_path / "screenshots",
        log_dir=tmp_path / "logs",
        sqlite_path=tmp_path / "processed" / "db.sqlite3",
        selectors_path=tmp_path / "selectors.yaml",
        integrations_path=config,
        postiz_url="http://127.0.0.1:4200",
        multica_url="http://127.0.0.1:3000",
    )

    registry = PlatformRegistry(settings)
    tools = registry.tools()
    tool = tools[0]
    assert tool.name == "Postiz"
    assert tool.capabilities == ("Scheduling", "Analytics")
    assert registry.base_url(tool) == "http://127.0.0.1:4200"
    assert tools[1].name == "Multica"
    assert registry.base_url(tools[1]) == "http://127.0.0.1:3000"
