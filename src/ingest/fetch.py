"""RSS/podcast fetching and article text extraction."""
from __future__ import annotations

import email.utils
import re
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from bs4 import BeautifulSoup

from .. import config

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


def _to_iso(dt) -> str | None:
    if not dt:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def fetch_rss(feed_url: str) -> list[dict]:
    """Fetch and parse an RSS/Atom feed into normalized items."""
    parsed = feedparser.parse(feed_url)
    items = []
    for entry in parsed.entries:
        guid = entry.get("id") or entry.get("link") or entry.get("title")
        if not guid:
            continue

        published = None
        for key in ("published_parsed", "updated_parsed", "created_parsed"):
            if entry.get(key):
                published = _to_iso(datetime(*entry[key][:6], tzinfo=timezone.utc))
                break
        if not published:
            published = _to_iso(datetime.now(timezone.utc))

        # Prefer full text content, fall back to summary/description.
        content = ""
        if entry.get("content"):
            content = entry["content"][0].get("value", "")
        if not content:
            content = entry.get("summary", "") or entry.get("description", "")
        content = _html_to_text(content)

        enclosure = ""
        if entry.get("enclosures"):
            enclosure = entry["enclosures"][0].get("href", "")

        items.append(
            {
                "guid": guid,
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "published_at": published,
                "content": content.strip(),
                "enclosure": enclosure,
            }
        )
    return items


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n")).strip()


def extract_article_text(url: str) -> str:
    """Fetch a web page and extract its main readable text."""
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside"]):
        tag.decompose()

    # Prefer explicit content containers.
    container = (
        soup.find("article")
        or soup.find("main")
        or soup.find(attrs={"class": re.compile(r"(post|article|entry|content)", re.I)})
        or soup.body
    )
    if container is None:
        return ""
    text = container.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def filter_recent(items: list[dict], days: int | None = None) -> list[dict]:
    """Keep only items published within the last N days (rolling window)."""
    days = days if days is not None else config.LOOKBACK_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for it in items:
        try:
            dt = datetime.fromisoformat(it["published_at"])
        except (ValueError, TypeError):
            dt = datetime.now(timezone.utc)
        if dt >= cutoff:
            out.append(it)
    return out
