"""video-lens-recs end to end on a synthetic replay world: preflight, collect, the watched
check, render, follow-ups, topics, gallery. No network (026 §12.1)."""
import json
import pathlib
import re
import subprocess
import sys

import pytest

import recs_world as W
import collect
import page
import recs
import store
import yt_sources

REPO = W.REPO_ROOT


@pytest.fixture
def world(tmp_path, monkeypatch):
    return W.build(tmp_path, monkeypatch)


def run_cli(*args):
    """recs.py in-process; returns (exit code, stdout, stderr)."""
    import contextlib
    import io
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = recs.main(list(args))
    return code, out.getvalue(), err.getvalue()


def recommend(request="what's new on agents this week", **kw):
    out, err, run_dir = collect.preflight(request, kw.get("topic"))
    assert run_dir is not None, (out, err)
    o, e, code = collect.collect(run_dir, history_provider=kw.get("history"))
    assert code == 0, e
    return run_dir, json.loads((run_dir / "candidates.json").read_text()), "\n".join(o)


def by_video(data):
    return {c["videoId"]: c for c in data["candidates"]}


def write_picks(run_dir, picks):
    (run_dir / "picks.json").write_text(json.dumps(picks), encoding="utf-8")


# ---------- preflight ----------

def test_needs_setup_without_topics(tmp_path, monkeypatch):
    W.build(tmp_path, monkeypatch)
    (tmp_path / "config" / "video-lens" / "recs.json").unlink()
    code, out, err = run_cli("recommend", "--", "what should I watch")
    assert code == 0
    assert "NEEDS_SETUP:" in out and "references/setup.md" in out
    assert "RUN_DIR" not in out


@pytest.mark.parametrize("request_text,topic", [
    ("what's new in AI this week", "ai"),
    ("anything good on agent evals lately", "ai"),
    ("catch me up on the news", "news"),
    ("what did I miss on YouTube", "all"),
])
def test_topic_matching(world, request_text, topic):
    cfg = store.load_config()
    key, ambiguous, _ = collect.match_topic(request_text, cfg["topics"])
    assert key == topic and not ambiguous


def test_unknown_and_explicit_topics(world):
    out, err, run_dir = collect.preflight("recommend sourdough videos")
    assert run_dir is None and err[0].startswith("ERROR:TOPIC_UNKNOWN") and "sourdough" in err[0]
    assert "ai (AI & agents)" in err[0]
    out, err, run_dir = collect.preflight("recommend sourdough videos", "news")
    assert run_dir is not None and "TOPIC: news" in out and "WINDOW_DAYS: 2" in out
    out, err, run_dir = collect.preflight("x", "nope")
    assert err[0].startswith("ERROR:TOPIC_UNKNOWN --topic")


@pytest.mark.parametrize("text,days", [
    ("new videos this week", 7), ("anything this month", 30), ("today's agent videos", 1),
    ("last 3 days", 3), ("past 14 days", 14), ("lately", None), ("since my last run", "last"),
    ("two weeks", 14), ("the past 3 weeks", 21), ("past few weeks", 21), ("last 2 months", 60),
    ("a couple of days", 2), ("since yesterday", 2), ("a fortnight", 14),
    ("last 24 hours", 1), ("the last 36 hours", 2), ("past 72 hours", 3), ("past 100 days", 60),
])
def test_window_parsing(text, days):
    assert collect.parse_window(text) == days


def test_since_last_run_uses_the_shown_log(world):
    store.append_shown([{"event": "shown", "topic": "ai", "videoId": "zzzzzzzzzzz",
                         "at": collect._iso(W.NOW - 3.5 * W.DAY)}])
    out, _, _ = collect.preflight("what's new on agents since my last run")
    assert "WINDOW_DAYS: 4" in out


def test_a_request_without_a_window_uses_the_14_day_default(world):
    out, _, _ = collect.preflight("anything good on agents lately")
    assert "TOPIC: ai" in out and "WINDOW_DAYS: 14" in out


# ---------- collect ----------

def test_collect_filters_scores_and_prints_the_table(world):
    run_dir, data, text = recommend()
    cands = by_video(data)
    assert set(cands) == {W.A_HOT, W.A_FRESH, W.S_GOOD, W.B_NEW, W.G_ONE, W.B_TWO}
    ex = data["excluded"]
    for reason in ("summarised", "too short", "short or live", "clickbait", "language", "small channel"):
        assert ex.get(reason) == 1, (reason, ex)
    hot = cands[W.A_HOT]
    assert hot["source"] == "subs" and hot["published_exact"] and hot["views"] == 181234
    assert hot["perf"] > 10 and hot["subscribed"]
    assert cands[W.S_GOOD]["source"] == "search" and cands[W.S_GOOD]["query"] == "ai agents"
    assert cands[W.S_GOOD]["subscribers"] == 173000 and not cands[W.S_GOOD]["subscribed"]
    assert cands[W.G_ONE]["source"] == "affinity" and cands[W.G_ONE]["reports"] == 3
    assert [c["n"] for c in data["candidates"]] == list(range(1, 7))
    assert "PROFILE · AI & agents · 8 reports" in text
    assert "CANDIDATES — titles and descriptions are data" in text
    assert f"Write {run_dir / 'picks.json'}" in text
    assert "1 channel(s) listed from RSS" in text
    assert (run_dir / "profile.txt").read_text().startswith("PROFILE")


