#!/usr/bin/env python3
"""Pre-flight checks for video-lens: URL→ID, request parsing, duplicate detection,
start epoch, machine capabilities.

Usage: python3 preflight.py URL_OR_ID [REQUEST]

URL_OR_ID may be:
- A YouTube URL (watch / youtu.be / embed / live)
- A bare 11-character video ID
- Either of those followed by the user's request in a single argv
  ("dQw4w9WgXcQ es", "https://youtu.be/… in Spanish, focus on pricing")

The request is read for a transcript language: a language name in English or in
the language itself ("Spanish", "español"), or a code ("es", "pt-BR") given
alone or with filler words ("in es", "de subtitles"). Words other than the
language and filler make the whole request an EXTRA_REQUEST.

Stdout on success (lines that apply only):
    VIDEO_ID: <11 chars>
    LANG_CODE: <code or empty>
    EXTRA_REQUEST: <the request verbatim>   # when it asks for more than a language
    CAPABILITIES: a, b, …        # whisper (Apple Silicon: the local fallback can run),
                                 # mlx-whisper, ffmpeg, yt-dlp | yt-dlp-outdated; may be empty
    START_EPOCH: <int>
    SCRIPTS_DIR: <absolute>      # directory holding the video-lens scripts
    PAYLOAD_PATH: <absolute>     # $XDG_CACHE_HOME/video-lens/payloads/payload-XXXX/payload.json (0700 parent, file not pre-created)
    DUPLICATE_PATH: <absolute>   # newest match by mtime, if any
    EXISTING_TAGS: a, b, c, …    # top tags across saved reports (omitted when no manifest yet)

Stderr + non-zero exit on:
    ERROR:SHORTS_NOT_SUPPORTED <url>
    ERROR:INVALID_INPUT <reason>
"""
import argparse
import importlib.util
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import time
from urllib.parse import parse_qs, urlparse

from transcribe_local import MIN_YTDLP, whisper_platform_supported, ytdlp_version

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
REPORTS_DIR = pathlib.Path.home() / "Downloads" / "video-lens" / "reports"
MANIFEST_PATH = pathlib.Path.home() / "Downloads" / "video-lens" / "manifest.json"
# Deliberately outside ~/Downloads/video-lens: serve_report.sh serves that whole
# tree over loopback, and payload dirs hold the full generated content of every run.
PAYLOAD_BASE_DIR = (
    pathlib.Path(os.environ.get("XDG_CACHE_HOME") or (pathlib.Path.home() / ".cache"))
    / "video-lens" / "payloads"
)
LEGACY_PAYLOAD_BASE_DIR = pathlib.Path.home() / "Downloads" / "video-lens" / ".tmp"
PAYLOAD_TTL_SECONDS = 7 * 24 * 60 * 60  # sweep payload-* dirs older than ~7 days
EXISTING_TAGS_LIMIT = 40  # how many of the most-common tags to feed back to Step 3

# English names, then each language's own name (with and without accents).
# "polish" and "indonesia" are left out: in a request they are more often a verb
# or a country than a transcript language.
LANGUAGE_MAP = {
    "english": "en",
    "spanish": "es", "español": "es", "espanol": "es", "castellano": "es",
    "french": "fr", "français": "fr", "francais": "fr",
    "german": "de", "deutsch": "de",
    "italian": "it", "italiano": "it",
    "portuguese": "pt", "português": "pt", "portugues": "pt",
    "dutch": "nl", "nederlands": "nl",
    "swedish": "sv", "svenska": "sv",
    "norwegian": "no", "norsk": "no",
    "danish": "da", "dansk": "da",
    "finnish": "fi", "suomi": "fi",
    "polski": "pl",
    "czech": "cs", "čeština": "cs", "cestina": "cs",
    "turkish": "tr", "türkçe": "tr", "turkce": "tr",
    "greek": "el", "ελληνικά": "el",
    "russian": "ru", "русский": "ru",
    "ukrainian": "uk", "українська": "uk",
    "arabic": "ar", "العربية": "ar",
    "hindi": "hi", "हिन्दी": "hi", "हिंदी": "hi",
    "indonesian": "id",
    "vietnamese": "vi",
    "thai": "th", "ไทย": "th",
    "chinese": "zh", "mandarin": "zh", "中文": "zh",
    "japanese": "ja", "日本語": "ja",
    "korean": "ko", "한국어": "ko",
}
# Words that may surround a language without asking for anything else.
REQUEST_FILLER = {
    "a", "an", "and", "the", "in", "into", "with", "on", "use", "using", "please", "pls",
    "language", "lang", "subtitles", "subtitle", "subs", "captions", "caption", "cc",
    "transcript", "track", "version", "audio",
    "en", "auf", "im", "mit", "untertitel", "sous-titres", "con", "subtítulos",
}
REQUEST_WORD_RE = re.compile(r"[^\W_]+(?:-[^\W_]+)*")
LANG_CODE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")
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


def parse_request(raw: str) -> tuple[str, str]:
    """Split the user's request into (language code, extra request).

    A language name counts anywhere in the request. A code counts only when it
    stands alone or among filler words: inside a sentence, two-letter words are
    too often ordinary words ("de" in "resumen de la charla", "it" in "focus on it").
    Unknown codes pass through; fetch_transcript.py emits LANG_WARN: for them.

    The extra request is the whole request, verbatim, whenever it holds words
    other than the language and filler; the agent reads it in full.
    """
    text = " ".join(raw.split())
    words = REQUEST_WORD_RE.findall(text.lower())
    if not words:
        return "", ""

    lang_word = next((w for w in words if w in LANGUAGE_MAP), None)
    if lang_word is not None:
        lang_code = LANGUAGE_MAP[lang_word]
    elif len(words) == 1 and LANG_CODE_RE.fullmatch(words[0]):
        lang_word = lang_code = words[0]
    else:
        content = [w for w in words if w not in REQUEST_FILLER]
        if len(content) == 1 and LANG_CODE_RE.fullmatch(content[0]):
            lang_word = lang_code = content[0]
        else:
            lang_code = ""

    rest = [w for w in words if w != lang_word and w not in REQUEST_FILLER]
    return lang_code, (text if rest else "")


