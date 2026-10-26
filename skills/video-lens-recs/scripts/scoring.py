"""Pure ranking functions for video-lens-recs: hard filters, features, prior, shortlist.

No I/O and no clock: callers pass `now` and the state they read. Every function here is
unit-tested in tests/test_recs_scoring.py. Concept 026 §7 is the spec.
"""
import math
import re
import statistics
import unicodedata

# ---------- text ----------

STOPWORDS = set("""
a an and are as at be but by for from has have how i in into is it its of on or our so
that the their this to was we what when where which who why will with you your vs not
just more most new all can do does one about after before over under than then them they
der die das und ist nicht ein eine zu mit den auf für sich auch von dem des im wird sind
werden oder aber wie was wer neue neuer neues
""".split())

WORD_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.U)


def tokens(text: str) -> list[str]:
    """Lowercase content words; stopwords and 1-letter words dropped."""
    return [w for w in WORD_RE.findall((text or "").lower())
            if len(w) > 1 and w not in STOPWORDS]


def jaccard(a, b) -> float:
    a, b = set(a), set(b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def phrase_in(phrase: str, text: str) -> bool:
    """Whole-word, case-insensitive phrase match ('mcp' matches 'MCP server', not 'mcpx')."""
    phrase = " ".join(phrase.lower().split())
    if not phrase:
        return False
    return re.search(r"(?<![\w])" + re.escape(phrase) + r"(?![\w])", text.lower()) is not None


# ---------- discovery gates ----------

HYPE_PHRASES = (
    "secret", "insane", "shocking", "unbelievable", "mind blowing", "mind-blowing",
    "mindblowing", "crazy", "just dropped", "you won't believe", "you wont believe",
    "game changer", "game-changer", "exposed", "destroyed", "nobody is talking about",
    "nobody talks about", "no one is talking about", "jaw dropping", "jaw-dropping",
)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿\U0001F000-\U0001F2FF]")


def clickbait_score(title: str) -> int:
    """Cheap heuristic: hype phrases, shouted words, emoji runs, '!!'. ≥ 2 is clickbait."""
    t = title or ""
    low = t.lower()
    score = sum(1 for p in HYPE_PHRASES if phrase_in(p, low))
    shouted = [w for w in re.findall(r"[^\W\d_]+", t) if len(w) >= 5 and w.isupper()]
    score += min(len(shouted), 2)
    if len(EMOJI_RE.findall(t)) >= 2:
        score += 1
    if "!!" in t or "?!" in t:
        score += 1
    return score


LANGUAGE_SCRIPTS = {
    "ru": "CYRILLIC", "uk": "CYRILLIC", "bg": "CYRILLIC", "sr": "CYRILLIC",
    "el": "GREEK", "ar": "ARABIC", "fa": "ARABIC", "ur": "ARABIC", "he": "HEBREW",
    "hi": "DEVANAGARI", "mr": "DEVANAGARI", "ne": "DEVANAGARI", "bn": "BENGALI",
    "ta": "TAMIL", "te": "TELUGU", "th": "THAI", "ko": "HANGUL",
    "zh": "CJK", "ja": "CJK", "ka": "GEORGIAN", "hy": "ARMENIAN",
}
SCRIPT_PREFIXES = ("LATIN", "CYRILLIC", "GREEK", "ARABIC", "HEBREW", "DEVANAGARI", "BENGALI",
                   "TAMIL", "TELUGU", "THAI", "HANGUL", "GEORGIAN", "ARMENIAN")


def _char_script(ch: str) -> str | None:
    try:
        name = unicodedata.name(ch)
    except ValueError:
        return None
    if name.startswith(("CJK", "HIRAGANA", "KATAKANA")):
        return "CJK"
    for prefix in SCRIPT_PREFIXES:
        if name.startswith(prefix):
            return prefix
    return None


def dominant_script(text: str) -> str | None:
    counts: dict[str, int] = {}
    for ch in text or "":
        if ch.isalpha():
            s = _char_script(ch)
            if s:
                counts[s] = counts.get(s, 0) + 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def script_allowed(title: str, languages) -> bool:
    """True when the title's dominant script belongs to one of `languages`.

    Latin covers every language not in LANGUAGE_SCRIPTS (en, de, fr, es, …). A title
    with no letters at all passes.
    """
    script = dominant_script(title)
    if script is None:
        return True
    allowed = {LANGUAGE_SCRIPTS.get(lang.split("-")[0].lower(), "LATIN") for lang in (languages or ["en"])}
    return script in allowed


