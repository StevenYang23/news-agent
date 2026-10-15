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


def list_recent_videos(channel_url: str, limit: int = 10) -> list[dict]:
    """Return recent videos with accurate publish dates + description from the RSS."""
    cid = _channel_id(channel_url)
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
    parsed = feedparser.parse(feed_url)

    videos = []
    for entry in parsed.entries[:limit]:
        vid = entry.get("yt_videoid") or (entry.get("id", "").split(":")[-1])
        if not vid:
            continue
        published = None
        if entry.get("published_parsed"):
            published = datetime(*entry["published_parsed"][:6], tzinfo=timezone.utc).isoformat()
        videos.append(
            {
                "guid": "yt:" + vid,
                "title": entry.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "video_id": vid,
                "published_at": published or datetime.now(timezone.utc).isoformat(),
                "description": _strip_html(entry.get("summary", "") or entry.get("description", "")),
            }
        )
    return videos


def get_captions(video_id: str, retries: int = 2) -> str:
    """Fetch YouTube captions, preferring Supadata (reliable) when configured."""
    from .. import config  # noqa: PLC0415

    # 1) Supadata API (cloud, reliable, AI fallback when no captions)
    if config.SUPADATA_API_KEY:
        for attempt in range(retries + 1):
            try:
                return _captions_supadata(video_id)
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


def _captions_supadata(video_id: str) -> str:
    import requests  # noqa: PLC0415

    from .. import config  # noqa: PLC0415

    resp = requests.get(
        "https://api.supadata.ai/v1/youtube/transcript",
        params={"url": f"https://www.youtube.com/watch?v={video_id}", "text": "true"},
        headers={"x-api-key": config.SUPADATA_API_KEY},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data.get("content", "")
    if isinstance(content, list):
        content = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
    text = (content or "").strip()
    if not text:
        raise RuntimeError("empty transcript from Supadata")
    return text


def log_fallback(video_id: str, err: Exception) -> None:
    import logging  # noqa: PLC0415

    logging.getLogger("pipeline").info(
        "Supadata failed for %s (%s) — falling back to youtube-transcript-api",
        video_id, str(err)[:80],
    )
