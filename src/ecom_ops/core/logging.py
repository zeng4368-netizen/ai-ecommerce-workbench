from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
import sys

from ecom_ops.core.settings import Settings


def configure_logging(settings: Settings, run_id: str | None = None) -> Path:
    settings.ensure_dirs()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_name = f"{run_id or 'app'}_{stamp}.log"
    log_path = settings.log_dir / log_name
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )
    logging.getLogger(__name__).info("Logging to %s", log_path)
    return log_path
