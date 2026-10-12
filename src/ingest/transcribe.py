"""Audio transcription via faster-whisper (optional dependency)."""
from __future__ import annotations

import requests

from .. import config

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0"
}

_model = None


def is_available() -> bool:
    """Whether faster-whisper is installed (needed for audio podcasts)."""
    try:
        import faster_whisper  # noqa: F401
        return True
    except ImportError:
        return False


def _get_model():
    global _model
    if _model is None:
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "faster-whisper is not installed. Run `pip install faster-whisper` "
                "(ctranslate2 ships cp314 wheels, so it works on Python 3.14)."
            ) from e
        _model = WhisperModel("small", device="cpu", compute_type="int8")
    return _model


def download_audio(url: str, dest: str) -> str:
    """Download an audio enclosure to disk."""
    resp = requests.get(url, headers=_HEADERS, timeout=300, stream=True)
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 16):
            f.write(chunk)
    return dest


def transcribe_audio(path: str) -> str:
    """Transcribe a local audio file to text."""
    model = _get_model()
    segments, _info = model.transcribe(path, language="en")
    return " ".join(seg.text.strip() for seg in segments)
