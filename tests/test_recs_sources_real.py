"""video-lens-recs network tier: the public sources against live YouTube (026 §12.2).

The canary for yt-dlp or YouTube changes: it asserts that fields are present, not their
values. Stable public channels only; no cookies. Run with: task test-real.
"""
import time

import pytest

import recs_world  # noqa: F401  (puts the recs scripts on sys.path)
import yt_sources as yt

pytestmark = pytest.mark.network

# Large, long-lived public channels that upload long-form video regularly.
CHANNELS = {
    "UC_x5XG1OV2P6uZZ5FSM9Ttw": "Google for Developers",
    "UCLA_DiR1FfKNvjuUpBHmylQ": "NASA",
    "UCAuUUnT6oDeKwE6v1NGQxug": "TED",
}


@pytest.mark.parametrize("channel_id", list(CHANNELS))
def test_channel_listing_has_duration_views_and_dates(channel_id):
    lst = yt.channel_listing(channel_id, limit=30)
    assert lst["channelId"] == channel_id
    assert lst["subscribers"] and lst["subscribers"] > 10_000
    entries = [e for e in lst["entries"] if not e["live_status"]]
    assert len(entries) >= 10
    assert sum(e["duration"] is not None for e in entries) >= 0.8 * len(entries)
    assert sum(e["published"] is not None for e in entries) >= 0.8 * len(entries)
    assert all(yt.VIDEO_ID_RE.fullmatch(e["videoId"]) for e in entries)
    # Flat listings sometimes omit views on sub-2-minute clips; the pipeline drops those anyway.
    long_form = [e for e in entries if (e["duration"] or 0) >= 240]
    assert len(long_form) >= 3
    assert sum(e["views"] is not None for e in long_form) >= 0.8 * len(long_form)


@pytest.mark.parametrize("channel_id", list(CHANNELS))
def test_rss_long_form_feed_has_exact_dates_and_views(channel_id):
    feed = yt.channel_rss(channel_id)
    assert feed["entries"], "empty feed"
    e = feed["entries"][0]
    assert e["published_exact"] and e["published"] and e["published"] < time.time() + 3600
    assert e["views"] is not None
    assert e["channelId"] == channel_id


def test_search_entries_carry_channel_ids_views_and_durations():
    entries = yt.search("python tutorial", 30, limit=10)
    assert len(entries) >= 5
    assert all(yt.VIDEO_ID_RE.fullmatch(e["videoId"]) for e in entries)
    assert sum(bool(yt.CHANNEL_ID_RE.fullmatch(e["channelId"])) for e in entries) >= 0.8 * len(entries)
    assert sum(e["views"] is not None for e in entries) >= 0.5 * len(entries)
    assert sum(e["duration"] is not None for e in entries) >= 0.5 * len(entries)


def test_handle_resolves_to_a_channel_id():
    lst = yt.channel_listing("@TED", limit=3)
    assert lst["channelId"] == "UCAuUUnT6oDeKwE6v1NGQxug"
