"""A synthetic, offline world for the video-lens-recs tests.

Builds replay files (yt_sources' VIDEO_LENS_RECS_REPLAY format) for made-up channels and
videos, a small video-lens manifest, and a topic config, all under a temp dir. Nothing here
comes from a real library: channel names, IDs and titles are invented.
"""
import datetime
import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
RECS_SCRIPTS = REPO_ROOT / "skills" / "video-lens-recs" / "scripts"
if str(RECS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RECS_SCRIPTS))

import yt_sources  # noqa: E402

NOW = 1792584000.0          # 2026-10-21 12:00 UTC (the same local date in most timezones)
DAY = 86400


def cid(name: str) -> str:
    return "UC" + (name + "x" * 22)[:22]


def vid(tag: str) -> str:
    return (tag + "_" * 11)[:11]


ALPHA, BETA, GAMMA, NEWS = cid("alphaagents"), cid("betabuilds"), cid("gammalabs"), cid("newsdesk")
OUTSIDER, CLICKY, TINY = cid("outsiderai"), cid("clickyfarm"), cid("tinychan")


def listing_entry(v, title, age_days, views, duration=900, **extra):
    return {"_type": "url", "ie_key": "Youtube", "id": v, "title": title, "duration": duration,
            "view_count": views, "timestamp": NOW - age_days * DAY, "live_status": None,
            "url": f"https://www.youtube.com/watch?v={v}", **extra}


def listing(channel_id, name, subs, entries):
    return {"_type": "playlist", "id": channel_id, "channel_id": channel_id, "channel": name,
            "uploader_id": "@" + name.lower().replace(" ", ""), "channel_follower_count": subs,
            "title": f"{name} - Videos", "entries": entries}


def rss(channel_id, name, items):
    """items: (video id, title, age days, views, description)."""
    entries = []
    for v, title, age, views, desc in items:
        published = datetime.datetime.fromtimestamp(NOW - age * DAY, datetime.timezone.utc).isoformat()
        entries.append(f"""
 <entry>
  <id>yt:video:{v}</id><yt:videoId>{v}</yt:videoId><yt:channelId>{channel_id}</yt:channelId>
  <title>{title}</title>
  <link rel="alternate" href="https://www.youtube.com/watch?v={v}"/>
  <author><name>{name}</name></author>
  <published>{published}</published>
  <media:group><media:title>{title}</media:title><media:description>{desc}</media:description>
   <media:community><media:statistics views="{views}"/></media:community></media:group>
 </entry>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <title>{name}</title>{''.join(entries)}
</feed>"""


def search_entry(v, title, channel_id, name, views, duration=800, desc=""):
    return {"_type": "url", "ie_key": "Youtube", "id": v, "title": title, "channel": name,
            "channel_id": channel_id, "duration": duration, "view_count": views, "description": desc,
            "url": f"https://www.youtube.com/watch?v={v}", "timestamp": None}


def old_uploads(prefix, n, views):
    """Older uploads that set a channel's usual views (outside a 7-day window)."""
    return [listing_entry(vid(f"{prefix}{i:02d}"), f"Older {prefix} talk {i}", 10 + i, views) for i in range(n)]


def put(replay_dir, key, data):
    p = yt_sources._key_file(replay_dir, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"key": key, "data": data}), encoding="utf-8")


def put_error(replay_dir, key, code):
    p = yt_sources._key_file(replay_dir, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"key": key, "error": code}), encoding="utf-8")


# The fresh uploads every test relies on.
A_HOT = vid("alphahot")        # 3 days, far above the channel's usual
A_FRESH = vid("alphafrsh")     # 1 day
A_SUMM = vid("alphasum")       # already summarised
A_SHORT = vid("alphashrt")     # 2 minutes: too short
A_LIVE = vid("alphalive")      # upcoming premiere
B_NEW = vid("betanew")
B_TWO = vid("betatwo")
G_ONE = vid("gammaone")
S_GOOD = vid("srchgood")       # search hit from a channel outside the subscriptions
S_CLICK = vid("srchclick")     # clickbait search hit
S_TINY = vid("srchtiny")       # tiny channel, ordinary performance
S_CJK = vid("srchcjk")         # title in a script outside the topic languages
S_ALPHA = vid("alphahot")      # same video found by search too (dedup)
H_ONE = vid("homeone")         # home feed, on topic
H_OFF = vid("homeoff")         # home feed, off topic
N_ONE = vid("newsone")


