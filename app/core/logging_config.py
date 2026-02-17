"""
Application logging configuration.

- General app logs: {LOG_DIR}/app.log
- Daily schedule (Flow 1) logs: {LOG_DIR}/schedule_daily.log (separate file)
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from app.core.config import get_settings


# Logger name used by the daily schedule flow (has its own log file)
SCHEDULE_DAILY_LOGGER_NAME = "schedule.daily"

# Format for log messages
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_dir: Optional[str] = None,
    log_level: Optional[str] = None,
) -> None:
    """
    Configure application logging at startup.

    - Creates log directory if it does not exist.
    - App (root) logger: writes to {log_dir}/app.log and optionally to console.
    - Logger "schedule.daily": writes only to {log_dir}/schedule_daily.log (no propagation to root).

    **Input (request):**
        - log_dir: Directory for log files. Default from settings LOG_DIR (default "logs").
        - log_level: Level name (DEBUG, INFO, WARNING, ERROR). Default from settings LOG_LEVEL (default "INFO").

    **Output (response):** None.

    **What it does:** Adds FileHandlers (and optional StreamHandler) to root and to "schedule.daily" logger.
    """
    settings = get_settings()
    dir_path = Path(log_dir or settings.LOG_DIR)
    dir_path.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, (log_level or settings.LOG_LEVEL).upper(), logging.INFO)

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    # ---- Root / app logger: app.log + console ----
    app_log_file = dir_path / "app.log"
    app_file_handler = logging.FileHandler(app_log_file, encoding="utf-8")
    app_file_handler.setLevel(level)
    app_file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # Remove existing handlers to avoid duplicates on reload
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    root_logger.addHandler(app_file_handler)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # ---- Daily schedule logger: schedule_daily.log only (separate file) ----
    daily_log_file = dir_path / "schedule_daily.log"
    daily_file_handler = logging.FileHandler(daily_log_file, encoding="utf-8")
    daily_file_handler.setLevel(level)
    daily_file_handler.setFormatter(formatter)

    daily_logger = logging.getLogger(SCHEDULE_DAILY_LOGGER_NAME)
    daily_logger.setLevel(level)
    daily_logger.propagate = False  # Do not duplicate to root; daily logs only in schedule_daily.log
    for h in daily_logger.handlers[:]:
        daily_logger.removeHandler(h)
    daily_logger.addHandler(daily_file_handler)
