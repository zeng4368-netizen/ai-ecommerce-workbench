from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parents[3]


def _parse_bool(value: str | bool | None, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_env(path: Path | None = None) -> None:
    env_path = path or BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _path_from_env(name: str, default: str) -> Path:
    raw = os.getenv(name, default)
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    raw_dir: Path
    processed_dir: Path
    output_dir: Path
    screenshot_dir: Path
    log_dir: Path
    sqlite_path: Path
    selectors_path: Path
    integrations_path: Path | None = None
    log_level: str = "INFO"
    browser_headless: bool = True
    automation_enabled: bool = False
    require_human_confirmation: bool = True
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = "http://127.0.0.1:8000/tiktok/oauth/callback"
    tiktok_login_platform: str = "desktop"
    tiktok_scopes: str = "user.info.basic,video.list"
    tiktok_sync_interval_seconds: int = 300
    tiktok_max_pages_per_sync: int = 50
    tiktok_request_timeout_seconds: int = 20
    tiktok_business_access_token: str = ""
    tiktok_business_advertiser_id: str = ""
    tiktok_business_base_url: str = "https://business-api.tiktok.com/open_api/v1.3"
    tiktok_ads_report_days: int = 30
    tiktok_ads_metrics: str = (
        "spend,impressions,clicks,ctr,cpc,conversion,cost_per_conversion,"
        "video_play_actions,video_watched_2s,video_watched_6s,video_views_p100,"
        "onsite_total_purchase,onsite_purchases_roas"
    )
    postiz_url: str = ""
    brightbean_url: str = ""
    multica_url: str = ""
    external_health_timeout_seconds: int = 3
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    mixer_vision_model: str = "gpt-5-mini"
    mixer_transcription_model: str = "gpt-4o-mini-transcribe"
    mixer_tts_model: str = "gpt-4o-mini-tts"
    mixer_tts_voice: str = "marin"
    mixer_daily_budget: float = 0.0
    mixer_download_concurrency: int = 2
    mixer_render_concurrency: int = 1
    mixer_use_tikwm_fallback: bool = False
    mixer_cookies_file: str = ""
    mixer_cookies_from_browser: str = ""

    @property
    def tiktok_configured(self) -> bool:
        return bool(self.tiktok_client_key and self.tiktok_client_secret and self.tiktok_redirect_uri)

    @property
    def tiktok_ads_configured(self) -> bool:
        return bool(self.tiktok_business_access_token and self.tiktok_business_advertiser_id)

    def ensure_dirs(self) -> None:
        for path in [
            self.raw_dir,
            self.processed_dir,
            self.output_dir,
            self.screenshot_dir,
            self.log_dir,
            self.sqlite_path.parent,
        ]:
            path.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    load_env()
    settings = Settings(
        base_dir=BASE_DIR,
        raw_dir=_path_from_env("DATA_RAW_DIR", "data/raw"),
        processed_dir=_path_from_env("DATA_PROCESSED_DIR", "data/processed"),
        output_dir=_path_from_env("DATA_OUTPUT_DIR", "data/output"),
        screenshot_dir=_path_from_env("SCREENSHOT_DIR", "data/screenshots"),
        log_dir=BASE_DIR / "logs",
        sqlite_path=_path_from_env("SQLITE_PATH", "data/processed/ecom_ops.sqlite3"),
        selectors_path=_path_from_env("SELECTORS_PATH", "config/selectors.yaml"),
        integrations_path=_path_from_env("INTEGRATIONS_PATH", "config/integrations.yaml"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        browser_headless=_parse_bool(os.getenv("BROWSER_HEADLESS"), True),
        automation_enabled=_parse_bool(os.getenv("AUTOMATION_ENABLED"), False),
        require_human_confirmation=_parse_bool(os.getenv("REQUIRE_HUMAN_CONFIRMATION"), True),
        tiktok_client_key=os.getenv("TIKTOK_CLIENT_KEY", "").strip(),
        tiktok_client_secret=os.getenv("TIKTOK_CLIENT_SECRET", "").strip(),
        tiktok_redirect_uri=os.getenv(
            "TIKTOK_REDIRECT_URI", "http://127.0.0.1:8000/tiktok/oauth/callback"
        ).strip(),
        tiktok_login_platform=os.getenv("TIKTOK_LOGIN_PLATFORM", "desktop").strip().lower(),
        tiktok_scopes=os.getenv("TIKTOK_SCOPES", "user.info.basic,video.list").strip(),
        tiktok_sync_interval_seconds=max(60, int(os.getenv("TIKTOK_SYNC_INTERVAL_SECONDS", "300"))),
        tiktok_max_pages_per_sync=max(1, int(os.getenv("TIKTOK_MAX_PAGES_PER_SYNC", "50"))),
        tiktok_request_timeout_seconds=max(5, int(os.getenv("TIKTOK_REQUEST_TIMEOUT_SECONDS", "20"))),
        tiktok_business_access_token=os.getenv("TIKTOK_BUSINESS_ACCESS_TOKEN", "").strip(),
        tiktok_business_advertiser_id=os.getenv("TIKTOK_BUSINESS_ADVERTISER_ID", "").strip(),
        tiktok_business_base_url=os.getenv(
            "TIKTOK_BUSINESS_BASE_URL",
            "https://business-api.tiktok.com/open_api/v1.3",
        ).strip().rstrip("/"),
        tiktok_ads_report_days=max(1, min(90, int(os.getenv("TIKTOK_ADS_REPORT_DAYS", "30")))),
        tiktok_ads_metrics=os.getenv(
            "TIKTOK_ADS_METRICS",
            (
                "spend,impressions,clicks,ctr,cpc,conversion,cost_per_conversion,"
                "video_play_actions,video_watched_2s,video_watched_6s,video_views_p100,"
                "onsite_total_purchase,onsite_purchases_roas"
            ),
        ).strip(),
        postiz_url=os.getenv("POSTIZ_URL", "").strip().rstrip("/"),
        brightbean_url=os.getenv("BRIGHTBEAN_URL", "").strip().rstrip("/"),
        multica_url=os.getenv("MULTICA_URL", "").strip().rstrip("/"),
        external_health_timeout_seconds=max(
            1, min(15, int(os.getenv("EXTERNAL_HEALTH_TIMEOUT_SECONDS", "3")))
        ),
        openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
        mixer_vision_model=os.getenv("MIXER_VISION_MODEL", "gpt-5-mini").strip(),
        mixer_transcription_model=os.getenv(
            "MIXER_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"
        ).strip(),
        mixer_tts_model=os.getenv("MIXER_TTS_MODEL", "gpt-4o-mini-tts").strip(),
        mixer_tts_voice=os.getenv("MIXER_TTS_VOICE", "marin").strip(),
        mixer_daily_budget=max(0.0, float(os.getenv("MIXER_DAILY_BUDGET", "0"))),
        mixer_download_concurrency=max(
            1, min(2, int(os.getenv("MIXER_DOWNLOAD_CONCURRENCY", "2")))
        ),
        mixer_render_concurrency=max(
            1, int(os.getenv("MIXER_RENDER_CONCURRENCY", "1"))
        ),
        mixer_use_tikwm_fallback=_parse_bool(
            os.getenv("MIXER_USE_TIKWM_FALLBACK"), False
        ),
        mixer_cookies_file=os.getenv("MIXER_COOKIES_FILE", "").strip(),
        mixer_cookies_from_browser=os.getenv("MIXER_COOKIES_FROM_BROWSER", "").strip(),
    )
    settings.ensure_dirs()
    return settings