# ---------- hard filters ----------

DISCOVERY_SOURCES = ("search", "home")


def hard_filter(c: dict, ctx: dict) -> str | None:
    """Return the reason a candidate is dropped, or None to keep it.

    ctx keys: now, window_days, min_duration_s, max_duration_s, summarised (set),
    dismissed (set), watched (set), shown (videoId → count), muted (set of channel ids
    and lowercased titles), exclude_keywords, languages.
    The order follows 026 §7.2: cheapest and most certain first. The reason strings are
    the counters in the run summary.
    """
    vid = c["videoId"]
    if vid in ctx.get("summarised", ()):
        return "summarised"
    if vid in ctx.get("watched", ()):
        return "watched"
    if vid in ctx.get("dismissed", ()):
        return "dismissed"
    shown = ctx.get("shown", {}).get(vid, 0)
    if shown:
        return "shown"
    muted = ctx.get("muted", set())
    if (c.get("channelId") and c["channelId"] in muted) or (c.get("channel") or "").lower() in muted:
        return "muted"
    text = f"{c.get('title', '')} {c.get('description', '')}"
    if any(phrase_in(k, text) for k in ctx.get("exclude_keywords", ())):
        return "excluded keyword"
    if c.get("is_short") or c.get("live_status") in ("is_upcoming", "is_live", "post_live", "upcoming"):
        return "short or live"
    if c.get("availability") in ("subscriber_only", "premium_only", "needs_auth"):
        return "members only"
    dur = c.get("duration")
    if dur is not None:
        if dur < 61:
            return "short or live"
        if dur < ctx.get("min_duration_s", 0):
            return "too short"
        if ctx.get("max_duration_s") and dur > ctx["max_duration_s"]:
            return "too long"
    published = c.get("published")
    if published is not None:
        # Listing dates are approximate (day-level, sometimes 1.5 days off): allow a day of slack.
        slack = 0 if c.get("published_exact") else 1
        if (ctx["now"] - published) / 86400 > ctx["window_days"] + slack:
            return "older than window"
    if c.get("source") in DISCOVERY_SOURCES and not c.get("subscribed"):
        if not script_allowed(c.get("title", ""), ctx.get("languages")):
            return "language"
        if clickbait_score(c.get("title", "")) >= 2:
            return "clickbait"
        # Only once features are in: Data API results carry subscriber counts from the
        # start, and a breakout upload (perf ≥ 3) must get its chance to pass.
        subs = c.get("subscribers")
        if subs is not None and subs < 5000 and "perf" in c and (c["perf"] or 0) < 3:
            return "small channel"
    return None


# ---------- features ----------

def age_curve(age_days: float) -> float:
    """Share of its first-week views a video has after `age_days` (026 §7.3)."""
    return min(1.0, max(age_days, 0.25) / 7) ** 0.5


def v_norm(views, age_days) -> float | None:
    if views is None or age_days is None:
        return None
    return views / age_curve(age_days)


def channel_baseline(uploads) -> float | None:
    """Median age-normalised views over a channel's recent uploads, or None when fewer
    than 3 uploads carry views. `uploads` is an iterable of (views, age_days)."""
    norms = [v_norm(v, a) for v, a in uploads if v is not None and a is not None]
    norms = [n for n in norms if n is not None]
    if len(norms) < 3:
        return None
    med = statistics.median(norms)
    return med if med > 0 else None


PERF_MIN_AGE_DAYS = 0.5


def perf(views, age_days, baseline) -> float | None:
    """Views relative to the channel's usual, both age-normalised; None when unknown.

    Under 12 hours the age curve says too little (an hour-old upload reads as 0.0×), so
    perf stays unknown and velocity carries the signal.
    """
    if age_days is not None and age_days < PERF_MIN_AGE_DAYS:
        return None
    vn = v_norm(views, age_days)
    if vn is None or not baseline:
        return None
    return vn / baseline


