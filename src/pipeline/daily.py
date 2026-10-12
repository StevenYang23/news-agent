"""Daily pipeline: fetch -> extract/transcribe -> summarize -> rolling retention.

Stateless over ``site/insights.json`` (see src/state.py): the committed JSON is
both the dedup state and the served data, so it works identically locally and
in GitHub Actions with no server or database.
"""
from __future__ import annotations

import logging

from .. import config, state
from ..ingest import fetch, transcribe, youtube
from ..llm import deepseek

log = logging.getLogger("pipeline")

MIN_FEED_CONTENT = 400  # below this, fetch full article text


def _fetch_source(source: dict) -> list[dict]:
    stype = source["type"]
    if stype == "rss" or stype == "podcast":
        items = fetch.fetch_rss(source["feed_url"])
    elif stype == "youtube":
        items = youtube.list_recent_videos(source["url"], config.MAX_ITEMS_PER_SOURCE)
    elif stype == "web":
        log.warning("web scraping not implemented for %s — skipping", source["name"])
        return []
    else:
        log.warning("unknown type %r for %s — skipping", stype, source["name"])
        return []
    return fetch.filter_recent(items, config.LOOKBACK_DAYS)


def _content_for(source: dict, item: dict) -> str | None:
    """Return full text content for an item, or None if unavailable."""
    stype = source["type"]

    if stype == "rss":
        content = item.get("content", "")
        if len(content) < MIN_FEED_CONTENT and item.get("url"):
            try:
                content = fetch.extract_article_text(item["url"]) or content
            except Exception as e:  # noqa: BLE001
                log.info("article fetch failed for %s: %s", item["url"], e)
        return content

    if stype == "podcast":
        if not transcribe.is_available():
            raise RuntimeError("transcription unavailable: faster-whisper not installed")
        enclosure = item.get("enclosure", "")
        if not enclosure:
            raise RuntimeError("no audio enclosure")
        dest = config.AUDIO_DIR / f"{item['guid'].replace('/', '_')}.mp3"
        try:
            transcribe.download_audio(enclosure, str(dest))
            return transcribe.transcribe_audio(str(dest))
        finally:
            if dest.exists():
                try:
                    dest.unlink()
                except OSError:
                    pass

    if stype == "youtube":
        return youtube.get_captions(item["video_id"])

    return item.get("content", "")


def run_pipeline() -> dict:
    sources = config.load_sources()
    active = [s for s in sources if s.get("active")]

    stats = {
        "fetched": 0,
        "new_items": 0,
        "summarized": 0,
        "filtered_us": 0,
        "errors": 0,
        "pruned": 0,
        "sources_done": 0,
        "total": 0,
    }

    insights = state.load()
    guids = state.existing_guids()

    if not deepseek.is_configured():
        log.warning("DEEPSEEK_API_KEY not set — will fetch but not summarize.")

    new_insights: list[dict] = []
    for src in active:
        try:
            items = _fetch_source(src)
        except Exception as e:  # noqa: BLE001
            log.warning("fetch failed for %s: %s", src["name"], e)
            stats["errors"] += 1
            continue
        stats["fetched"] += len(items)
        stats["sources_done"] += 1

        for item in items:
            guid = item["guid"]
            if guid in guids:
                continue
            stats["new_items"] += 1

            try:
                content = _content_for(src, item)
                if not content or len(content.strip()) <= 20:
                    stats["errors"] += 1
                    continue
                if not deepseek.is_configured():
                    continue
                payload = deepseek.summarize(content, item["title"])
                if config.US_EQUITY_ONLY and not payload.get("us_equity_relevant"):
                    stats["filtered_us"] += 1
                    guids.add(guid)  # remember we already judged it
                    continue
                new_insights.append(
                    {
                        "guid": guid,
                        "title": item["title"],
                        "title_zh": payload.get("title_zh", ""),
                        "url": item["url"],
                        "published_at": item["published_at"],
                        "source_name": src["name"],
                        "source_kind": src.get("kind", "article"),
                        "summary_zh": payload.get("summary_zh", ""),
                        "summary_en": payload.get("summary_en", ""),
                        "key_points": payload.get("key_points", []),
                        "tags": payload.get("tags", []),
                        "tickers": payload.get("tickers", []),
                        "sentiment": payload.get("sentiment", "neutral"),
                    }
                )
                guids.add(guid)
                stats["summarized"] += 1
            except Exception as e:  # noqa: BLE001
                log.warning("item failed (%s): %s", (item.get("title") or "")[:50], e)
                stats["errors"] += 1

    combined = state.sort_newest(new_insights + insights)
    before = len(combined)
    combined = state.prune(combined, config.LOOKBACK_DAYS)
    stats["pruned"] = before - len(combined)
    state.save(combined)
    stats["total"] = len(combined)
    return stats
