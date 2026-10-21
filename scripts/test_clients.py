"""One-off CI diagnostic: try every yt-dlp player client and report which are blocked.

Run from GitHub Actions (datacenter IP) to see if any client bypasses YouTube's
"Sign in to confirm you're not a bot" check.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yt_dlp  # noqa: E402

VIDEO = "jNQXAC9IVRw"  # "Me at the zoo" — stable, always-public video

CLIENTS = [
    "web",
    "web_safari",
    "web_embedded",
    "mweb",
    "ios",
    "android",
    "android_vr",
    "tv",
    "tv_simply",
    "tv_embedded",
]


def main() -> None:
    results = {}
    for c in CLIENTS:
        try:
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "extractor_args": {"youtube": {"player_client": [c]}},
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={VIDEO}", download=False)
            dur = info.get("duration")
            subs = bool(
                (info.get("subtitles") or {}).get("en")
                or (info.get("automatic_captions") or {}).get("en")
            )
            results[c] = f"OK (dur={dur}s, subs={subs})"
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if "not a bot" in msg:
                results[c] = "BLOCKED (not a bot)"
            else:
                results[c] = f"ERROR {type(e).__name__}: {msg[:80]}"
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
