from __future__ import annotations

from datetime import datetime
from pathlib import Path
import logging

import yaml

from ecom_ops.core.database import log_automation_step
from ecom_ops.core.settings import Settings, get_settings


logger = logging.getLogger(__name__)


class AutomationPaused(RuntimeError):
    """Raised when login, captcha, two-factor verification, or disabled automation is detected."""


def load_selectors(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    if not settings.selectors_path.exists():
        raise FileNotFoundError(f"Missing selectors file: {settings.selectors_path}")
    return yaml.safe_load(settings.selectors_path.read_text(encoding="utf-8")) or {}


async def _is_visible(page, selector: str) -> bool:
    try:
        locator = page.locator(selector).first
        return await locator.is_visible(timeout=500)
    except Exception:
        return False


async def pause_if_auth_required(page, system_name: str, settings: Settings, run_id: str | None = None) -> None:
    selectors = load_selectors(settings)
    common = selectors.get("common", {})
    checks = {
        "login": common.get("login_indicators", []),
        "captcha": common.get("captcha_indicators", []),
        "two_factor": common.get("two_factor_indicators", []),
    }
    for status, status_selectors in checks.items():
        for selector in status_selectors:
            if await _is_visible(page, selector):
                screenshot_path = await screenshot(page, settings, f"{system_name}_{status}")
                log_automation_step(
                    settings.sqlite_path,
                    system_name,
                    "pause_if_auth_required",
                    status,
                    selector,
                    screenshot_path,
                    run_id,
                )
                raise AutomationPaused(f"Paused because {status} verification is visible.")


async def screenshot(page, settings: Settings, label: str) -> Path:
    settings.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)
    path = settings.screenshot_dir / f"{safe_label}_{stamp}.png"
    await page.screenshot(path=str(path), full_page=True)
    return path


async def open_safe_page(system_name: str, page_name: str, run_id: str | None = None) -> None:
    settings = get_settings()
    if not settings.automation_enabled:
        raise AutomationPaused("Browser automation is disabled. Set AUTOMATION_ENABLED=true after reviewing selectors.")

    selectors = load_selectors(settings)
    system = selectors.get(system_name)
    if not system:
        raise KeyError(f"No selector block configured for {system_name}.")

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("Install Playwright and browsers before running automation templates.") from exc

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=settings.browser_headless)
        page = await browser.new_page()
        await page.goto(system["base_url"])
        await pause_if_auth_required(page, system_name, settings, run_id)
        selector = system.get("safe_pages", {}).get(page_name)
        if selector:
            await page.locator(selector).click()
            path = await screenshot(page, settings, f"{system_name}_{page_name}")
            log_automation_step(settings.sqlite_path, system_name, f"open_{page_name}", "ok", selector, path, run_id)
        await browser.close()