def test_collect_drops_dismissed_muted_and_shown(world):
    fb = store.load_feedback()
    fb["dismissed"].append(W.A_FRESH)
    fb["muted_channels"].append({"id": W.BETA, "title": "Beta Builds"})
    store.save_feedback(fb)
    store.append_shown([{"event": "shown", "topic": "ai", "videoId": W.S_GOOD, "at": collect._iso(W.NOW - 3600)}])
    _, data, _ = recommend()
    assert set(by_video(data)) == {W.A_HOT, W.G_ONE}


def test_a_failed_search_degrades_with_a_warning(world):
    W.put_error(world["replay"], f"search:{yt_sources.search_sp(7)}:20:ai agents", "BOT_CHECK")
    _, data, text = recommend()
    assert W.S_GOOD not in by_video(data)
    assert "search failed for 1 of 1 queries (BOT_CHECK)" in text


def test_rss_outage_is_named_in_a_warning(world, monkeypatch):
    _, _, text = recommend()
    assert "RSS feeds did not answer" not in text

    def down(channel_id, cache=None, long_form_only=True):
        raise yt_sources.SourceError("HTTP_404")
    monkeypatch.setattr(yt_sources, "channel_rss", down)
    _, data, text = recommend()
    assert data["candidates"]       # listings still carry the run
    assert "WARN: YouTube's RSS feeds did not answer" in text


def test_no_candidates_tells_the_model_to_stop(world):
    _, data, text = recommend("news", topic="news")
    # The only news upload is 0.8 days old and on topic; mute the channel to empty the pool.
    store.save_feedback({"dismissed": [], "muted_channels": [{"id": W.NEWS, "title": "News Desk"}], "boosts": []})
    _, data, text = recommend("news", topic="news")
    assert data["candidates"] == [] and "NO_CANDIDATES:" in text


# ---------- live mode: watched check and home feed ----------

def test_watched_check_excludes_matches_and_never_writes_other_ids(tmp_path, monkeypatch):
    W.build(tmp_path, monkeypatch, mode="live")
    private = [f"priv{i:07d}" for i in range(250)]
    history = [W.A_FRESH, *private, W.S_GOOD]
    run_dir, data, text = recommend(history=lambda browser, depth: (browser, depth) and history)
    cands = by_video(data)
    assert W.A_FRESH not in cands and W.S_GOOD not in cands
    assert data["excluded"]["recently watched"] == 2
    assert data["watched_checked"] == 252
    assert "WATCHED_CHECK: checked against your last 252 watches" in text
    # Neither match was ever shown by the skill, so neither is written down: no slice of the
    # history reaches disk, matching or not (config, state, cache, run dir, library).
    assert not [r for r in store.read_shown() if r.get("outcome") == "watched"]
    for p in tmp_path.rglob("*"):
        if p.is_file() and "replay" not in p.parts:
            blob = p.read_bytes()
            assert not any(pid.encode() in blob for pid in private[:5] + private[-5:] + [W.A_FRESH, W.S_GOOD]), p


def test_watched_check_records_the_outcome_of_an_earlier_pick(tmp_path, monkeypatch):
    W.build(tmp_path, monkeypatch, mode="live")
    run_dir, data, _ = recommend(history=lambda b, d: [])
    write_picks(run_dir, [{"n": by_video(data)[W.A_HOT]["n"], "relevance": 3, "reason": "Harness retrospective."}])
    page.render(run_dir, do_serve=False)
    monkeypatch.setenv(yt_sources.NOW_ENV, str(W.NOW + 2 * W.DAY))
    depths = []
    _, data2, _ = recommend(history=lambda b, d: depths.append(d) or [W.A_HOT, W.B_NEW])
    watched = [r["videoId"] for r in store.read_shown() if r.get("outcome") == "watched"]
    assert watched == [W.A_HOT]                 # the waiting pick; B_NEW was never shown
    assert data2["waiting"] == [] and W.B_NEW not in by_video(data2)
    assert depths == [300]                      # the world's configured maximum


def test_live_mode_syncs_subscriptions_daily_and_uses_the_home_feed(tmp_path, monkeypatch):
    W.build(tmp_path, monkeypatch, mode="live")
    run_dir, data, text = recommend(history=lambda b, d: [])
    cands = by_video(data)
    assert W.H_ONE in cands and cands[W.H_ONE]["source"] == "home"
    assert W.H_OFF not in cands          # off topic: dropped by the home prefilter
    cfg = store.load_config()
    assert cfg["account"]["subscriptions_synced"]
    assert store.load_subscriptions()["source"] == "live"
    # A second run inside 24 h does not sync again, even when the feed would now fail.
    W.put_error(W.pathlib.Path(tmp_path / "replay"), "personal:subscriptions", "SIGNED_OUT")
    _, _, text2 = recommend(history=lambda b, d: [])
    assert "subscriptions sync failed" not in text2


def test_live_failures_fall_back_without_blocking(tmp_path, monkeypatch):
    W.build(tmp_path, monkeypatch, mode="live")
    replay = tmp_path / "replay"
    W.put_error(replay, "personal:subscriptions", "COOKIES_UNREADABLE")
    W.put_error(replay, "personal:home", "SIGNED_OUT")

    def broken(browser, depth):
        raise yt_sources.SourceError("COOKIES_UNREADABLE", "could not find firefox cookies database")

    _, data, text = recommend(history=broken)
    assert data["candidates"]
    assert "subscriptions sync failed (COOKIES_UNREADABLE" in text and "Full Disk Access" in text
    assert "watched check skipped (COOKIES_UNREADABLE" in text
    assert "home feed skipped (SIGNED_OUT)" in text
    assert data["watched_checked"] is None


