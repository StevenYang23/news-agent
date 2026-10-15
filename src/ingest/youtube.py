"""YouTube channel ingestion.

Lists recent videos via the channel's official RSS feed (accurate publish
dates + description) and reads auto-captions, with retries and a description
fallback for resilience against YouTube rate limiting.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

import feedparser


def _channel_id(channel_url: str) -> str:
    import yt_dlp  # noqa: PLC0415

    opts = {"quiet": True, "extract_flat": True, "skip_download": True, "playlistend": 1}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)
    cid = info.get("channel_id")
    if not cid:
        raise RuntimeError(f"could not resolve channel id for {channel_url}")
    return cid


def _strip_html(html: str) -> str:
    if not html:
        return ""
    from bs4 import BeautifulSoup  # noqa: PLC0415

    return re.sub(r"\n{3,}", "\n\n", BeautifulSoup(html, "html.parser").get_text("\n")).strip()


def _is_live(title: str) -> bool:
    """Heuristic: treat live streams (title has LIVE / 🔴 / 直播) as skippable."""
    return bool(re.search(r"\blive\b", title, re.IGNORECASE)) or "🔴" in title or "直播" in title


def list_recent_videos(channel_url: str, limit: int = 10, title_filter: str | None = None) -> list[dict]:
    """Return recent videos (optionally filtered by title substring) from the RSS."""
    cid = _channel_id(channel_url)
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
    parsed = feedparser.parse(feed_url)

    videos = []
    for entry in parsed.entries:
        title = entry.get("title", "")
        if _is_live(title):
            continue  # skip live streams
        if title_filter and title_filter.lower() not in title.lower():
            continue
        vid = entry.get("yt_videoid") or (entry.get("id", "").split(":")[-1])
        if not vid:
            continue
        published = None
        if entry.get("published_parsed"):
            published = datetime(*entry["published_parsed"][:6], tzinfo=timezone.utc).isoformat()
        videos.append(
            {
                "guid": "yt:" + vid,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "video_id": vid,
                "published_at": published or datetime.now(timezone.utc).isoformat(),
                "description": _strip_html(entry.get("summary", "") or entry.get("description", "")),
            }
        )
        if len(videos) >= limit:
            break
    return videos


def get_duration(video_id: str) -> int | None:
    """Return video duration in seconds (best-effort via yt-dlp), or None."""
    try:
        import yt_dlp  # noqa: PLC0415

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        return int(info.get("duration") or 0) or None
    except Exception:  # noqa: BLE001
        return None


def get_captions(video_id: str, retries: int = 2) -> str:
    """Fetch YouTube captions, preferring TranscriptAPI (reliable) when configured."""
    from .. import config  # noqa: PLC0415

    # 1) TranscriptAPI (cloud, reliable)
    if config.TRANSCRIPT_API_KEY:
        for attempt in range(retries + 1):
            try:
                return _captions_transcriptapi(video_id)
            except OutOfCredits:
                raise  # hard stop: out of credits, don't fall back
            except Exception as e:  # noqa: BLE001
                if attempt >= retries:
                    log_fallback(video_id, e)
                    break
                time.sleep(2 * (attempt + 1))

    # 2) Free youtube-transcript-api fallback
    from youtube_transcript_api import YouTubeTranscriptApi  # noqa: PLC0415

    last = None
    for attempt in range(retries + 1):
        try:
            api = YouTubeTranscriptApi()
            transcript = api.fetch(video_id)
            parts = [re.sub(r"\s+", " ", seg.text).strip() for seg in transcript]
            return " ".join(p for p in parts if p)
        except Exception as e:  # noqa: BLE001
            last = e
            if attempt < retries:
                time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"No captions for {video_id}: {last}")


def _captions_transcriptapi(video_id: str) -> str:
    import requests  # noqa: PLC0415

    from .. import config  # noqa: PLC0415

    resp = requests.get(
        "https://transcriptapi.com/api/v2/youtube/transcript",
        params={"video_url": video_id, "format": "text", "include_timestamp": "false"},
        headers={"Authorization": f"Bearer {config.TRANSCRIPT_API_KEY}"},
        timeout=60,
    )
    if resp.status_code == 402:
        raise OutOfCredits("TranscriptAPI credits exhausted (HTTP 402)")
    resp.raise_for_status()
    data = resp.json()
    text = data.get("transcript", "")
    if isinstance(text, list):
        text = " ".join(s.get("text", "") for s in text if isinstance(s, dict))
    text = (text or "").strip()
    if not text:
        raise RuntimeError("empty transcript from TranscriptAPI")
    return text


def log_fallback(video_id: str, err: Exception) -> None:
    import logging  # noqa: PLC0415

    logging.getLogger("pipeline").info(
        "TranscriptAPI failed for %s (%s) — falling back to youtube-transcript-api",
        video_id, str(err)[:80],
    )


class OutOfCredits(Exception):
    """TranscriptAPI returned 402 — the account is out of credits."""
