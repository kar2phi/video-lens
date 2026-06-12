#!/usr/bin/env python3
"""Fetch enriched YouTube metadata via yt-dlp.

Usage: python3 fetch_metadata.py VIDEO_ID
"""
import argparse
import html
import json
import re
import subprocess
import sys


def _linkify(line):
    parts = []
    last = 0
    for m in re.finditer(r"https?://\S+", line):
        parts.append(html.escape(line[last:m.start()]))
        url = m.group()
        parts.append(
            f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
            f"{html.escape(url)}</a>"
        )
        last = m.end()
    parts.append(html.escape(line[last:]))
    return "".join(parts)


def _format_views(vc):
    if vc is None:
        return ""
    return (f"{vc/1e6:.1f}M views" if vc >= 1e6
            else f"{vc/1e3:.0f}K views" if vc >= 1e3
            else f"{vc} views")


def _format_duration(dur_s):
    h, rem = divmod(int(dur_s or 0), 3600)
    m2 = rem // 60
    return f"{h}h {m2}m" if h > 0 else f"{m2} min"


def _primary_lang(code):
    return (code or "").split("-")[0].split("_")[0].lower()


def _detect_language(data):
    """Primary ISO-639-1 language subtag from a yt-dlp info dict, or ''."""
    lang = _primary_lang(data.get("language"))
    if lang:
        return lang
    # Multi-audio videos list every dubbed track as its own format;
    # language_preference marks the original audio (10) above dubs, so take
    # the highest-preference language rather than the first in format order.
    best_pref = None
    for fmt in (data.get("formats") or []):
        fl = _primary_lang(fmt.get("language"))
        if not fl or fl == "und":
            continue
        pref = fmt.get("language_preference")
        pref = -1000 if pref is None else pref
        if best_pref is None or pref > best_pref:
            best_pref = pref
            lang = fl
    return lang


def _format_published(upload_date):
    if len(upload_date) != 8:
        return ""
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    return f"{months[int(upload_date[4:6])-1]} {int(upload_date[6:8])} {upload_date[:4]}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video_id")
    args = parser.parse_args()

    video_id = args.video_id
    url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        result = subprocess.run(
            ["yt-dlp", "--skip-download", "--quiet", "--no-warnings",
             "--no-check-formats", "--dump-json", url],
            capture_output=True, text=True, timeout=60,
        )
    except FileNotFoundError:
        print("ERROR:YTDLP_MISSING: yt-dlp not installed — run: brew install yt-dlp or pip install yt-dlp")
        sys.exit(0)
    except subprocess.TimeoutExpired:
        print("ERROR:YTDLP_TIMEOUT: yt-dlp timed out after 60s")
        sys.exit(0)

    raw = result.stdout
    if not raw.strip():
        stderr_hint = result.stderr.strip()[:200]
        print(f"ERROR:YTDLP_NO_OUTPUT: yt-dlp produced no output — {stderr_hint}")
        sys.exit(0)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR:YTDLP_JSON_ERROR: {e} — raw output: {raw[:200]}")
        sys.exit(0)

    desc_raw = (data.get("description") or "")[:3000]
    if len(data.get("description") or "") > 3000:
        desc_raw += "\u2026"
    desc_html = "<br>".join(_linkify(line) for line in desc_raw.split("\n"))

    chapters = data.get("chapters") or []
    published = _format_published(data.get("upload_date") or "")
    views = _format_views(data.get("view_count"))
    duration = _format_duration(data.get("duration"))

    print(f'YTDLP_CHANNEL: {data.get("channel") or ""}')
    print(f"YTDLP_PUBLISHED: {published}")
    print(f"YTDLP_VIEWS: {views}")
    print(f"YTDLP_DURATION: {duration}")
    print(f"YTDLP_DESC_HTML: {desc_html}")
    print(f"YTDLP_CHAPTERS: {json.dumps(chapters)}")
    print(f"YTDLP_LANGUAGE: {_detect_language(data)}")


if __name__ == "__main__":
    main()
