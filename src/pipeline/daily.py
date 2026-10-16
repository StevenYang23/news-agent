"""Daily pipeline: fetch -> extract/transcribe -> summarize -> rolling retention.

Stateless over ``site/insights.json`` (see src/state.py): the committed JSON is
both the dedup state and the served data, so it works identically locally and
in GitHub Actions with no server or database.
"""
from __future__ import annotations

import logging
import time

from .. import config, state
from ..ingest import fetch, transcribe, web, youtube
from ..llm import deepseek

log = logging.getLogger("pipeline")

MIN_FEED_CONTENT = 400  # below this, fetch full article text

_transcript_used = 0  # transcripts consumed this run (module-level)
_transcripts_exhausted = False  # set when TranscriptAPI returns 402


def _allow_transcript() -> bool:
    """Return True if we're under the monthly transcript budget (and count it)."""
    global _transcript_used
    if _transcripts_exhausted:
        return False
    if state.usage_count() + _transcript_used < config.TRANSCRIPT_MONTHLY_BUDGET:
        _transcript_used += 1
        return True
    return False


def _fetch_source(source: dict) -> list[dict]:
    stype = source["type"]
    if stype == "rss":
        items = fetch.fetch_rss(source["feed_url"])
    elif stype == "podcast":
        items = fetch.fetch_rss(source["feed_url"])
        # Transcribing audio is expensive, so cap the number of episodes per run.
        items = items[: source.get("max_items", 3)]
    elif stype == "youtube":
        items = youtube.list_recent_videos(
            source["url"],
            source.get("max_items", config.MAX_ITEMS_PER_SOURCE),
            title_filter=source.get("title_filter"),
        )
    elif stype == "web":
        scraper = source.get("scraper", "")
        if scraper == "macrovoices":
            items = web.fetch_macrovoices(source.get("max_items", 5))
        else:
            log.warning("unknown web scraper %r for %s — skipping", scraper, source["name"])
            return []
    else:
        log.warning("unknown type %r for %s — skipping", stype, source["name"])
        return []
    return fetch.filter_recent(items, config.LOOKBACK_DAYS)


def _content_for(source: dict, item: dict) -> str | None:
    """Return full text content for an item, or None if unavailable."""
    stype = source["type"]

    if stype == "web":
        return web.extract_pdf_text(item["pdf_url"])

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
        return _youtube_content(item)

    return item.get("content", "")


def _youtube_content(item: dict) -> str | None:
    """YouTube content: transcript if under budget (or a long video), else description."""
    global _transcripts_exhausted
    desc = (item.get("description") or "").strip()

    if config.USE_YOUTUBE_CAPTIONS:
        if _allow_transcript():
            time.sleep(2)
            try:
                return youtube.get_captions(item["video_id"])
            except youtube.OutOfCredits:
                _transcripts_exhausted = True
                log.warning("TranscriptAPI out of credits — using descriptions for the rest of this run")
            except Exception as e:  # noqa: BLE001
                if len(desc) > 40:
                    return desc
                raise e
        else:
            # Over budget: only fetch transcripts for long videos (> MIN_TRANSCRIPT_DURATION).
            dur = youtube.get_duration(item["video_id"])
            if dur is None or dur >= config.MIN_TRANSCRIPT_DURATION:
                time.sleep(2)
                try:
                    return youtube.get_captions(item["video_id"])
                except youtube.OutOfCredits:
                    _transcripts_exhausted = True
                    log.warning("TranscriptAPI out of credits — using descriptions for the rest of this run")
                except Exception as e:  # noqa: BLE001
                    if len(desc) > 40:
                        return desc
                    raise e

    if len(desc) > 40:
        return desc
    raise RuntimeError("no description for youtube video")


def run_pipeline() -> dict:
    sources = config.load_sources()
    global _transcript_used, _transcripts_exhausted
    _transcript_used = 0
    _transcripts_exhausted = False
    active = [s for s in sources if s.get("active")]
    # Process higher-priority sources first (lower `priority` = more important).
    active.sort(key=lambda s: s.get("priority", 99))

    stats = {
        "fetched": 0,
        "new_items": 0,
        "summarized": 0,
        "filtered_us": 0,
        "filtered_econ": 0,
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
                if config.US_EQUITY_ONLY and not payload.get("us_equity_relevant") and not src.get("include_all"):
                    stats["filtered_us"] += 1
                    guids.add(guid)  # remember we already judged it
                    continue
                if src.get("require_econ_tech") and not payload.get("econ_tech_relevant"):
                    stats["filtered_econ"] += 1
                    guids.add(guid)
                    continue
                categories = list(payload.get("categories", ["other"]))
                force = src.get("force_category")
                if force and force not in categories:
                    categories.append(force)
                new_insights.append(
                    {
                        "guid": guid,
                        "title": item["title"],
                        "title_zh": payload.get("title_zh", ""),
                        "url": item["url"],
                        "published_at": item["published_at"],
                        "source_name": src["name"],
                        "source_kind": src.get("kind", "article"),
                        "categories": categories,
                        "summary_zh": payload.get("summary_zh", ""),
                        "summary_en": payload.get("summary_en", ""),
                        "detail_zh": payload.get("detail_zh", ""),
                        "detail_en": payload.get("detail_en", ""),
                        "conclusion_zh": payload.get("conclusion_zh", ""),
                        "conclusion_en": payload.get("conclusion_en", ""),
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
    pruned = before - len(combined)
    stats["pruned"] = pruned
    stats["total"] = len(combined)
    # Only persist insights when something actually changed, so hourly runs
    # with no new content don't trigger a spurious commit + deploy.
    if new_insights or pruned > 0:
        state.save(combined)
    state.save_sources(sources)
    if _transcript_used > 0:
        state.add_usage(_transcript_used)
        stats["transcripts_used"] = _transcript_used
    return stats