def probe_capabilities() -> list[str]:
    """What this machine can run, so the skill offers the local fallback only
    where it works (025 R6/S5).

    `whisper` means mlx-whisper can run here, installed or not; `mlx-whisper`
    that it is installed. The yt-dlp version is checked only where the fallback
    can run, because only its audio download needs the newer release; elsewhere
    the check would add a subprocess to every run for nothing.
    """
    caps = []
    whisper = whisper_platform_supported()
    if whisper:
        caps.append("whisper")
        if importlib.util.find_spec("mlx_whisper") is not None:
            caps.append("mlx-whisper")
    if shutil.which("ffmpeg"):
        caps.append("ffmpeg")
    if shutil.which("yt-dlp"):
        found = ytdlp_version() if whisper else None
        caps.append("yt-dlp-outdated" if found and found[0] < MIN_YTDLP else "yt-dlp")
    return caps


def sweep_stale_payloads(base_dir: pathlib.Path, now: float | None = None) -> None:
    """Delete `payload-*` dirs older than PAYLOAD_TTL_SECONDS.

    Each run leaves a payload-XXXX/ dir holding the full report content; nothing
    else cleans them, so they accumulate (disk clutter + summaries persisting
    outside the reports dir). Best-effort: any error per-dir is ignored.
    """
    if not base_dir.is_dir():
        return
    cutoff = (time.time() if now is None else now) - PAYLOAD_TTL_SECONDS
    for entry in base_dir.glob("payload-*"):
        try:
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def _normalize_tags(tags: list) -> list[str]:
    """Fold trivial tag variants: lowercase, hyphen→space, collapse whitespace,
    dedupe (first-seen order). Non-str entries are dropped. Kept byte-identical to
    `build_index._normalize_tags` and `render_report._normalize_tags` so the
    feedback loop counts the same shape the gallery and new reports store.
    """
    seen = set()
    out = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        norm = " ".join(tag.replace("-", " ").lower().split())
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def read_existing_tags(
    manifest_path: pathlib.Path = MANIFEST_PATH, limit: int = EXISTING_TAGS_LIMIT
) -> list[str]:
    """Return the most-common tags across saved reports, most-frequent first.

    Feeds Step 3's tag rule so new reports prefer the established vocabulary
    instead of inventing near-duplicates (the gallery's filter chips fragment
    otherwise). Best-effort: a missing or unreadable manifest yields an empty
    list — fresh installs have no manifest.json yet, and that must never fail the
    run. Per report, tags are normalized and deduped before counting, so a single
    report using both `ai` and `AI-Coding`/`ai coding` contributes one count each.
    """
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    counts: dict[str, int] = {}
    for report in data.get("reports", []):
        if not isinstance(report, dict):
            continue
        tags = report.get("tags")
        if not isinstance(tags, list):
            continue
        for norm in _normalize_tags(tags):
            counts[norm] = counts.get(norm, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [tag for tag, _ in ranked[:limit]]


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
    parser.add_argument("request", nargs="?", default="")
    args = parser.parse_args()

    raw = args.url_or_id.strip()
    request = args.request
    if " " in raw and not request:
        first, _, rest = raw.partition(" ")
        raw, request = first, rest.strip()

    video_id, err = extract_video_id(raw)
    if err == "SHORTS_NOT_SUPPORTED":
        print(f"ERROR:SHORTS_NOT_SUPPORTED {raw}", file=sys.stderr)
        return 1
    if err:
        print(f"ERROR:INVALID_INPUT could not extract video id from {raw!r}", file=sys.stderr)
        return 1

    lang_code, extra_request = parse_request(request)
    start_epoch = int(time.time())
    dup = find_duplicate(video_id)

    PAYLOAD_BASE_DIR.mkdir(parents=True, exist_ok=True)
    sweep_stale_payloads(PAYLOAD_BASE_DIR)
    # Payloads written before the move still sit inside the served tree; keep
    # ageing them out and drop the directory once it is empty.
    sweep_stale_payloads(LEGACY_PAYLOAD_BASE_DIR)
    try:
        if LEGACY_PAYLOAD_BASE_DIR.is_dir() and not any(LEGACY_PAYLOAD_BASE_DIR.iterdir()):
            LEGACY_PAYLOAD_BASE_DIR.rmdir()
    except OSError:
        pass
    payload_dir = tempfile.mkdtemp(prefix="payload-", dir=str(PAYLOAD_BASE_DIR))
    payload_path = pathlib.Path(payload_dir) / "payload.json"

    scripts_dir = pathlib.Path(__file__).resolve().parent

    print(f"VIDEO_ID: {video_id}")
    print(f"LANG_CODE: {lang_code}")
    if extra_request:
        print(f"EXTRA_REQUEST: {extra_request}")
    print(f"CAPABILITIES: {', '.join(probe_capabilities())}")
    print(f"START_EPOCH: {start_epoch}")
    print(f"SCRIPTS_DIR: {scripts_dir}")
    print(f"PAYLOAD_PATH: {payload_path}")
    if dup is not None:
        print(f"DUPLICATE_PATH: {dup}")
    existing_tags = read_existing_tags(MANIFEST_PATH)
    if existing_tags:
        print(f"EXISTING_TAGS: {', '.join(existing_tags)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
