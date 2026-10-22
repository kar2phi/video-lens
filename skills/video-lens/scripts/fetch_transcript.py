#!/usr/bin/env python3
"""Fetch YouTube transcript and basic HTML metadata.

Usage: python3 fetch_transcript.py VIDEO_ID [LANG_PREF]
"""
import argparse
import datetime
import html as html_lib
import json
import re
import sys
import urllib.parse
import urllib.request


def _json_str(raw):
    """Decode a captured JSON string body; fall back to the raw text."""
    try:
        return json.loads(f'"{raw}"')
    except (ValueError, TypeError):
        return raw


def _fetch_html_metadata(video_id):
    try:
        req = urllib.request.Request(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")

        m = re.search(r"<title>([^<]+)</title>", html)
        # The <title> element carries HTML entities ("Rock &amp; Roll"); the renderer
        # escapes again downstream, so decode here or the entity reaches the <h1> verbatim.
        title = html_lib.unescape(m.group(1)).replace(" - YouTube", "").strip() if m else ""

        # channelName is a JSON string literal: decode \u00e9-style escapes rather
        # than passing the raw source text through.
        channel = ""
        m_ch = re.search(r'"channelName"\s*:\s*"((?:[^"\\]|\\.)*)"', html)
        if m_ch:
            channel = _json_str(m_ch.group(1))

        published = ""
        m_pub = re.search(r'"publishDate"\s*:\s*"([^"]+)"', html)
        if m_pub:
            parts = m_pub.group(1)[:10].split("-")
            months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
            published = f"{months[int(parts[1])-1]} {int(parts[2])} {parts[0]}"

        views = ""
        m_views = re.search(r'"viewCount"\s*:\s*"([0-9]+)"', html)
        if m_views:
            v = int(m_views.group(1))
            views = (f"{v/1e6:.1f}M views" if v >= 1e6
                     else f"{v/1e3:.0f}K views" if v >= 1e3
                     else f"{v} views")

        duration = ""
        m_dur = re.search(r'"lengthSeconds"\s*:\s*"([0-9]+)"', html)
        if m_dur:
            total_s = int(m_dur.group(1))
            h, rem = divmod(total_s, 3600)
            m2 = rem // 60
            duration = f"{h}h {m2}m" if h > 0 else f"{m2} min"

        return title, channel, published, views, duration
    except Exception:
        return "", "", "", "", ""


def _import_errors():
    """(class, code) pairs, most specific first; classes renamed or removed upstream are skipped."""
    import youtube_transcript_api as yta
    pairs = [
        ("TranscriptsDisabled",  "ERROR:CAPTIONS_DISABLED"),
        ("AgeRestricted",        "ERROR:AGE_RESTRICTED"),
        ("VideoUnavailable",     "ERROR:VIDEO_UNAVAILABLE"),
        ("InvalidVideoId",       "ERROR:INVALID_VIDEO_ID"),
        ("IpBlocked",            "ERROR:IP_BLOCKED"),       # before RequestBlocked, its base class
        ("RequestBlocked",       "ERROR:REQUEST_BLOCKED"),
        ("PoTokenRequired",      "ERROR:PO_TOKEN_REQUIRED"),
        ("NoTranscriptFound",    "ERROR:NO_TRANSCRIPT"),
        ("YouTubeRequestFailed", "ERROR:NETWORK_ERROR"),
    ]
    return [(getattr(yta, name), code) for name, code in pairs if hasattr(yta, name)]


def error_code(e):
    for cls, code in _import_errors():
        if isinstance(e, cls):
            return code
    return "ERROR:TRANSCRIPT_FETCH_FAILED"


def list_transcripts(video_id):
    from youtube_transcript_api import YouTubeTranscriptApi
    try:
        return YouTubeTranscriptApi().list(video_id)
    except (AttributeError, TypeError):
        return YouTubeTranscriptApi.list_transcripts(video_id)


def _is_dub(t):
    """YouTube's auto-dubbed tracks are machine translations of the original audio. The
    library does not expose that, but their timedtext URL carries variant=timing-optimized."""
    query = urllib.parse.urlparse(getattr(t, "_url", "") or "").query
    return urllib.parse.parse_qs(query).get("variant") == ["timing-optimized"]


def pick_transcript(tlist, lang_pref):
    """Return (transcript, LANG_WARN line or None). Originals rank before auto-dubs; a
    requested language matches exactly first, then by primary subtag (de ↔ de-DE)."""
    tracks = sorted(tlist, key=_is_dub)   # stable: keeps manual-before-generated order
    if not lang_pref:
        return tracks[0], None
    want = lang_pref.lower()
    for same in (lambda code: code == want,
                 lambda code: code.split("-")[0] == want.split("-")[0]):
        for t in tracks:
            if same(t.language_code.lower()):
                return t, None
    return tracks[0], f'LANG_WARN: Requested language "{lang_pref}" not available; using {tracks[0].language_code}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video_id")
    parser.add_argument("lang_pref", nargs="?", default="")
    args = parser.parse_args()

    video_id = args.video_id
    lang_pref = args.lang_pref

    try:
        import youtube_transcript_api  # noqa: F401
    except ImportError:
        print("ERROR:LIBRARY_MISSING: pip install 'youtube-transcript-api>=0.6.3'")
        sys.exit(1)

    title, channel, published, views, duration = _fetch_html_metadata(video_id)
    if not title:
        title = f"YouTube video {video_id}"

    # The list call can succeed while the download is blocked, so both share one error map.
    try:
        transcript_obj, lang_warn = pick_transcript(list_transcripts(video_id), lang_pref)
        transcript = transcript_obj.fetch()
    except Exception as e:
        print(f"{error_code(e)}: {e}")
        sys.exit(1)
    if lang_warn:
        print(lang_warn)
    lang = transcript_obj.language_code

    # Detect entry type once before the loop
    use_dict = isinstance(transcript[0], dict) if transcript else False

    lines = [
        f"TITLE: {title}",
        f"CHANNEL: {channel}",
        f"PUBLISHED: {published}",
        f"VIEWS: {views}",
        f"DURATION: {duration}",
        f"DATE: {datetime.date.today().isoformat()}",
        f"LANG: {lang}",
    ]

    for s in transcript:
        text = s["text"] if use_dict else s.text
        start = s["start"] if use_dict else s.start
        total_s = int(start)
        h, rem = divmod(total_s, 3600)
        m2, s2 = divmod(rem, 60)
        if h > 0:
            lines.append(f"[{h}:{m2:02d}:{s2:02d}] {text}")
        else:
            lines.append(f"[{m2}:{s2:02d}] {text}")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
