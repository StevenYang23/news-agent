"""Central configuration loaded from environment and sources.json."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# DeepSeek (OpenAI-compatible)
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Data locations
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "insights.db"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR = DATA_DIR / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

SOURCES_PATH = ROOT / "config" / "sources.json"

# Pipeline settings (defaults; overridden by sources.json "settings" block)
LOOKBACK_DAYS = 30
US_EQUITY_ONLY = True
MAX_ITEMS_PER_SOURCE = 10
# Whether to fetch YouTube auto-captions (slow / rate-limited) or just use the
# video description. Set USE_YOUTUBE_CAPTIONS=1 to enable captions.
USE_YOUTUBE_CAPTIONS = os.getenv("USE_YOUTUBE_CAPTIONS", "0") == "1"

_loaded = False


def load_sources() -> list[dict]:
    """Load source definitions. Returns only active sources by default."""
    global _loaded
    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    _apply_settings(data.get("settings", {}))
    _loaded = True
    return data["sources"]


def _apply_settings(settings: dict) -> None:
    global LOOKBACK_DAYS, US_EQUITY_ONLY, MAX_ITEMS_PER_SOURCE
    LOOKBACK_DAYS = int(settings.get("lookback_days", LOOKBACK_DAYS))
    US_EQUITY_ONLY = bool(settings.get("us_equity_only", US_EQUITY_ONLY))
    MAX_ITEMS_PER_SOURCE = int(settings.get("max_items_per_source", MAX_ITEMS_PER_SOURCE))


def active_sources() -> list[dict]:
    return [s for s in load_sources() if s.get("active")]
