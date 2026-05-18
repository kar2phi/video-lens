#!/usr/bin/env python3
"""Pre-flight checks for video-lens: URL→ID, language mapping, duplicate detection, start epoch.

Usage: python3 preflight.py URL_OR_ID [LANG_REQUEST]

URL_OR_ID may be:
- A YouTube URL (watch / youtu.be / embed / live)
- A bare 11-character video ID
- A bare ID followed by a 2–3 char language hint (e.g. "dQw4w9WgXcQ es") — passed as a single argv

Stdout on success (lines that apply only):
    VIDEO_ID: <11 chars>
    LANG_CODE: <code or empty>
    START_EPOCH: <int>
    SCRIPTS_DIR: <absolute>      # directory holding the video-lens scripts
    PAYLOAD_PATH: <absolute>     # ~/Downloads/video-lens/.tmp/payload-XXXX/payload.json (0700 parent, file not pre-created)
    DUPLICATE_PATH: <absolute>   # newest match by mtime, if any

Stderr + non-zero exit on:
    ERROR:SHORTS_NOT_SUPPORTED <url>
    ERROR:INVALID_INPUT <reason>
"""
import argparse
import pathlib
import re
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlparse

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
REPORTS_DIR = pathlib.Path.home() / "Downloads" / "video-lens" / "reports"
PAYLOAD_BASE_DIR = pathlib.Path.home() / "Downloads" / "video-lens" / ".tmp"

LANGUAGE_MAP = {
    "english": "en", "spanish": "es", "french": "fr", "german": "de",
    "japanese": "ja", "portuguese": "pt", "italian": "it",
    "chinese": "zh", "korean": "ko", "russian": "ru",
}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
YOUTUBE_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}


def extract_video_id(raw: str) -> tuple[str, str | None]:
    """Return (video_id, error_code). error_code is None on success."""
    raw = raw.strip()
    if VIDEO_ID_RE.fullmatch(raw):
        return raw, None

    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw.lstrip("/")

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if "/shorts/" in parsed.path:
        return "", "SHORTS_NOT_SUPPORTED"

    if host in YOUTUBE_SHORT_HOSTS:
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif host in YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        elif parsed.path.startswith("/embed/") or parsed.path.startswith("/live/"):
            parts = parsed.path.strip("/").split("/", 2)
            candidate = parts[1] if len(parts) >= 2 else ""
        else:
            return "", "INVALID_INPUT"
    else:
        return "", "INVALID_INPUT"

    if VIDEO_ID_RE.fullmatch(candidate):
        return candidate, None
    return "", "INVALID_INPUT"


def map_language(raw: str) -> str:
    """Map a name (english) or a short code (en) to a code. No format validation.

    Unknown codes pass through; fetch_transcript.py already emits LANG_WARN: when
    youtube-transcript-api rejects them, so a second validation layer here is dead weight.
    """
    raw = raw.strip().lower()
    if not raw:
        return ""
    return LANGUAGE_MAP.get(raw, raw)


def find_duplicate(video_id: str) -> pathlib.Path | None:
    if not REPORTS_DIR.is_dir():
        return None
    matches = sorted(
        REPORTS_DIR.glob(f"*video-lens*{video_id}*.html"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url_or_id")
    parser.add_argument("lang_request", nargs="?", default="")
    args = parser.parse_args()

    raw = args.url_or_id.strip()
    lang_request = args.lang_request
    if " " in raw and not lang_request:
        first, _, rest = raw.partition(" ")
        raw, lang_request = first, rest.strip()

    video_id, err = extract_video_id(raw)
    if err == "SHORTS_NOT_SUPPORTED":
        print(f"ERROR:SHORTS_NOT_SUPPORTED {raw}", file=sys.stderr)
        return 1
    if err:
        print(f"ERROR:INVALID_INPUT could not extract video id from {raw!r}", file=sys.stderr)
        return 1

    lang_code = map_language(lang_request)
    start_epoch = int(time.time())
    dup = find_duplicate(video_id)

    PAYLOAD_BASE_DIR.mkdir(parents=True, exist_ok=True)
    payload_dir = tempfile.mkdtemp(prefix="payload-", dir=str(PAYLOAD_BASE_DIR))
    payload_path = pathlib.Path(payload_dir) / "payload.json"

    scripts_dir = pathlib.Path(__file__).resolve().parent

    print(f"VIDEO_ID: {video_id}")
    print(f"LANG_CODE: {lang_code}")
    print(f"START_EPOCH: {start_epoch}")
    print(f"SCRIPTS_DIR: {scripts_dir}")
    print(f"PAYLOAD_PATH: {payload_path}")
    if dup is not None:
        print(f"DUPLICATE_PATH: {dup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
