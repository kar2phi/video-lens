#!/usr/bin/env python3
"""Fetch YouTube transcript and basic HTML metadata.

Usage: python3 fetch_transcript.py VIDEO_ID [LANG_PREF]
"""
import argparse
import datetime
import re
import sys
import urllib.request


def _fetch_html_metadata(video_id):
    try:
        req = urllib.request.Request(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        html = urllib.request.urlopen(req).read().decode("utf-8", errors="ignore")

        m = re.search(r"<title>([^<]+)</title>", html)
        title = m.group(1).replace(" - YouTube", "").strip() if m else ""

        channel = ""
        m_ch = re.search(r'"channelName"\s*:\s*"([^"]+)"', html)
        if m_ch:
            channel = m_ch.group(1)

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video_id")
    parser.add_argument("lang_pref", nargs="?", default="")
    args = parser.parse_args()

    video_id = args.video_id
    lang_pref = args.lang_pref

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("ERROR:LIBRARY_MISSING: pip install 'youtube-transcript-api>=0.6.3'")
        sys.exit(1)

    # Defensive imports — fall back to generic handling if classes are renamed/removed
    try:
        from youtube_transcript_api import (
            TranscriptsDisabled,
            VideoUnavailable,
            NoTranscriptFound,
            InvalidVideoId,
        )
    except ImportError:
        TranscriptsDisabled = VideoUnavailable = NoTranscriptFound = InvalidVideoId = None

    try:
        from youtube_transcript_api import (
            AgeRestricted,
            IpBlocked,
            RequestBlocked,
            PoTokenRequired,
            YouTubeRequestFailed,
        )
    except ImportError:
        AgeRestricted = IpBlocked = RequestBlocked = PoTokenRequired = YouTubeRequestFailed = None

    title, channel, published, views, duration = _fetch_html_metadata(video_id)

    try:
        try:
            tlist = YouTubeTranscriptApi().list(video_id)
        except (AttributeError, TypeError):
            tlist = YouTubeTranscriptApi.list_transcripts(video_id)
    except Exception as e:
        _error_map = [
            (TranscriptsDisabled,  "ERROR:CAPTIONS_DISABLED"),
            (AgeRestricted,        "ERROR:AGE_RESTRICTED"),
            (VideoUnavailable,     "ERROR:VIDEO_UNAVAILABLE"),
            (InvalidVideoId,       "ERROR:INVALID_VIDEO_ID"),
            (IpBlocked,            "ERROR:IP_BLOCKED"),
            (RequestBlocked,       "ERROR:REQUEST_BLOCKED"),
            (PoTokenRequired,      "ERROR:PO_TOKEN_REQUIRED"),
            (NoTranscriptFound,    "ERROR:NO_TRANSCRIPT"),
            (YouTubeRequestFailed, "ERROR:NETWORK_ERROR"),
        ]
        code = "ERROR:TRANSCRIPT_FETCH_FAILED"
        for cls, mapped_code in _error_map:
            if cls is not None and isinstance(e, cls):
                code = mapped_code
                break
        print(f"{code}: {e}")
        sys.exit(1)

    transcript_obj = None
    if lang_pref:
        # 1. native exact match
        for t in tlist:
            if t.language_code == lang_pref and not getattr(t, "is_translation", False):
                transcript_obj = t
                break
        # 2. any exact match (including translated)
        if transcript_obj is None:
            for t in tlist:
                if t.language_code == lang_pref:
                    transcript_obj = t
                    break
        # 3. native fallback
        if transcript_obj is None:
            for t in tlist:
                if not getattr(t, "is_translation", False):
                    transcript_obj = t
                    break
            if transcript_obj is None:
                transcript_obj = next(iter(tlist))
            print(f'LANG_WARN: Requested language "{lang_pref}" not available; using {transcript_obj.language_code}')
    else:
        for t in tlist:
            if not getattr(t, "is_translation", False):
                transcript_obj = t
                break
        if transcript_obj is None:
            transcript_obj = next(iter(tlist))

    transcript = transcript_obj.fetch()
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
        f"TIME: {datetime.datetime.now().strftime('%H%M%S')}",
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