def velocity(views, age_days) -> float | None:
    if views is None or age_days is None:
        return None
    return views / max(age_days * 24, 6)


def affinity(report_count: int, subscribed: bool, acted_count: int) -> float:
    return math.log1p(report_count) + (1.0 if subscribed else 0.0) + 0.5 * math.log1p(acted_count)


def kw_score(text: str, topic_keywords, profile_terms) -> float:
    """Topic keyword hits count 1, taste-profile term hits count 0.3."""
    hits = sum(1 for k in topic_keywords if phrase_in(k, text))
    words = set(tokens(text))
    return hits + 0.3 * len(words & set(profile_terms))


def on_topic(text: str, topic_keywords, profile_terms) -> bool:
    """A topic keyword in the text, or at least two taste-profile terms. One profile term
    alone ('code', 'review') says little about a video from a channel that posts on many things."""
    if any(phrase_in(k, text) for k in topic_keywords):
        return True
    return len(set(tokens(text)) & set(profile_terms)) >= 2


# ---------- same story ----------

def doc_freq(titles) -> dict:
    df: dict = {}
    for t in titles:
        for w in set(tokens(t)):
            df[w] = df.get(w, 0) + 1
    return df


def same_story(a: set, b: set, df: dict, n_titles: int, threshold: float = 0.5,
               common=frozenset()) -> bool:
    """Two title token sets cover the same story: most words shared, or a looser overlap that
    includes two words rare in this set of titles ('Zephyr Phone review' vs 'Zephyr Phone
    review (emotional)'). Common product names ('claude code') are not rare in a topic's table, and
    the topics' own words (`common`) never are: two eval talks are not one story."""
    if len(a) < 3 or not b:
        return False
    j = jaccard(a, b)
    if j >= threshold:
        return True
    rare_max = max(3, math.ceil(0.1 * n_titles))
    rare = [w for w in a & b if df.get(w, 0) <= rare_max and w not in common]
    return j >= 0.3 and len(rare) >= 2


def dup_groups(cands, threshold: float = 0.5, common=frozenset()) -> dict:
    """Map candidate index → index of the earlier candidate it repeats."""
    titles = [c.get("title", "") for c in cands]
    toks = [set(tokens(t)) for t in titles]
    df = doc_freq(titles)
    out = {}
    for i in range(len(cands)):
        for j in range(i):
            if j in out:
                continue
            if same_story(toks[i], toks[j], df, len(titles), threshold, common):
                out[i] = j
                break
    return out


def similar_report(title: str, report_titles, threshold: float = 0.5, df: dict | None = None,
                   common=frozenset()) -> str | None:
    """The first report title that covers the same story; `df` is doc_freq(report_titles)."""
    t = set(tokens(title))
    if len(t) < 3:
        return None
    report_titles = list(report_titles)
    df = df if df is not None else doc_freq(report_titles)
    for rt in report_titles:
        if same_story(t, set(tokens(rt)), df, len(report_titles), threshold, common):
            return rt
    return None


# ---------- prior + shortlist ----------

PRIOR_WEIGHTS = {"perf": 0.30, "kw": 0.20, "affinity": 0.20, "fresh": 0.15, "velocity": 0.15}


