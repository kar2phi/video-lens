"""video-lens-recs scoring: hard filters, features, prior, shortlist (026 §7). No network."""
import math

import pytest

import recs_world  # noqa: F401  (puts the recs scripts on sys.path)
import scoring

NOW = 1_800_000_000.0
DAY = 86400


def cand(**kw):
    base = {"videoId": "aaaaaaaaaaa", "title": "A normal talk about agents", "channelId": "UC" + "a" * 22,
            "channel": "Chan", "duration": 900, "views": 1000, "published": NOW - 2 * DAY,
            "published_exact": True, "source": "subs", "subscribed": True}
    base.update(kw)
    return base


def ctx(**kw):
    base = {"now": NOW, "window_days": 7, "min_duration_s": 240, "max_duration_s": None,
            "summarised": set(), "dismissed": set(), "watched": set(), "shown": {}, "muted": set(),
            "exclude_keywords": [], "languages": ["en", "de"]}
    base.update(kw)
    return base


# ---------- features ----------

def test_age_curve_reaches_one_at_a_week_and_floors_at_six_hours():
    assert scoring.age_curve(7) == 1.0
    assert scoring.age_curve(30) == 1.0
    assert scoring.age_curve(0) == scoring.age_curve(0.25) == pytest.approx((0.25 / 7) ** 0.5)
    assert scoring.age_curve(3.5) == pytest.approx(0.5 ** 0.5)


def test_perf_is_views_against_the_channels_age_normalised_median():
    uploads = [(10_000, 10), (12_000, 12), (8_000, 20), (None, 3), (9_000, None)]
    baseline = scoring.channel_baseline(uploads)
    assert baseline == 10_000
    # 176K after 3 days on a ~10K channel is an outlier (026 §7.3 example: ≈15–21×).
    p = scoring.perf(176_000, 3, baseline)
    assert 20 < p < 30
    assert scoring.perf(10_000, 7, baseline) == pytest.approx(1.0)


def test_perf_is_unknown_without_enough_uploads_or_for_very_young_videos():
    assert scoring.channel_baseline([(1, 10), (2, 10)]) is None
    assert scoring.perf(100, 3, None) is None
    assert scoring.perf(139, 0.04, 20_000) is None      # an hour old: too early to tell
    assert scoring.perf(5_000, 0.6, 20_000) is not None


def test_velocity_uses_a_six_hour_floor():
    assert scoring.velocity(600, 0.01) == 100
    assert scoring.velocity(2400, 1) == 100
    assert scoring.velocity(None, 1) is None


def test_affinity_combines_reports_subscription_and_acted_picks():
    assert scoring.affinity(0, False, 0) == 0
    assert scoring.affinity(0, True, 0) == 1
    assert scoring.affinity(32, True, 3) == pytest.approx(math.log1p(32) + 1 + 0.5 * math.log1p(3))


def test_kw_score_matches_whole_phrases_and_profile_terms():
    text = "Building an MCP server for agent evals"
    assert scoring.kw_score(text, ["mcp", "agent evals", "rag"], []) == 2
    assert scoring.kw_score("mcpx tooling", ["mcp"], []) == 0
    assert scoring.kw_score(text, [], ["server", "evals", "unrelated"]) == pytest.approx(0.6)


def test_dup_groups_link_the_same_story_across_channels():
    cands = [cand(title="OpenAI ships GPT-6 with agents built in"),
             cand(title="GPT-6 ships: OpenAI agents built in, explained"),
             cand(title="Making sourdough bread at home")]
    assert scoring.dup_groups(cands) == {1: 0}
    assert scoring.similar_report("GPT-6 ships with agents built in", ["OpenAI ships GPT-6 with agents built in"])
    assert scoring.similar_report("Sourdough at home", ["OpenAI ships GPT-6"]) is None


def test_same_story_catches_reviews_of_one_product_by_its_rare_words():
    titles = ["Zephyr Phone review (emotional)", "Zephyr Phone Review: I See Why They Took Their Time",
              "Zephyr Phone - Unboxing, In-Depth Review & 1-Week Experience",
              *[f"Forge CLI tip {w}: speed up your builds" for w in ("one", "two", "three", "four", "five")],
              "How to Ship a Game With Forge CLI and Publish It", "I Gave Forge CLI My Hardest Animation Yet"]
    groups = scoring.dup_groups([cand(title=t) for t in titles])
    assert groups.get(1) == 0 and groups.get(2) == 0
    # A product name common in this table ('forge cli') does not make two videos one story.
    assert 8 not in groups and 9 not in groups
    library = ["Zephyr Phone Review: First Generation Fun!", "Weekly tooling round-up", "Forge CLI internals"]
    assert scoring.similar_report("Zephyr Phone review (emotional)", library) == library[0]
    assert scoring.similar_report("Forge CLI internals, part two: caching", ["Sourdough at home"]) is None


