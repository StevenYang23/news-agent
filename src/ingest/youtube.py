"""YouTube channel ingestion.

Lists recent videos via the channel's official RSS feed (accurate publish
dates + description) and reads auto-captions, with retries and a description
fallback for resilience against YouTube rate limiting.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from pathlib import Path

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


def _parse_relative(text: str) -> str:
    """Parse a relative time like '2 weeks ago' into an approximate ISO date."""
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    now = datetime.now(timezone.utc)
    m = re.search(r"(\d+)\s*(second|minute|hour|day|week|month|year)s?\s*ago", text, re.IGNORECASE)
    if not m:
        return now.isoformat()
    n = int(m.group(1))
    unit = m.group(2).lower()
    delta = {
        "second": timedelta(seconds=n),
        "minute": timedelta(minutes=n),
        "hour": timedelta(hours=n),
        "day": timedelta(days=n),
        "week": timedelta(weeks=n),
        "month": timedelta(days=30 * n),
        "year": timedelta(days=365 * n),
    }.get(unit, timedelta())
    return (now - delta).isoformat()


_channel_videos_cache: dict[str, list[dict]] = {}


def _list_channel_videos(channel_url: str, limit: int) -> list[dict]:
    """List a channel's recent videos via TranscriptAPI (100+ entries, cached per run)."""
    from .. import config  # noqa: PLC0415

    if channel_url in _channel_videos_cache:
        return _channel_videos_cache[channel_url][:limit]

    import requests  # noqa: PLC0415

    resp = requests.get(
        "https://transcriptapi.com/api/v2/youtube/channel/videos",
        params={"channel": channel_url},
        headers={"Authorization": f"Bearer {config.TRANSCRIPT_API_KEY}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    videos = []
    for v in data.get("results", []):
        vid = v.get("videoId")
        title = v.get("title", "")
        if not vid or _is_live(title):
            continue
        videos.append(
            {
                "guid": "yt:" + vid,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "video_id": vid,
                "published_at": _parse_relative(v.get("publishedTimeText", "")),
                "description": "",  # channel/videos doesn't return descriptions
            }
        )
    _channel_videos_cache[channel_url] = videos
    return videos[:limit]


def list_recent_videos(channel_url: str, limit: int = 10, title_filter: str | None = None) -> list[dict]:
    """Return recent videos from the channel RSS (free, 15 entries).

    Title filtering is applied to the RSS entries (used for the Bloomberg podcasts).
    """
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


def _cookies() -> str | None:
    """Return the path to a YouTube cookies.txt if configured and present."""
    from .. import config  # noqa: PLC0415

    if not config.YOUTUBE_COOKIES_FILE:
        return None
    p = Path(config.YOUTUBE_COOKIES_FILE)
    if not p.is_absolute():
        p = config.ROOT / p
    return str(p) if p.exists() else None


def _ytdlp_opts() -> dict:
    """Base yt-dlp options shared by duration lookup and caption download."""
    opts: dict = {"quiet": True, "no_warnings": True, "skip_download": True}
    cookies = _cookies()
    if cookies:
        opts["cookiefile"] = cookies
    return opts


def get_duration(video_id: str) -> int | None:
    """Return video duration in seconds (best-effort via yt-dlp), or None."""
    try:
        import yt_dlp  # noqa: PLC0415

        with yt_dlp.YoutubeDL(_ytdlp_opts()) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
        return int(info.get("duration") or 0) or None
    except Exception:  # noqa: BLE001
        return None


RETRYABLE_STATUS = {408, 429, 503}  # transient: retry after a short delay


class TranscriptError(Exception):
    """TranscriptAPI returned an error. Carries the HTTP status + machine code."""

    def __init__(self, status_code: int, code: str, message: str):
        self.status_code = status_code
        self.code = code
        super().__init__(message or f"HTTP {status_code}")


class OutOfCredits(TranscriptError):
    """TranscriptAPI returned 402 — the account is out of credits."""


def get_captions(video_id: str, retries: int = 2) -> str:
    """Fetch YouTube captions: yt-dlp (free) → TranscriptAPI (cloud) → youtube-transcript-api."""
    from .. import config  # noqa: PLC0415

    # 1) yt-dlp with cookies (free) — works in CI once cookies are provided
    if _cookies():
        try:
            return _captions_ytdlp(video_id)
        except Exception as e:  # noqa: BLE001
            log_fallback(video_id, e)

    # 2) TranscriptAPI (cloud, reliable)
    if config.TRANSCRIPT_API_KEY:
        for attempt in range(retries + 1):
            try:
                return _captions_transcriptapi(video_id)
            except OutOfCredits:
                raise  # hard stop: out of credits, don't fall back
            except TranscriptError as e:
                # Retry only transient errors (408/429/503); permanent errors fall through.
                if e.status_code in RETRYABLE_STATUS and attempt < retries:
                    time.sleep(2 * (attempt + 1))
                    continue
                log_fallback(video_id, e)
                break
            except Exception as e:  # noqa: BLE001  (network etc.)
                if attempt >= retries:
                    log_fallback(video_id, e)
                    break
                time.sleep(2 * (attempt + 1))

    # 3) Free youtube-transcript-api fallback
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


def _captions_ytdlp(video_id: str) -> str:
    """Fetch captions for free via yt-dlp (cookies needed to bypass CI bot checks)."""
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    import yt_dlp  # noqa: PLC0415

    tmpdir = tempfile.mkdtemp(prefix="ytdlp_subs_")
    try:
        opts = dict(_ytdlp_opts())
        opts.update(
            {
                "writesubtitles": True,
                "writeautosubtitles": True,
                "subtitleslangs": ["en"],
                "outtmpl": str(Path(tmpdir) / "%(id)s.%(ext)s"),
            }
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

        files = [p for p in Path(tmpdir).iterdir() if p.suffix in (".vtt", ".srt")]
        if not files:
            raise RuntimeError("yt-dlp produced no subtitle file")
        text = _parse_subtitle_file(str(files[0]))
        if not text.strip():
            raise RuntimeError("empty subtitle from yt-dlp")
        return text
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _parse_subtitle_file(path: str) -> str:
    """Extract plain text from a .vtt/.srt subtitle file."""
    with open(path, encoding="utf-8", errors="replace") as f:
        content = f.read()
    lines = []
    for line in content.splitlines():
        s = line.strip()
        if not s:
            continue
        if "-->" in s:  # timestamp line
            continue
        if s.startswith(("WEBVTT", "Kind:", "Language:")):
            continue
        s = re.sub(r"<[^>]+>", "", s)  # strip inline tags
        s = re.sub(r"\s+", " ", s).strip()
        if s:
            lines.append(s)
    return " ".join(lines)


def _captions_transcriptapi(video_id: str) -> str:
    import requests  # noqa: PLC0415

    from .. import config  # noqa: PLC0415

    resp = requests.get(
        "https://transcriptapi.com/api/v2/youtube/transcript",
        params={"video_url": video_id, "format": "text", "include_timestamp": "false"},
        headers={"Authorization": f"Bearer {config.TRANSCRIPT_API_KEY}"},
        timeout=60,
    )

    if resp.status_code == 200:
        data = resp.json()
        text = data.get("transcript", "")
        if isinstance(text, list):
            text = " ".join(s.get("text", "") for s in text if isinstance(s, dict))
        text = (text or "").strip()
        if not text:
            raise TranscriptError(200, "empty", "empty transcript from TranscriptAPI")
        return text

    # error response — parse the machine-readable code if present
    code, detail = "", ""
    try:
        body = resp.json()
        code = body.get("code", "")
        detail = body.get("detail", "")
    except Exception:  # noqa: BLE001
        pass

    if resp.status_code == 402:
        raise OutOfCredits(resp.status_code, code, detail or "credits exhausted")
    raise TranscriptError(resp.status_code, code, detail or f"HTTP {resp.status_code}")


def log_fallback(video_id: str, err: Exception) -> None:
    import logging  # noqa: PLC0415

    logging.getLogger("pipeline").info(
        "TranscriptAPI failed for %s (%s) — falling back to youtube-transcript-api",
        video_id, str(err)[:80],
    )