def percentile_ranks(values) -> list[float]:
    """Rank-percentile in [0, 1] with ties averaged; None ranks lowest."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [1.0 if values[0] is not None else 0.0]
    keyed = sorted(range(n), key=lambda i: (values[i] is not None, values[i] if values[i] is not None else 0))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        vi = values[keyed[i]]
        while j + 1 < n and values[keyed[j + 1]] == vi:
            j += 1
        avg = (i + j) / 2
        for k in range(i, j + 1):
            ranks[keyed[k]] = avg / (n - 1)
        i = j + 1
    return ranks


def prior_scores(cands, weights: dict | None = None) -> list[float]:
    """0.30·perf + 0.20·kw + 0.20·affinity + 0.15·fresh + 0.15·velocity, each term a
    rank-percentile within this pool. An unknown perf counts as the channel's usual (1.0).
    `weights` overrides PRIOR_WEIGHTS (the eval compares variants)."""
    weights = weights or PRIOR_WEIGHTS
    cols = {
        "perf": [c.get("perf") if c.get("perf") is not None else 1.0 for c in cands],
        "kw": [c.get("kw", 0.0) for c in cands],
        "affinity": [c.get("affinity", 0.0) for c in cands],
        "fresh": [-c["age_days"] if c.get("age_days") is not None else None for c in cands],
        "velocity": [c.get("velocity") for c in cands],
    }
    pct = {k: percentile_ranks(v) for k, v in cols.items()}
    return [round(sum(weights[k] * pct[k][i] for k in weights), 4) for i in range(len(cands))]


SHORTLIST_QUOTAS = {"own_min": 24, "search_max": 10, "home_max": 6}


def source_group(c) -> str:
    if c.get("source") in ("subs", "affinity") or c.get("subscribed"):
        return "own"
    return c.get("source", "search")


def channel_key(c) -> str:
    return c.get("channelId") or c.get("channel") or c["videoId"]


def shortlist(cands, size: int = 40, quotas=None, per_channel: int = 3, taken=None,
              channel_caps=None) -> list:
    """Top `size` by prior with source quotas (026 §7.3) and a per-channel cap, so a
    conference dump from one channel cannot fill the table. The cap is one more than render
    shows per channel on a page: the spare absorbs a same-story merge. `channel_caps`
    raises it for named channels.

    `taken` continues an existing selection (its channels count towards the cap)."""
    q = {**SHORTLIST_QUOTAS, **(quotas or {})}
    caps = {"search": q["search_max"], "home": q["home_max"]}
    ordered = sorted(cands, key=lambda c: -c.get("prior", 0))
    taken = list(taken or [])
    ids = {c["videoId"] for c in taken}
    per_chan: dict = {}
    for c in taken:
        per_chan[channel_key(c)] = per_chan.get(channel_key(c), 0) + 1
    per_group = {"own": 0, "search": 0, "home": 0}
    start = len(taken)

    def take(c, capped=True, scale=1):
        ch = channel_key(c)
        g = source_group(c)
        chan_cap = max((channel_caps or {}).get(ch, per_channel), scale * per_channel)
        if c["videoId"] in ids or per_chan.get(ch, 0) >= chan_cap:
            return False
        if capped and g in caps and per_group[g] >= caps[g]:
            return False
        taken.append(c)
        ids.add(c["videoId"])
        per_chan[ch] = per_chan.get(ch, 0) + 1
        per_group[g] = per_group.get(g, 0) + 1
        return True

    # Reserve the own-channel minimum, then discovery up to its caps, then fill. The caps
    # only make room: rows nobody else wants go to the best of the rest, and a busy channel
    # may take up to twice its share before a row stays empty.
    for c in ordered:
        if per_group["own"] >= q["own_min"] or len(taken) - start >= size:
            break
        if source_group(c) == "own":
            take(c)
    for capped, scale in ((True, 1), (False, 1), (False, 2)):
        for c in ordered:
            if len(taken) - start >= size:
                break
            take(c, capped, scale)
    return sorted(taken, key=lambda c: -c.get("prior", 0))


def shortlist_by_topic(cands, size: int = 40, per_channel: int = 3, channel_caps=None) -> list:
    """All-topics runs: an equal share of the table per topic (its quotas scaled to the
    share), then the best of the rest, so the biggest topic cannot fill the table."""
    groups: dict = {}
    for c in cands:
        groups.setdefault(c.get("topic") or "", []).append(c)
    if len(groups) <= 1:
        return shortlist(cands, size, per_channel=per_channel, channel_caps=channel_caps)
    share = max(1, size // len(groups))
    quotas = {k: max(1, math.ceil(v * share / size)) for k, v in SHORTLIST_QUOTAS.items()}
    taken: list = []
    for group in groups.values():
        taken = shortlist(group, share, quotas, per_channel, taken, channel_caps)
    ids = {t["videoId"] for t in taken}
    rest = [c for c in cands if c["videoId"] not in ids]
    taken = shortlist(rest, size - len(taken), {"own_min": 0}, per_channel, taken, channel_caps)
    return sorted(taken, key=lambda c: -c.get("prior", 0))