def test_same_story_ignores_the_topics_own_words():
    titles = ["Evals for Agents in Regulated Workflows", "How We Ship Agents With Evals at Scale",
              "Agent Evals Without a Benchmark", "Building an MCP Server for Your Team's Tools"]
    assert 1 in scoring.dup_groups([cand(title=t) for t in titles])   # a small table: every word is rare
    assert scoring.dup_groups([cand(title=t) for t in titles], common={"agents", "evals"}) == {}


def test_on_topic_needs_a_keyword_or_two_profile_terms():
    assert scoring.on_topic("Building an MCP server", ["mcp"], [])
    assert not scoring.on_topic("Router settings you should enable", ["mcp"], ["settings"])
    assert scoring.on_topic("Harness settings for agent evals", [], ["harness", "evals"])


# ---------- discovery gates ----------

@pytest.mark.parametrize("title,expect", [
    ("The SECRET Python Upgrade", True),
    ("INSANE new model just dropped!!", True),
    ("🔥🔥 You won't believe this agent", True),
    ("Is the Build System Dead?", False),
    ("A Big Lab Just Revealed How Its Engineers Write Code", False),
    ("KubeCon keynote with the CTO", False),
])
def test_clickbait_score(title, expect):
    assert (scoring.clickbait_score(title) >= 2) is expect


@pytest.mark.parametrize("title,langs,ok", [
    ("Agenten im Unternehmen: ein Überblick", ["en", "de"], True),
    ("人工智能代理的未来", ["en", "de"], False),
    ("人工智能代理的未来", ["en", "zh"], True),
    ("Будущее агентов", ["en"], False),
    ("Будущее агентов", ["ru"], True),
    ("2026 · 10 · 22", ["en"], True),
])
def test_script_allowed(title, langs, ok):
    assert scoring.script_allowed(title, langs) is ok


# ---------- hard filters ----------

@pytest.mark.parametrize("c,cx,reason", [
    (cand(), ctx(summarised={"aaaaaaaaaaa"}), "summarised"),
    (cand(), ctx(watched={"aaaaaaaaaaa"}), "watched"),
    (cand(), ctx(dismissed={"aaaaaaaaaaa"}), "dismissed"),
    (cand(), ctx(shown={"aaaaaaaaaaa": 1}), "shown"),
    (cand(), ctx(muted={"UC" + "a" * 22}), "muted"),
    (cand(channel="Loud Channel"), ctx(muted={"loud channel"}), "muted"),
    (cand(title="Huge giveaway inside"), ctx(exclude_keywords=["giveaway"]), "excluded keyword"),
    (cand(is_short=True), ctx(), "short or live"),
    (cand(live_status="is_upcoming"), ctx(), "short or live"),
    (cand(duration=45), ctx(), "short or live"),
    (cand(availability="subscriber_only"), ctx(), "members only"),
    (cand(duration=200), ctx(), "too short"),
    (cand(duration=4000), ctx(max_duration_s=3600), "too long"),
    (cand(published=NOW - 9 * DAY), ctx(), "older than window"),
])
def test_hard_filter_reasons(c, cx, reason):
    assert scoring.hard_filter(c, cx) == reason


def test_listing_dates_get_a_day_of_slack_exact_dates_do_not():
    approx = cand(published=NOW - 7.5 * DAY, published_exact=False)
    exact = cand(published=NOW - 7.5 * DAY, published_exact=True)
    assert scoring.hard_filter(approx, ctx()) is None
    assert scoring.hard_filter(exact, ctx()) == "older than window"


def test_discovery_gates_apply_only_outside_the_subscriptions():
    cjk = cand(title="人工智能代理的未来", source="search", subscribed=False)
    bait = cand(title="The SECRET Agent Trick NOBODY Knows", source="home", subscribed=False)
    tiny = cand(source="search", subscribed=False, subscribers=800, perf=1.0)
    tiny_hit = cand(source="search", subscribed=False, subscribers=800, perf=4.0)
    assert scoring.hard_filter(cjk, ctx()) == "language"
    assert scoring.hard_filter(bait, ctx()) == "clickbait"
    assert scoring.hard_filter(tiny, ctx()) == "small channel"
    assert scoring.hard_filter(tiny_hit, ctx()) is None
    # A subscribed channel is exempt from all three (026 §15 Q1 default).
    assert scoring.hard_filter({**cjk, "subscribed": True}, ctx()) is None
    assert scoring.hard_filter({**bait, "source": "subs", "subscribed": True}, ctx()) is None


