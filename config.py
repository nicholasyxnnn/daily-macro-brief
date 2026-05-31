import os
from pathlib import Path
import yaml

ROOT = Path(__file__).parent

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_ADMIN_CHAT_ID: str = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", TELEGRAM_CHAT_ID)
FRED_API_KEY: str = os.environ.get("FRED_API_KEY", "")
NEWSAPI_KEY: str = os.environ.get("NEWSAPI_KEY", "")


def load_positions() -> dict:
    with open(ROOT / "config" / "positions.yml") as f:
        return yaml.safe_load(f)


def load_sources() -> dict:
    with open(ROOT / "config" / "sources.yml") as f:
        return yaml.safe_load(f)
