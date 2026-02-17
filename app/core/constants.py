"""
Application constants (n8n / Wellington integration).

Excludes today_date; that should be computed at runtime (e.g. {{ $now.format('yyyy-MM-dd') }}).

The following are loaded from .env via Settings:
  WELLINGTON_CUSTOMER_ID
  WELLINGTON_FARM_NAME
  WELLINGTON_USERNAME  (e.g. ckear0004@gmail.com)
  WELLINGTON_PASSWORD
"""

from app.core.config import get_settings

# --- Wellington / n8n integration ---

ORIGIN: str = "https://www.wellingtoninternational.com"

# From .env (Settings)
_settings = get_settings()
CUSTOMER_ID: str = _settings.WELLINGTON_CUSTOMER_ID
FARM_NAME: str = _settings.WELLINGTON_FARM_NAME
USERNAME: str = _settings.WELLINGTON_USERNAME
PASSWORD: str = _settings.WELLINGTON_PASSWORD