# ---------- prior + shortlist ----------

def test_percentile_ranks_average_ties_and_rank_none_lowest():
    assert scoring.percentile_ranks([3, 1, 2]) == [1.0, 0.0, 0.5]
    assert scoring.percentile_ranks([1, 1, 5]) == [0.25, 0.25, 1.0]
    assert scoring.percentile_ranks([None, 2, 1]) == [0.0, 1.0, 0.5]
    assert scoring.percentile_ranks([7]) == [1.0]


def test_prior_weights_sum_to_one_and_order_candidates():
    best = cand(videoId="b" * 11, perf=20, kw=3, affinity=4, age_days=0.5, velocity=500)
    worst = cand(videoId="w" * 11, perf=0.2, kw=0, affinity=0, age_days=6, velocity=1)
    mid = cand(videoId="m" * 11, perf=2, kw=1, affinity=1, age_days=3, velocity=50)
    assert sum(scoring.PRIOR_WEIGHTS.values()) == pytest.approx(1.0)
    assert scoring.prior_scores([worst, best, mid]) == [0.0, 1.0, 0.5]


def _pool():
    pool = []
    for i in range(30):
        pool.append(cand(videoId=f"own{i:08d}", channelId=f"UC{i % 10:022d}", source="subs", prior=0.3 + i / 1000))
    for i in range(20):
        pool.append(cand(videoId=f"src{i:08d}", channelId=f"UCs{i:021d}", source="search", subscribed=False, prior=0.9))
    for i in range(10):
        pool.append(cand(videoId=f"hom{i:08d}", channelId=f"UCh{i:021d}", source="home", subscribed=False, prior=0.8))
    return pool


def test_shortlist_quotas_keep_room_for_your_channels():
    short = scoring.shortlist(_pool(), size=40)
    groups = [scoring.source_group(c) for c in short]
    assert len(short) == 40
    assert groups.count("search") == 10
    assert groups.count("home") == 6
    assert groups.count("own") == 24
    assert [c["prior"] for c in short] == sorted((c["prior"] for c in short), reverse=True)


def test_shortlist_caps_one_channel_dumping_a_conference():
    dump = [cand(videoId=f"dmp{i:08d}", channelId="UC" + "d" * 22, prior=0.99) for i in range(20)]
    others = [cand(videoId=f"oth{i:08d}", channelId=f"UC{i:022d}", prior=0.1) for i in range(10)]
    short = scoring.shortlist(dump + others, size=13)
    assert sum(c["channelId"] == "UC" + "d" * 22 for c in short) == 3
    # With rows to spare, the channel may take up to twice its share, no more.
    short = scoring.shortlist(dump + others, size=40)
    assert sum(c["channelId"] == "UC" + "d" * 22 for c in short) == 6 and len(short) == 16
    # A channel the user summarises often gets a raised cap ahead of the rest.
    short = scoring.shortlist(dump + others, size=13, channel_caps={"UC" + "d" * 22: 6})
    assert sum(c["channelId"] == "UC" + "d" * 22 for c in short) == 6 and len(short) == 13


def test_shortlist_discovery_caps_give_way_when_the_table_has_room():
    pool = [c for c in _pool() if c["source"] != "subs"][:25] + _pool()[:5]
    short = scoring.shortlist(pool, size=40)
    groups = [scoring.source_group(c) for c in short]
    assert len(short) == 30 and groups.count("own") == 5 and groups.count("search") == 20


def test_shortlist_by_topic_gives_every_topic_a_share():
    big = [cand(videoId=f"big{i:08d}", channelId=f"UCb{i:021d}", topic="ai", prior=0.9) for i in range(40)]
    small = [cand(videoId=f"{t}{i:08d}", channelId=f"UC{t}{i:020d}", topic=t, prior=0.1)
             for t in ("cl", "st") for i in range(5)]
    short = scoring.shortlist_by_topic(big + small, size=15)
    topics = [c["topic"] for c in short]
    assert len(short) == 15 and topics.count("cl") == 5 and topics.count("st") == 5
    # Topics with fewer candidates than their share leave the rest to the best of the others.
    short = scoring.shortlist_by_topic(big + small[:2], size=15)
    assert [c["topic"] for c in short].count("ai") == 13
