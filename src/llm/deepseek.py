"""DeepSeek (OpenAI-compatible) summarization client."""
from __future__ import annotations

import json
import time

import requests

from .. import config

_SYSTEM_PROMPT = (
    "You are a senior buy-side equity research analyst. You read public research, "
    "podcast transcripts, and market commentary, then produce concise, balanced "
    "bilingual (Chinese + English) summaries focused on US equities. "
    "You always respond with a single valid JSON object and nothing else."
)

_USER_TEMPLATE = """\
Analyze the following content. Focus ONLY on material that is relevant to US equities \
(US-listed stocks, sectors, or macro that directly moves US equity markets).

Return a JSON object with exactly these fields:
- "title_zh": concise Chinese title
- "summary_zh": 2-3 sentence Chinese summary of the key investment insight
- "summary_en": equivalent English summary
- "key_points": array of 3-5 objects, each {{"zh": "...", "en": "..."}}
- "tags": array of 2-5 short topic tags (English)
- "tickers": array of US stock tickers mentioned (uppercase, no duplicates), omit if none
- "sentiment": one of "positive", "neutral", "negative" (overall market/stance tone)
- "us_equity_relevant": boolean, true only if this content is meaningfully relevant to US equities

Rules:
- If the content is NOT relevant to US equities, set "us_equity_relevant": false and keep all other fields minimal.
- Summaries must be in the content's own voice, no hedging, no "this article says".
- Keep summaries factual and specific (names, numbers, direction).

CONTENT:
{content}
"""


def _chat(messages: list[dict], max_retries: int = 3) -> dict:
    url = f"{config.DEEPSEEK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": config.DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=120)
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

    # Token budget: keep the model call cheap and fast.
    content = (content or "").strip()
    if len(content) > 6000:
        content = content[:6000] + "\n...[truncated]"

    user_msg = _USER_TEMPLATE.format(content=content or title)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    result = _chat(messages)

    # Normalize / defensive parsing
    key_points = result.get("key_points", [])
    if isinstance(key_points, list):
        key_points = [
            {"zh": p.get("zh", ""), "en": p.get("en", "")}
            if isinstance(p, dict) else {"zh": str(p), "en": str(p)}
            for p in key_points
        ]
    else:
        key_points = []

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
        "key_points": key_points,
        "tags": [str(t) for t in tags],
        "tickers": tickers,
        "sentiment": str(result.get("sentiment", "neutral")).lower(),
        "us_equity_relevant": bool(result.get("us_equity_relevant", True)),
        "model": config.DEEPSEEK_MODEL,
    }