def build(root: pathlib.Path, monkeypatch, mode="takeout", topics=None) -> dict:
    """Create config, state, library and replay files; point the env at them."""
    root = pathlib.Path(root)
    replay = root / "replay"
    env = {"HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "config"),
           "XDG_DATA_HOME": str(root / "data"), "XDG_CACHE_HOME": str(root / "cache"),
           "VIDEO_LENS_LIBRARY": str(root / "library"), yt_sources.REPLAY_ENV: str(replay),
           yt_sources.NOW_ENV: str(NOW), "NO_BROWSER": "1"}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv(yt_sources.RECORD_ENV, raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    (root / "home").mkdir(parents=True, exist_ok=True)

    put(replay, f"listing:{ALPHA}:30", listing(ALPHA, "Alpha Agents", 830000, [
        listing_entry(A_HOT, "Is the Agent Loop Over? A Harness Retrospective", 3, 180000),
        listing_entry(A_FRESH, "Evals for Agents in Regulated Workflows", 1, 9000),
        listing_entry(A_SUMM, "Context Engineering for Long-Running Agents", 2, 15000),
        listing_entry(A_SHORT, "Agent tip of the day", 1, 4000, duration=120),
        listing_entry(A_LIVE, "Live: agent office hours", 0, None, duration=None, live_status="is_upcoming"),
        *old_uploads("alphaold", 12, 10000),
    ]))
    put(replay, f"rss:{ALPHA}:0", rss(ALPHA, "Alpha Agents", [
        (A_HOT, "Is the Agent Loop Over? A Harness Retrospective", 3.2, 181234, "A look back at agent harnesses and what models changed."),
        (A_FRESH, "Evals for Agents in Regulated Workflows", 1.1, 9123, "How a bank evaluates agents before letting them run unsupervised."),
    ]))
    put(replay, f"listing:{BETA}:30", listing(BETA, "Beta Builds", 120000, [
        listing_entry(B_NEW, "Building an MCP Server for Your Team's Tools", 2, 30000),
        listing_entry(B_TWO, "Agent Memory Patterns That Survive Production", 5, 12000),
        *old_uploads("betaold", 10, 8000),
    ]))
    put_error(replay, f"rss:{BETA}:0", "HTTP_404")
    put_error(replay, f"rss:{BETA}:1", "HTTP_404")
    put_error(replay, f"listing:{GAMMA}:30", "YTDLP_FAILED")
    put(replay, f"rss:{GAMMA}:0", rss(GAMMA, "Gamma Labs", [
        (G_ONE, "Agent Evals Without a Benchmark", 2, 5000, "Testing agents when no benchmark exists."),
    ]))
    put(replay, f"listing:{NEWS}:30", listing(NEWS, "News Desk", 2000000, [
        listing_entry(N_ONE, "Evening news: elections and budget", 0.8, 300000, duration=1500),
        *old_uploads("newsold", 10, 200000),
    ]))
    put_error(replay, f"rss:{NEWS}:0", "HTTP_404")
    put_error(replay, f"rss:{NEWS}:1", "HTTP_404")

    sp = yt_sources.search_sp(7)
    put(replay, f"search:{sp}:20:ai agents", {"_type": "playlist", "id": "ai agents", "entries": [
        search_entry(S_ALPHA, "Is the Agent Loop Over? A Harness Retrospective", ALPHA, "Alpha Agents", 180000),
        search_entry(S_GOOD, "How We Ship Agents With Evals at Scale", OUTSIDER, "Outsider AI", 60000,
                     desc="Agent evals in production, step by step."),
        search_entry(S_CLICK, "The SECRET Agent Trick NOBODY Is Talking About!!", CLICKY, "Clicky Farm", 90000),
        search_entry(S_TINY, "my agent experiments vlog", TINY, "Tiny Chan", 300),
        search_entry(S_CJK, "人工智能代理的未来与评估方法", OUTSIDER, "Outsider AI", 50000),
    ]})
    put(replay, f"listing:{OUTSIDER}:30", listing(OUTSIDER, "Outsider AI", 173000, [
        listing_entry(S_GOOD, "How We Ship Agents With Evals at Scale", 2, 60000),
        listing_entry(S_CJK, "人工智能代理的未来与评估方法", 3, 50000),
        *old_uploads("outold", 10, 20000),
    ]))
    put(replay, f"rss:{OUTSIDER}:0", rss(OUTSIDER, "Outsider AI", [
        (S_GOOD, "How We Ship Agents With Evals at Scale", 2.3, 61000, "Agent evals in production, step by step."),
    ]))
    put(replay, f"listing:{CLICKY}:30", listing(CLICKY, "Clicky Farm", 900000, old_uploads("clickold", 5, 50000)))
    put(replay, f"listing:{TINY}:30", listing(TINY, "Tiny Chan", 1200, [
        listing_entry(S_TINY, "my agent experiments vlog", 2, 300),
        *old_uploads("tinyold", 5, 250),
    ]))
    for c in (CLICKY, TINY):
        put_error(replay, f"rss:{c}:0", "HTTP_404")
        put_error(replay, f"rss:{c}:1", "HTTP_404")

    put(replay, "personal:subscriptions", {"_type": "playlist", "entries": [
        {"id": ALPHA, "title": "Alpha Agents", "channel_follower_count": 830000},
        {"id": BETA, "title": "Beta Builds", "channel_follower_count": 120000},
        {"id": NEWS, "title": "News Desk", "channel_follower_count": 2000000},
    ]})
    put(replay, "personal:home", {"_type": "playlist", "entries": [
        search_entry(H_ONE, "Agent Evals: A Field Guide", OUTSIDER, "Outsider AI", 40000),
        search_entry(H_OFF, "Ten Pasta Recipes for Busy Weeknights", cid("pastachan"), "Pasta Chan", 900000),
    ]})

    library = root / "library"
    (library / "reports").mkdir(parents=True, exist_ok=True)
    reports = [
        {"videoId": A_SUMM, "title": "Context Engineering for Long-Running Agents", "channel": "Alpha Agents",
         "tags": ["ai", "ai agents"], "keywords": ["Context windows", "Agent memory"], "generationDate": "2026-10-20"},
        *[{"videoId": vid(f"libalpha{i}"), "title": f"Agent harness deep dive part {i}", "channel": "Alpha Agents",
           "tags": ["ai", "ai agents"], "keywords": ["Harness design"], "generationDate": f"2026-09-{10 + i:02d}"}
          for i in range(4)],
        *[{"videoId": vid(f"libgamma{i}"), "title": f"Evals in practice {i}", "channel": "Gamma Labs",
           "tags": ["ai", "evals"], "keywords": ["Evals"], "generationDate": f"2026-08-{10 + i:02d}"} for i in range(3)],
        {"videoId": vid("libnews1"), "title": "Weekly news round-up", "channel": "News Desk",
         "tags": ["news"], "keywords": [], "generationDate": "2026-10-01"},
    ]
    (library / "manifest.json").write_text(json.dumps({"count": len(reports), "reports": reports}), encoding="utf-8")

    cfg_dir = root / "config" / "video-lens"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    topics = topics or {
        "ai": {"label": "AI & agents", "channels": [ALPHA, BETA], "queries": ["ai agents"],
               "keywords": ["agent", "evals", "mcp"], "exclude_keywords": ["giveaway"],
               "report_tags": ["ai", "ai agents"]},
        "news": {"label": "News", "channels": [NEWS], "queries": [], "window_days": 2, "report_tags": ["news"]},
    }
    (cfg_dir / "recs.json").write_text(json.dumps({
        "version": 1, "account": {"mode": mode, "browser": "firefox", "subscriptions_synced": "",
                                  "watched_check_depth": 300},
        "ui": {"raycast_summarize": False}, "topics": topics}), encoding="utf-8")
    data = root / "data" / "video-lens" / "recs"
    data.mkdir(parents=True, exist_ok=True)
    (data / "subscriptions.json").write_text(json.dumps({"source": "takeout", "channels": [
        {"id": ALPHA, "title": "Alpha Agents"}, {"id": BETA, "title": "Beta Builds"},
        {"id": NEWS, "title": "News Desk"}]}), encoding="utf-8")
    # Gamma Labs is an affinity channel: 3 reports, not subscribed. Its id comes from a lookup.
    put(replay, f"video_channel:{vid('libgamma0')}", [f"{GAMMA}\tGamma Labs"])
    return {"root": root, "replay": replay, "library": library}
