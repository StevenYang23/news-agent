"""DeepSeek (OpenAI-compatible) summarization client."""
from __future__ import annotations

import json
import time

import requests

from .. import config
from . import skill

_CATEGORIES = ("macro", "tech", "politics", "volatility", "other")


def _chat(messages: list[dict], max_retries: int = 3) -> dict:
    url = f"{config.DEEPSEEK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": config.DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=180)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"DeepSeek call failed after {max_retries} attempts: {last_err}")


def is_configured() -> bool:
    return bool(config.DEEPSEEK_API_KEY)


def summarize(content: str, title: str = "") -> dict:
    """Return a normalized insight dict from raw content."""
    if not is_configured():
        raise RuntimeError("DEEPSEEK_API_KEY is not set. Add it to .env")

    messages = [
        {"role": "system", "content": skill.SYSTEM_PROMPT},
        {"role": "user", "content": skill.build_user_prompt(content, title)},
    ]
    result = _chat(messages)

    # --- normalize key_points ---
    key_points = result.get("key_points", [])
    if isinstance(key_points, list):
        key_points = [
            {"zh": p.get("zh", ""), "en": p.get("en", "")}
            if isinstance(p, dict) else {"zh": str(p), "en": str(p)}
            for p in key_points
        ]
    else:
        key_points = []

    # --- normalize categories (list) ---
    raw_cats = result.get("categories", [])
    if not isinstance(raw_cats, list):
        raw_cats = [str(raw_cats)]
    categories = []
    for c in raw_cats:
        c = str(c).lower().strip()
        if c in _CATEGORIES and c not in categories:
            categories.append(c)
    if not categories:
        categories = ["other"]

    tags = result.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    tickers = result.get("tickers", [])
    if not isinstance(tickers, list):
        tickers = []
    tickers = [str(t).upper() for t in tickers if str(t).strip()]

    return {
        "title_zh": str(result.get("title_zh", "")).strip(),
        "summary_zh": str(result.get("summary_zh", "")).strip(),
        "summary_en": str(result.get("summary_en", "")).strip(),
        "detail_zh": str(result.get("detail_zh", "")).strip(),
        "detail_en": str(result.get("detail_en", "")).strip(),
        "conclusion_zh": str(result.get("conclusion_zh", "")).strip(),
        "conclusion_en": str(result.get("conclusion_en", "")).strip(),
        "key_points": key_points,
        "categories": categories,
        "tags": [str(t) for t in tags],
        "tickers": tickers,
        "sentiment": str(result.get("sentiment", "neutral")).lower(),
        "us_equity_relevant": bool(result.get("us_equity_relevant", True)),
        "model": config.DEEPSEEK_MODEL,
    }
