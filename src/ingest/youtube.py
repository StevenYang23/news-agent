"""YouTube channel ingestion: list recent videos and read auto-captions."""
from __future__ import annotations

import re
from datetime import datetime, timezone


def list_recent_videos(channel_url: str, limit: int = 10) -> list[dict]:
    """Return recent videos from a channel using yt-dlp (flat, no download)."""
    import yt_dlp  # noqa: PLC0415

    opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "playlistend": limit,
        "skip_download": True,
    }
    url = channel_url.rstrip("/") + "/videos"
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    videos = []
    for entry in info.get("entries", []) or []:
        if not entry:
            continue
        vid = entry.get("id")
        if not vid:
            continue
        published = None
        if entry.get("timestamp"):
            published = datetime.fromtimestamp(entry["timestamp"], tz=timezone.utc).isoformat()
        videos.append(
            {
                "guid": "yt:" + vid,
                "title": entry.get("title", ""),
                "url": f"https://www.youtube.com/watch?v={vid}",
                "video_id": vid,
                "published_at": published or datetime.now(timezone.utc).isoformat(),
            }
        )
    return videos


def get_captions(video_id: str) -> str:
    """Fetch and join YouTube auto-generated captions for a video."""
    from youtube_transcript_api import YouTubeTranscriptApi  # noqa: PLC0415

    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"No captions for {video_id}: {e}") from e

    parts = []
    for seg in transcript:
        text = re.sub(r"\s+", " ", seg.text).strip()
        if text:
            parts.append(text)
    return " ".join(parts)
