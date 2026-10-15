"""JSON-file state: the single source of truth for the static site.

The deployable data lives at ``site/insights.json`` and is committed to git,
which doubles as both the dedup state and the served data for GitHub Pages.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import config

STATE_PATH = config.ROOT / "site" / "insights.json"


def load() -> list[dict]:
    """Load existing insights (newest-first), or [] if none."""
    if not STATE_PATH.exists():
        return []
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("insights", []) or []
    except (json.JSONDecodeError, OSError):
        return []


def save(insights: list[dict]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "insights": insights,
    }
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def existing_guids() -> set[str]:
    return {i.get("guid") for i in load() if i.get("guid")}


def prune(insights: list[dict], days: int) -> list[dict]:
    """Rolling retention: drop insights older than N days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for it in insights:
        try:
            dt = datetime.fromisoformat(it.get("published_at") or "")
        except (ValueError, TypeError):
            dt = datetime.now(timezone.utc)
        if dt >= cutoff:
            out.append(it)
    return out


def sort_newest(insights: list[dict]) -> list[dict]:
    return sorted(insights, key=lambda x: x.get("published_at") or "", reverse=True)


# ---- transcript usage tracking (monthly credit budget) ----

def _usage_path():
    return STATE_PATH.parent / "usage.json"


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def usage_count() -> int:
    """Transcript credits used this calendar month (persisted across runs)."""
    try:
        with open(_usage_path(), encoding="utf-8") as f:
            data = json.load(f)
        return int(data.get(_month_key(), 0) or 0)
    except (OSError, ValueError, json.JSONDecodeError):
        return 0


def add_usage(count: int) -> None:
    if count <= 0:
        return
    data = {}
    try:
        with open(_usage_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, json.JSONDecodeError):
        data = {}
    key = _month_key()
    data[key] = int(data.get(key, 0) or 0) + count
    with open(_usage_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def save_sources(sources: list[dict]) -> None:
    """Export the active source list to site/sources.json for the frontend."""
    active = [s for s in sources if s.get("active")]
    out = [
        {
            "name": s.get("name"),
            "url": s.get("url", ""),
            "type": s.get("type", ""),
            "kind": s.get("kind", ""),
            "category": s.get("category", ""),
            "note": s.get("note", ""),
        }
        for s in active
    ]
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH.parent / "sources.json", "w", encoding="utf-8") as f:
        json.dump({"sources": out}, f, ensure_ascii=False, indent=2)