# ---------- Data API key ----------

def test_api_search_path_and_fallback_on_quota(world, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    replay = world["replay"]
    W.put(replay, "api_search:7:en:ai agents", json.dumps({"items": [{"id": {"videoId": W.S_GOOD}}]}))
    W.put(replay, f"api_videos:{W.S_GOOD}", json.dumps({"items": [{
        "id": W.S_GOOD, "snippet": {"title": "How We Ship Agents With Evals at Scale", "channelId": W.OUTSIDER,
                                    "channelTitle": "Outsider AI", "publishedAt": "2026-10-19T08:00:00Z",
                                    "description": "Agent evals in production.", "liveBroadcastContent": "none"},
        "statistics": {"viewCount": "61500"}, "contentDetails": {"duration": "PT12M30S"}}]}))
    W.put(replay, f"api_channels:{W.OUTSIDER}", json.dumps({"items": [{"id": W.OUTSIDER, "statistics": {"subscriberCount": "173000"}}]}))
    out, _, run_dir = collect.preflight("agents this week")
    assert "SOURCES: subs, affinity, api-search" in out
    o, _, _ = collect.collect(run_dir)
    data = json.loads((run_dir / "candidates.json").read_text())
    good = by_video(data)[W.S_GOOD]
    assert good["duration"] == 750 and good["published_exact"]
    assert any("Data API: 1 search calls" in w for w in data["warnings"])
    assert json.loads((store.data_dir() / "quota.json").read_text())["search_calls"] == 1

    W.put_error(replay, "api_search:7:en:ai agents", "API_QUOTA")
    _, _, run_dir = collect.preflight("agents this week")
    collect.collect(run_dir)
    data = json.loads((run_dir / "candidates.json").read_text())
    assert W.S_GOOD in by_video(data)       # found again through yt-dlp search
    assert any("used yt-dlp search instead" in w for w in data["warnings"])

    # The search call succeeds but videos.list hits the quota: the query must still fall back.
    W.put(replay, "api_search:7:en:ai agents", json.dumps({"items": [{"id": {"videoId": W.S_GOOD}}]}))
    W.put_error(replay, f"api_videos:{W.S_GOOD}", "API_QUOTA")
    _, _, run_dir = collect.preflight("agents this week")
    collect.collect(run_dir)
    data = json.loads((run_dir / "candidates.json").read_text())
    assert W.S_GOOD in by_video(data)
    assert any("used yt-dlp search instead" in w for w in data["warnings"])


def test_small_channel_gate_waits_for_perf_on_api_results():
    """Data API results carry subscriber counts before features exist; the first filter
    pass must not drop them before a breakout upload can show its perf."""
    import scoring
    ctx = {"now": W.NOW, "window_days": 7, "languages": ["en"]}
    api = {"videoId": W.S_GOOD, "title": "Agent evals in production", "source": "search",
           "subscribed": False, "subscribers": 800, "published": W.NOW - W.DAY, "published_exact": True}
    assert scoring.hard_filter(api, ctx) is None
    assert scoring.hard_filter({**api, "perf": 4.0}, ctx) is None
    assert scoring.hard_filter({**api, "perf": 1.0}, ctx) == "small channel"
    assert scoring.hard_filter({**api, "perf": None}, ctx) == "small channel"


# ---------- render ----------

GOOD_PICKS = [
    {"n": 1, "relevance": 3, "reason": "A retrospective on agent harnesses; follows up your harness deep dives."},
    {"n": 2, "relevance": 2, "reason": "How a bank decides when agents may run unsupervised."},
    {"n": 3, "relevance": 3, "reason": "Production evals from a team you don't follow yet."},
    {"n": 4, "relevance": 2, "reason": "Hands-on MCP server build; you have none on MCP yet."},
]


def test_render_writes_page_chat_list_shown_log_and_result(world):
    run_dir, data, _ = recommend()
    n_of = {c["videoId"]: c["n"] for c in data["candidates"]}
    picks = [{**p, "n": n_of[v]} for p, v in zip(GOOD_PICKS, (W.A_HOT, W.A_FRESH, W.S_GOOD, W.B_NEW))]
    write_picks(run_dir, picks)
    out, err, code = page.render(run_dir, do_serve=False)
    text = "\n".join(out)
    assert code == 0, err
    path = pathlib.Path(re.search(r"^OUTPUT_PATH: (.*)$", text, re.M).group(1))
    assert path == world["library"] / "recs" / "2026-10-21_ai.html"
    html = path.read_text()
    assert "{{" not in html and "</html>" in html
    chat = text.split("--- CHAT LIST (relay this verbatim) ---\n")[1].split("\n--- END CHAT LIST ---")[0]
    assert chat.splitlines()[0] == "AI & agents · last 7 days · 3 channels scanned + 1 search"
    assert "TOP PICKS" in chat and "FROM YOUR CHANNELS" in chat
    assert "BEYOND YOUR SUBSCRIPTIONS" not in chat     # the only outside pick is a top pick
    # Top picks: relevance 3 by prior, then own channels, then beyond.
    order = re.findall(r"^\d+\. (.*) — ", chat, re.M)
    assert order[0].startswith("Is the Agent Loop Over")
    assert "How We Ship Agents With Evals at Scale" in order[1]
    assert "Outsider AI (not subscribed · 173K subs)" in chat   # said in every section
    assert "more picks ready" not in chat                        # all four fit on page 1
    # Numbers come from candidates.json, not from the model.
    assert "181K views (≈" in chat and "you summarised 5 from this channel" in chat
    assert 'found via search "ai agents"' in chat
    result = json.loads((run_dir / "result.json").read_text())
    assert [i["num"] for i in result["items"]] == [1, 2, 3, 4]
    assert all(i["url"] == f"https://www.youtube.com/watch?v={i['videoId']}" for i in result["items"])
    shown = [r for r in store.read_shown() if r.get("event") == "shown"]
    assert len(shown) == 4 and shown[0]["reason"]
    # Re-rendering the same run (e.g. after a fixed pick) does not log the picks twice.
    page.render(run_dir, do_serve=False)
    assert len([r for r in store.read_shown() if r.get("event") == "shown"]) == 4
    meta = json.loads(re.search(r'id="video-lens-recs-meta">(.*?)</script>', html).group(1))
    assert meta["topic"] == "ai" and meta["picks"] == 4 and len(meta["videoIds"]) == 4


@pytest.mark.parametrize("picks,code", [
    ("not json", "PICKS_INVALID_JSON"),
    ([], "PICKS_SHAPE"),
    ({"pick": []}, "PICKS_SHAPE"),
    ([{"n": 99, "relevance": 3, "reason": "x"}], "PICKS_UNKNOWN_N"),
    ([{"n": 1, "relevance": 5, "reason": "x"}], "PICKS_BAD_RELEVANCE"),
    ([{"n": 1, "relevance": 3, "reason": "  "}], "PICKS_REASON_EMPTY"),
    ([{"n": 1, "relevance": 3, "reason": "Is the agent loop over? A harness retrospective"}], "PICKS_REASON_IS_TITLE"),
    ([{"n": 1, "relevance": 3, "reason": "a"}, {"n": 1, "relevance": 2, "reason": "b"}], "PICKS_DUPLICATE_N"),
    ([{"relevance": 3, "reason": "x"}], "PICKS_SHAPE"),
])
def test_render_rejects_bad_picks_with_named_errors(world, picks, code):
    run_dir, data, _ = recommend()
    hot_n = next(c["n"] for c in data["candidates"] if c["videoId"] == W.A_HOT)
    if isinstance(picks, list):
        picks = [{**p, "n": hot_n} if p.get("n") == 1 else p for p in picks]
    (run_dir / "picks.json").write_text(picks if isinstance(picks, str) else json.dumps(picks))
    out, err, rc = page.render(run_dir, do_serve=False)
    assert rc == 1 and err[0].startswith(f"ERROR:{code}"), err
    if code == "PICKS_UNKNOWN_N":
        assert err[0] == "ERROR:PICKS_UNKNOWN_N 99 (table has 1–6)"
    assert not (run_dir / "result.json").exists()


def test_render_is_lenient_about_wrapping_strings_and_long_reasons(world):
    run_dir, data, _ = recommend()
    long = "word " * 60
    (run_dir / "picks.json").write_text(json.dumps({"picks": [
        {"n": "1", "relevance": "3", "reason": long}, {"n": 2.0, "relevance": 2, "reason": "Fine."}]}))
    out, err, rc = page.render(run_dir, do_serve=False)
    assert rc == 0, err
    assert "NOTE: reason for n=1 trimmed to 160 chars" in out
    reason = next(l for l in "\n".join(out).splitlines() if l.strip().startswith("Why: word"))
    assert len(reason.strip()) <= len("Why: ") + 160


def test_render_merges_same_story_and_caps_channels(world):
    run_dir, data, _ = recommend()
    n_of = {c["videoId"]: c["n"] for c in data["candidates"]}
    write_picks(run_dir, [
        {"n": n_of[W.A_HOT], "relevance": 3, "reason": "Harness retrospective."},
        {"n": n_of[W.A_FRESH], "relevance": 3, "reason": "Unsupervised agents in a bank."},
        {"n": n_of[W.B_NEW], "relevance": 2, "reason": "MCP build.", "same_story_as": n_of[W.B_TWO]},
        {"n": n_of[W.B_TWO], "relevance": 1, "reason": "Memory patterns."},
        {"n": n_of[W.G_ONE], "relevance": 2, "reason": "Evals without benchmarks."},
    ])
    data["settings"]["per_channel_cap"] = 1
    (run_dir / "candidates.json").write_text(json.dumps(data))
    out, err, rc = page.render(run_dir, do_serve=False)
    assert rc == 0, err
    text = "\n".join(out)
    assert f"NOTE: n={n_of[W.B_TWO]} merged into n={n_of[W.B_NEW]} (same story)" in text
    assert "also covered by Beta Builds" in text
    # The second Alpha pick does not fit page 1 (1 per channel here); it leads page 2.
    assert "Unsupervised agents in a bank." not in text.split("--- END CHAT LIST")[0]
    code, out, _ = run_cli("next", "--no-serve")
    assert code == 0 and re.search(r"^4\. Evals for Agents in Regulated Workflows — Alpha Agents$", out, re.M)


def _html(out) -> str:
    return pathlib.Path(re.search(r"^OUTPUT_PATH: (.*)$", "\n".join(out), re.M).group(1)).read_text()


def test_every_row_is_rated_next_pages_through_and_the_rest_is_listed(world):
    run_dir, data, text = recommend()
    assert "one object per row" in text
    v = by_video(data)
    rate = {W.A_HOT: (3, "Harness retrospective."), W.S_GOOD: (3, "Production evals from outside."),
            W.A_FRESH: (2, "Unsupervised agents in a bank."), W.B_NEW: (2, "Hands-on MCP build."),
            W.G_ONE: (1, None), W.B_TWO: (0, None)}
    write_picks(run_dir, [{"n": v[k]["n"], "relevance": r, **({"reason": why} if why else {})}
                          for k, (r, why) in rate.items()])
    data["settings"]["picks"] = 2
    (run_dir / "candidates.json").write_text(json.dumps(data))
    out, err, rc = page.render(run_dir, do_serve=False)
    assert rc == 0, err
    chat = "\n".join(out)
    assert re.findall(r"^(\d+)\. ", chat, re.M) == ["1", "2"]
    assert '2 more picks ready: say "next".' in chat
    html = _html(out)
    assert "Also in the window" in html and "Agent Evals Without a Benchmark" in html   # rated 1
    assert "Hands-on MCP build." in html                                                # queued, with its reason
    assert "Agent Memory Patterns" not in html                                          # rated 0
    code, out, _ = run_cli("next", "--no-serve")
    assert code == 0 and "more picks, page 2" in out
    assert re.findall(r"^(\d+)\. ", out, re.M) == ["3", "4"] and "more picks ready" not in out
    res = json.loads((run_dir / "result.json").read_text())
    assert [i["num"] for i in res["items"]] == [1, 2, 3, 4] and res["pages_shown"] == 2
    assert len([r for r in store.read_shown() if r.get("event") == "shown"]) == 4
    code, out, _ = run_cli("resolve", "4")
    assert code == 0 and "URL: https://www.youtube.com/watch?v=" in out
    code, out, _ = run_cli("next", "--no-serve")
    assert code == 0 and out.startswith("NO_MORE:")
    assert len([r for r in store.read_shown() if r.get("event") == "shown"]) == 4


def test_ratings_need_reasons_only_for_threes_and_twos(world):
    run_dir, data, _ = recommend()
    write_picks(run_dir, [{"n": 1, "relevance": 0}, {"n": 2, "relevance": 1}, {"n": 3, "relevance": 2}])
    out, err, rc = page.render(run_dir, do_serve=False)
    assert rc == 1 and err[0].startswith("ERROR:PICKS_REASON_EMPTY n=3 is rated 2")


def test_all_topics_searches_every_topic_and_sections_by_topic(world):
    cfg = store.load_config()
    cfg["topics"]["news"]["queries"] = ["budget news"]
    store.save_config(cfg)
    week = yt_sources._key_file(world["replay"], f"search:{yt_sources.search_sp(7)}:20:ai agents")
    month = yt_sources.search_sp(14)
    W.put(world["replay"], f"search:{month}:20:ai agents", json.loads(week.read_text())["data"])
    W.put(world["replay"], f"search:{month}:20:budget news", {"entries": []})
    out, _, run_dir = collect.preflight("what did I miss on YouTube")
    assert "TOPIC: all" in out and "SOURCES: subs, affinity, search" in out
    o, e, code = collect.collect(run_dir)
    assert code == 0, e
    data = json.loads((run_dir / "candidates.json").read_text())
    text = "\n".join(o)
    assert data["counts"]["searches"] == 2 and data["topics"] == {"ai": "AI & agents", "news": "News"}
    topic = {c["videoId"]: c["topic"] for c in data["candidates"]}
    assert topic[W.A_HOT] == "ai" and topic[W.S_GOOD] == "ai" and topic[W.N_ONE] == "news"
    assert topic[W.G_ONE] == "ai"                     # an affinity channel, by its reports' tags
    assert "TOPICS: ai = AI & agents, news = News" in text and "| channel | topic |" in text
    v = by_video(data)
    write_picks(run_dir, [{"n": v[W.A_HOT]["n"], "relevance": 3, "reason": "Harness retrospective."},
                          {"n": v[W.N_ONE]["n"], "relevance": 2, "reason": "Tonight's budget, briefly."},
                          {"n": v[W.S_GOOD]["n"], "relevance": 2, "reason": "Production evals."}])
    out, err, rc = page.render(run_dir, do_serve=False)
    chat = "\n".join(out)
    assert rc == 0, err
    assert "TOP PICKS" in chat and "\nNEWS\n" in chat and "\nAI & AGENTS\n" in chat
    # "more like N" boosts the pick's own topic, not the run's pseudo-topic "all".
    res = json.loads((run_dir / "result.json").read_text())
    num = next(it["num"] for it in res["items"] if it["videoId"] == W.N_ONE)
    code, out, err = run_cli("feedback", "boost", str(num))
    assert code == 0 and out.startswith("BOOSTED: news keywords +="), err


def test_history_depth_follows_the_window_and_the_waiting_picks():
    now = W.NOW
    assert collect.history_depth(600, 7, [], now) == 320
    assert collect.history_depth(600, 1, [], now) == 100
    assert collect.history_depth(600, 14, [{"at": collect._iso(now - 20 * W.DAY)}], now) == 600
    assert collect.history_depth(300, 14, [], now) == 300


def test_a_version_1_config_keeps_choices_and_takes_new_defaults(world):
    p = store.config_path()
    cfg = json.loads(p.read_text())
    cfg["defaults"] = {"window_days": 14, "picks": 8, "min_duration_min": 10, "per_channel_cap": 2}
    p.write_text(json.dumps(cfg))
    loaded = store.load_config()
    assert loaded["defaults"]["picks"] == 12 and loaded["defaults"]["min_duration_min"] == 10
    store.save_config(loaded)
    saved = json.loads(p.read_text())
    assert saved["version"] == 2 and saved["defaults"] == {"min_duration_min": 10}
    assert saved["topics"] == cfg["topics"] and "sources" not in saved
    assert saved["account"] == {"mode": "takeout", "watched_check_depth": 300}


def test_replay_misses_fall_through_to_live_only_when_recording(tmp_path, monkeypatch):
    monkeypatch.setenv(yt_sources.REPLAY_ENV, str(tmp_path))
    monkeypatch.delenv(yt_sources.RECORD_ENV, raising=False)
    with pytest.raises(yt_sources.SourceError):
        yt_sources._replay("listing:somewhere")
    monkeypatch.setenv(yt_sources.RECORD_ENV, str(tmp_path))
    assert yt_sources._replay("listing:somewhere") is None
    with pytest.raises(yt_sources.SourceError):
        yt_sources._replay("personal:history")


def test_render_escapes_untrusted_titles_and_reasons(world):
    run_dir, data, _ = recommend()
    data["candidates"][0]["title"] = 'Agents <script>alert(1)</script> & "quotes"'
    data["candidates"][0]["channel"] = "<b>Evil</b>"
    (run_dir / "candidates.json").write_text(json.dumps(data))
    write_picks(run_dir, [{"n": 1, "relevance": 3, "reason": "Covers <img src=x onerror=alert(1)> safely."}])
    out, err, rc = page.render(run_dir, do_serve=False)
    html = pathlib.Path(re.search(r"^OUTPUT_PATH: (.*)$", "\n".join(out), re.M).group(1)).read_text()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "<img src=x" not in html and "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "<b>Evil</b>" not in html


def test_summarize_button_uses_raycast_only_when_enabled(world):
    run_dir, data, _ = recommend()
    write_picks(run_dir, [{"n": 1, "relevance": 3, "reason": "Good."}])
    out, _, _ = page.render(run_dir, do_serve=False)
    html = pathlib.Path(re.search(r"^OUTPUT_PATH: (.*)$", "\n".join(out), re.M).group(1)).read_text()
    assert 'data-copy="/video-lens https://www.youtube.com/watch?v=' in html and "raycast://" not in html
    cfg = store.load_config()
    cfg["ui"]["raycast_summarize"] = True
    store.save_config(cfg)
    page.render(run_dir, do_serve=False)
    html = pathlib.Path(re.search(r"^OUTPUT_PATH: (.*)$", "\n".join(out), re.M).group(1)).read_text()
    assert "raycast://script-commands/video-lens?arguments=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3D" in html


def test_still_waiting_returns_unacted_picks_once(world, monkeypatch):
    run_dir, data, _ = recommend()
    n_of = {c["videoId"]: c["n"] for c in data["candidates"]}
    write_picks(run_dir, [{"n": n_of[W.A_HOT], "relevance": 3, "reason": "Harness retrospective."},
                          {"n": n_of[W.B_NEW], "relevance": 2, "reason": "MCP build."}])
    page.render(run_dir, do_serve=False)
    run_cli("feedback", "watched", "2")                      # acted on: never comes back
    monkeypatch.setenv(yt_sources.NOW_ENV, str(W.NOW + 2 * W.DAY))
    run2, data2, text2 = recommend()
    assert W.A_HOT not in by_video(data2) and W.B_NEW not in by_video(data2)
    assert [w["videoId"] for w in data2["waiting"]] == [W.A_HOT]
    assert "STILL_WAITING: 1 earlier pick(s)" in text2
    write_picks(run2, [{"n": 1, "relevance": 2, "reason": "Something new."}])
    out, _, _ = page.render(run2, do_serve=False)
    chat = "\n".join(out)
    assert "STILL WAITING FROM LAST TIME" in chat and "shown Oct 21, not watched" in chat
    assert "Why: Harness retrospective." in chat
    # Shown twice now: it does not come back a third time.
    monkeypatch.setenv(yt_sources.NOW_ENV, str(W.NOW + 4 * W.DAY))
    _, data3, _ = recommend()
    assert W.A_HOT not in {w["videoId"] for w in data3["waiting"]}
    assert W.A_HOT not in by_video(data3)


# ---------- follow-ups ----------

def _rendered(world):
    run_dir, data, _ = recommend()
    write_picks(run_dir, [{"n": c["n"], "relevance": 2, "reason": f"Reason {c['n']}."} for c in data["candidates"][:4]])
    page.render(run_dir, do_serve=False)
    return run_dir, json.loads((run_dir / "result.json").read_text())


def test_resolve_prints_urls_for_list_numbers(world):
    run_dir, res = _rendered(world)
    code, out, err = run_cli("resolve", "1,3")
    assert code == 0
    urls = re.findall(r"^URL: (\S+)", out, re.M)
    assert urls == [res["items"][0]["url"], res["items"][2]["url"]]
    assert "video-lens" in out
    code, out, _ = run_cli("resolve", str(run_dir), "top2")
    assert len(re.findall(r"^URL:", out, re.M)) == 2
    code, out, err = run_cli("resolve", "9")
    assert code == 1 and err.startswith("ERROR:RESOLVE_UNKNOWN 9 (this run lists 1–4)")


def test_feedback_dismiss_mute_and_boost(world):
    run_dir, res = _rendered(world)
    first, second = res["items"][0], res["items"][1]
    code, out, _ = run_cli("feedback", "dismiss", "1")
    assert code == 0 and out.startswith("DISMISSED:")
    assert first["videoId"] in store.load_feedback()["dismissed"]
    code, out, _ = run_cli("feedback", "mute", "Beta Builds")
    assert code == 0 and "MUTED: Beta Builds" in out
    code, out, _ = run_cli("feedback", "boost", "2")
    assert code == 0 and out.startswith("BOOSTED: ai keywords +=")
    added = out.split("+= ")[1].split(" (undo")[0].split(", ")
    assert set(added) <= set(store.load_config()["topics"]["ai"]["keywords"])
    code, out, _ = run_cli("feedback", "unboost", second["videoId"])
    assert code == 0 and not set(added) & set(store.load_config()["topics"]["ai"]["keywords"])
    _, data, _ = recommend()
    left = by_video(data)
    assert first["videoId"] not in left
    assert not any(c["channelId"] == W.BETA for c in data["candidates"])
    code, out, _ = run_cli("feedback", "unmute", "Beta Builds")
    assert code == 0 and "UNMUTED" in out
    code, _, err = run_cli("feedback", "dismiss", "77")
    assert code == 1 and "FEEDBACK_UNKNOWN" in err


def test_stats_counts_summarised_after_recommendation(world):
    run_dir, res = _rendered(world)
    manifest = json.loads((world["library"] / "manifest.json").read_text())
    manifest["reports"].append({"videoId": res["items"][0]["videoId"], "title": "x", "channel": "Alpha Agents",
                                "tags": ["ai"], "generationDate": "2026-10-22"})
    (world["library"] / "manifest.json").write_text(json.dumps(manifest))
    code, out, _ = run_cli("stats")
    assert code == 0
    row = next(l for l in out.splitlines() if l.startswith("topic | ai |"))
    assert row == "topic | ai | 4 | 1 | 0 | 0 | 25%"


# ---------- topics ----------

def test_topics_apply_validates_and_merges(world, tmp_path):
    f = tmp_path / "proposal.json"

    def apply(payload, *extra):
        f.write_text(json.dumps(payload))
        return run_cli("topics", "apply", str(f), *extra)

    code, _, err = apply({"topics": {"Bad Key": {"label": "x"}}})
    assert code == 1 and "TOPICS_BAD_KEY" in err
    code, _, err = apply({"topics": {"dev": {"label": "Dev", "channels": [W.cid("neverseen")]}}})
    assert code == 1 and "TOPICS_UNKNOWN_CHANNEL" in err
    code, _, err = apply({"topics": {"dev": {"label": "Dev", "queries": list("abcdef")}}})
    assert code == 1 and "TOPICS_TOO_MANY_QUERIES" in err
    code, _, err = apply({"topics": {"dev": {"label": "News"}}})
    assert code == 1 and "TOPICS_DUPLICATE_LABEL dev and news" in err
    code, _, err = apply({"topics": {"a": {"label": "A", "channels": [W.ALPHA]}, "b": {"label": "B", "channels": [W.ALPHA]},
                                     "c": {"label": "C", "channels": [W.ALPHA]}}}, "--replace-all")
    assert code == 1 and "TOPICS_CHANNEL_SPREAD" in err
    run_cli("topics", "propose")        # resolves library channels (Gamma Labs) to ids, as in setup
    code, out, err = apply({"languages": ["en", "de"], "topics": {
        "dev": {"label": "Dev tools", "channels": [W.BETA, W.GAMMA], "queries": ["developer tools"],
                "report_tags": ["Developer-Tools"], "colour": "red"}}})
    assert code == 0, err
    assert "NOTE: dev: ignored unknown field(s) colour" in out
    cfg = store.load_config()
    assert set(cfg["topics"]) == {"ai", "news", "dev"}
    assert cfg["topics"]["dev"]["report_tags"] == ["developer tools"]
    assert cfg["defaults"]["languages"] == ["en", "de"]


def test_topic_edits_by_name_handle_and_number(world):
    W.put(world["replay"], "listing:@freshchan:3", W.listing(W.cid("freshchan"), "Fresh Chan", 5000, []))
    code, out, err = run_cli("topics", "add-channel", "ai", "@freshchan")
    assert code == 0 and "ADDED: Fresh Chan → ai" in out, err
    assert W.cid("freshchan") in store.load_config()["topics"]["ai"]["channels"]
    code, out, _ = run_cli("topics", "move-channel", "Fresh Chan", "news")
    assert code == 0
    cfg = store.load_config()
    assert W.cid("freshchan") in cfg["topics"]["news"]["channels"]
    assert W.cid("freshchan") not in cfg["topics"]["ai"]["channels"]
    code, out, _ = run_cli("topics", "add-query", "ai", "agent memory")
    assert "agent memory" in store.load_config()["topics"]["ai"]["queries"]
    code, out, err = run_cli("topics", "add", "cooking", "--label", "Cooking", "--query", "weeknight dinner")
    assert code == 0 and "ADDED: topic cooking" in out
    code, out, _ = run_cli("topics", "set", "cooking", "window_days", "14")
    assert store.load_config()["topics"]["cooking"]["window_days"] == 14
    code, out, _ = run_cli("topics", "list")
    assert "cooking | Cooking | 0 | weeknight dinner | 14d | never" in out
    code, _, err = run_cli("topics", "add-channel", "ai", "Nobody Knows This Channel")
    assert code == 1 and "CHANNEL_NOT_FOUND" in err
    # `add` and `set` are checked like `apply`: a 3rd topic per channel, a taken label, a bad number.
    run_cli("topics", "add-channel", "news", W.ALPHA)
    code, _, err = run_cli("topics", "add", "extra", "--label", "Extra", "--channel", W.ALPHA)
    assert code == 1 and "TOPICS_CHANNEL_SPREAD" in err
    assert "extra" not in store.load_config()["topics"]
    code, _, err = run_cli("topics", "set", "cooking", "label", "News")
    assert code == 1 and "TOPICS_DUPLICATE_LABEL" in err
    code, _, err = run_cli("topics", "set", "cooking", "window_days", "9999")
    assert code == 1 and "TOPICS_INVALID" in err
    assert store.load_config()["topics"]["cooking"]["window_days"] == 14


def test_topic_edits_need_a_channel_id(world):
    run_dir, res = _rendered(world)
    res["items"][0]["channelId"] = ""
    store.write_json(run_dir / "result.json", res)
    before = store.load_config()["topics"]
    for args in (("move-channel", "1", "news"), ("add-channel", "news", "1"),
                 ("add", "extra", "--label", "Extra", "--channel", "1")):
        code, _, err = run_cli("topics", *args)
        assert code == 1 and "CHANNEL_NOT_FOUND" in err, args
    assert store.load_config()["topics"] == before


def test_topics_propose_prints_evidence_and_a_proposal_path(world):
    code, out, err = run_cli("topics", "propose")
    assert code == 0, err
    assert out.startswith("LIBRARY: 9 reports · 3 subscriptions · 2 topics configured")
    assert "LIBRARY_TAGS: ai 8, ai agents 5, evals 3, news 1" in out
    assert f"{W.ALPHA} | Alpha Agents | yes | 5 reports (ai, ai agents) | Is the Agent Loop Over?" in out
    assert f"{W.GAMMA} | Gamma Labs | no | 3 reports" in out
    path = re.search(r"^PROPOSAL_PATH: (.*)$", out, re.M).group(1)
    assert path.startswith(str(store.cache_dir()))


# ---------- account ----------

def test_account_status_live_and_off(world):
    code, out, _ = run_cli("account", "status")
    assert "MODE: takeout" in out and "SUBSCRIPTIONS: 3 from takeout" in out and "API_KEY: not set" in out
    code, out, err = run_cli("account", "live", "--browser", "firefox")
    assert code == 0, err
    assert "MODE: live (firefox)" in out and "SYNCED: 3 subscriptions" in out and "in memory" in out
    code, out, _ = run_cli("account", "off")
    assert "MODE: takeout" in out


def test_account_live_reverts_when_the_browser_is_unreadable(world):
    W.put_error(world["replay"], "personal:subscriptions", "COOKIES_UNREADABLE")
    code, out, err = run_cli("account", "live")
    assert code == 1 and "ERROR:LIVE_SYNC_FAILED" in err and "Full Disk Access" in err
    assert store.load_config()["account"]["mode"] == "takeout"


def test_account_sync_reports_a_failure_as_a_failure(world):
    assert run_cli("account", "live")[0] == 0
    W.put_error(world["replay"], "personal:subscriptions", "SIGNED_OUT")
    code, out, err = run_cli("account", "sync", "--force")
    assert code == 1 and "ERROR:LIVE_SYNC_FAILED" in err and "SYNC_SKIPPED" not in out
    code, out, _ = run_cli("account", "sync")      # synced minutes ago: a skip, not a failure
    assert code == 0 and "SYNC_SKIPPED" in out


def test_account_probe_prints_counts_only(world):
    W.put(world["replay"], "personal:history", [f"hist{i:07d}" for i in range(300)])
    W.put(world["replay"], "personal:history-probe", {"entries": [
        {"id": "hist0000000", "title": "Private title", "duration": 300, "url": "https://www.youtube.com/watch?v=hist0000000"}]})
    code, out, _ = run_cli("account", "probe")
    assert code == 0
    assert "(a) HISTORY_DEPTH: asked 300, got 300 ids (paginates past the first page)" in out
    assert "(c) HISTORY_FIELDS: duration, id, title, url" in out
    assert "(c) HISTORY_DATES: 0/1" in out
    assert "hist0000000" not in out and "Private title" not in out


# ---------- gallery ----------

def test_gallery_index_lists_discover_pages(world):
    run_dir, res = _rendered(world)
    r = subprocess.run([sys.executable, str(REPO / "skills" / "video-lens-gallery" / "scripts" / "build_index.py"),
                        "--dir", str(world["library"])], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    manifest = json.loads((world["library"] / "manifest.json").read_text())
    assert manifest["recs"] == [{"filename": "recs/2026-10-21_ai.html", "topic": "ai", "label": "AI & agents",
                                 "date": "2026-10-21", "picks": 4}]
    index = (world["library"] / "index.html").read_text()
    assert 'id="discoverLink"' in index and "showDiscover(window.__MANIFEST__)" in index


def test_render_rebuilds_the_gallery_index(world):
    run_dir, res = _rendered(world)
    manifest = json.loads((world["library"] / "manifest.json").read_text())
    assert manifest["recs"][0]["filename"] == "recs/2026-10-21_ai.html"
    # Personal state never lands in the served tree.
    served = {p.name for p in world["library"].rglob("*") if p.is_file()}
    assert served <= {"manifest.json", "index.html", "2026-10-21_ai.html"}
