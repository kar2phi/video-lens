#!/usr/bin/env python3
"""video-lens-recs: recommend YouTube videos on a topic, ranked with reasons (concept 026).

    recs.py recommend -- "<request>" [--topic KEY]   preflight + collect: run dir, profile, candidate table
    recs.py render RUN_DIR [--no-serve]              validate picks.json, write + serve the Discover page
    recs.py next [RUN_DIR] [--no-serve]              the next page of picks from the same run, no fetching
    recs.py resolve [RUN_DIR] 1,4                    the YouTube URLs behind numbers in the chat list
    recs.py feedback dismiss|watched|mute|unmute|boost|unboost TARGET
    recs.py topics list|show|propose|apply|add|delete|add-channel|remove-channel|move-channel|
                   add-query|remove-query|add-keyword|remove-keyword|set
    recs.py account status|import-takeout PATH|live|off|sync|probe
    recs.py stats
    recs.py preflight -- "<request>" / recs.py collect RUN_DIR   (the two halves of recommend)

Every line the agent acts on is prefixed (RUN_DIR:, ERROR:CODE …). Errors go to stderr with
exit status 1 and name the fix. Stdlib only, plus the yt-dlp CLI.
"""
import argparse
import datetime
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import collect  # noqa: E402
import page  # noqa: E402
import scoring  # noqa: E402
import store  # noqa: E402
import takeout  # noqa: E402
import yt_sources as yt  # noqa: E402
from yt_sources import SourceError  # noqa: E402

TOPIC_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}$")
MAX_TOPICS_PER_CHANNEL = 2


class CliError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def emit(out=(), err=(), code=0) -> int:
    for line in out:
        print(line)
    for line in err:
        print(line, file=sys.stderr)
    return code


# ---------- recommend / render ----------

def cmd_preflight(args) -> int:
    out, err, _ = collect.preflight(" ".join(args.request), args.topic)
    return emit(out, err, 1 if err else 0)


def cmd_collect(args) -> int:
    out, err, code = collect.collect(pathlib.Path(args.run_dir))
    return emit(out, err, code)


def cmd_recommend(args) -> int:
    out, err, run_dir = collect.preflight(" ".join(args.request), args.topic)
    if run_dir is None:
        return emit(out, err, 1 if err else 0)
    emit(out)
    print()
    out2, err2, code = collect.collect(run_dir)
    return emit(out2, err2, code)


def cmd_render(args) -> int:
    out, err, code = page.render(pathlib.Path(args.run_dir), do_serve=not args.no_serve)
    return emit(out, err, code)


def cmd_next(args) -> int:
    run_dir = pathlib.Path(args.run_dir) if args.run_dir else last_run_dir()
    out, err, code = page.render(run_dir, do_serve=not args.no_serve, advance=True)
    return emit(out, err, code)


# ---------- run lookup ----------

def last_run_dir() -> pathlib.Path:
    ptr = store.read_json(store.cache_dir() / "last_run.json", {}) or {}
    d = pathlib.Path(ptr.get("run_dir", ""))
    if not ptr.get("run_dir") or not (d / "result.json").exists():
        raise CliError("NO_RUN", "no rendered recommendation run yet (runs expire after 7 days); run recommend first")
    return d


def run_result(run_dir: str | None) -> tuple[pathlib.Path, dict]:
    d = pathlib.Path(run_dir) if run_dir else last_run_dir()
    res = store.read_json(d / "result.json")
    if not res:
        raise CliError("RUN_DIR_INVALID", f"{d} has no result.json; render it first")
    return d, res


def parse_numbers(spec: str, max_num: int) -> list[int]:
    s = spec.lower().replace("and", ",").replace("&", ",")
    m = re.fullmatch(r"\s*top\s*(\d+)\s*", s)
    if m:
        return list(range(1, min(int(m.group(1)), max_num) + 1))
    nums = []
    for part in re.split(r"[,\s]+", s.strip()):
        if not part:
            continue
        r = re.fullmatch(r"#?(\d+)(?:-(\d+))?", part)
        if not r:
            raise CliError("RESOLVE_BAD_SPEC", f"{part!r}: use numbers from the list, e.g. 1,4 or 1-3 or top3")
        a, b = int(r.group(1)), int(r.group(2) or r.group(1))
        nums += list(range(a, b + 1))
    bad = [n for n in nums if n < 1 or n > max_num]
    if bad:
        raise CliError("RESOLVE_UNKNOWN", f"{bad[0]} (this run lists 1–{max_num})")
    return list(dict.fromkeys(nums))


def cmd_resolve(args) -> int:
    parts = list(args.spec)
    run_dir = None
    if parts and (pathlib.Path(parts[0]).is_dir() or "/" in parts[0]):
        run_dir = parts.pop(0)
    _, res = run_result(run_dir)
    items = {it["num"]: it for it in res["items"]}
    nums = parse_numbers(" ".join(parts), max(items) if items else 0)
    for n in nums:
        it = items[n]
        print(f"URL: {it['url']}  ({n}. {it['title']} — {it['channel']})")
    print("NEXT: run the video-lens skill on each URL above, one after the other.")
    return 0


# ---------- feedback ----------

def _iso_now() -> str:
    return datetime.datetime.fromtimestamp(yt.now()).isoformat(timespec="seconds")


def target_video(target: str, run_dir: str | None) -> dict:
    """A number from the last run, a video id or a URL → {videoId, title, channel, channelId}."""
    t = target.strip().lstrip("#")
    if t.isdigit() and len(t) <= 3:
        _, res = run_result(run_dir)
        for it in res["items"]:
            if it["num"] == int(t):
                return it
        raise CliError("FEEDBACK_UNKNOWN", f"{t} is not in the last list (1–{len(res['items'])})")
    m = re.search(r"(?:v=|youtu\.be/|/live/|/embed/)([A-Za-z0-9_-]{11})", t)
    vid = m.group(1) if m else t
    if not yt.VIDEO_ID_RE.fullmatch(vid):
        raise CliError("FEEDBACK_UNKNOWN", f"{target!r} is not a list number, video id or YouTube URL")
    for rec in reversed(store.read_shown()):
        if rec["videoId"] == vid and rec.get("title"):
            return {"videoId": vid, "title": rec["title"], "channel": rec.get("channel"),
                    "channelId": rec.get("channelId"), "topic": rec.get("topic")}
    return {"videoId": vid, "title": "", "channel": "", "channelId": ""}


def resolve_channel(target: str, run_dir: str | None = None) -> dict:
    """A list number, UC id, @handle, channel URL or channel name → {id, title}."""
    t = target.strip()
    if t.lstrip("#").isdigit() and len(t) <= 4:
        it = target_video(t, run_dir)
        return {"id": it.get("channelId") or "", "title": it.get("channel") or ""}
    m = re.search(r"(UC[A-Za-z0-9_-]{22})", t)
    if m:
        cid = m.group(1)
        title = next((c["title"] for c in store.load_subscriptions().get("channels", []) if c["id"] == cid), "")
        return {"id": cid, "title": title}
    low = t.lower()
    for c in store.load_subscriptions().get("channels", []):
        if c.get("title", "").lower() == low:
            return {"id": c["id"], "title": c["title"]}
    try:
        _, res = run_result(run_dir)
        for it in res["items"]:
            if (it.get("channel") or "").lower() == low:
                return {"id": it.get("channelId") or "", "title": it["channel"]}
    except CliError:
        pass
    for name, cid in store.load_channel_ids().items():
        if name.lower() == low:
            return {"id": cid, "title": name}
    for cid, title in (store.load_config().get("channel_titles") or {}).items():
        if (title or "").lower() == low:
            return {"id": cid, "title": title}
    for r in store.load_reports():
        if (r.get("channel") or "").lower() == low and r.get("channelId"):
            return {"id": r["channelId"], "title": r["channel"]}
    if t.startswith("@") or "youtube.com/" in t:
        try:
            lst = yt.channel_listing(t if t.startswith("@") else t, yt.Cache(store.cache_dir() / "sources"), limit=3)
        except SourceError as e:
            raise CliError("CHANNEL_NOT_FOUND", f"{t}: {e.code}")
        if lst.get("channelId"):
            return {"id": lst["channelId"], "title": lst.get("channel", "")}
    raise CliError("CHANNEL_NOT_FOUND", f"{t!r}: give a list number, an @handle, a channel URL or its exact name")


def boost_keywords(title: str, existing) -> list[str]:
    have = {k.lower() for k in existing}
    words = [w for w in scoring.tokens(title) if len(w) >= 4 and w not in collect.GENERIC_WORDS and w not in have]
    return list(dict.fromkeys(words))[:3]


def cmd_feedback(args) -> int:
    action = args.action
    target = " ".join(args.target)
    fb = store.load_feedback()
    if action in ("mute", "unmute"):
        ch = resolve_channel(target, args.run)
        if action == "mute":
            if not any((m.get("id") and m["id"] == ch["id"]) or (m.get("title", "").lower() == ch["title"].lower() and ch["title"])
                       for m in fb["muted_channels"]):
                fb["muted_channels"].append({**ch, "at": _iso_now()})
            store.save_feedback(fb)
            print(f"MUTED: {ch['title'] or ch['id']} — dropped from every source (undo: feedback unmute)")
        else:
            fb["muted_channels"] = [m for m in fb["muted_channels"]
                                    if not ((ch["id"] and m.get("id") == ch["id"]) or
                                            (ch["title"] and m.get("title", "").lower() == ch["title"].lower()))]
            store.save_feedback(fb)
            print(f"UNMUTED: {ch['title'] or ch['id']}")
        return 0

    it = target_video(target, args.run)
    vid = it["videoId"]
    label = it.get("title") or vid
    if action == "dismiss":
        if vid not in fb["dismissed"]:
            fb["dismissed"].append(vid)
        store.save_feedback(fb)
        store.append_shown([{"event": "outcome", "videoId": vid, "outcome": "dismissed", "at": _iso_now()}])
        print(f"DISMISSED: {label} — never shown again")
    elif action == "watched":
        store.append_shown([{"event": "outcome", "videoId": vid, "outcome": "watched", "at": _iso_now()}])
        print(f"WATCHED: {label} — recorded, never shown again")
    elif action in ("boost", "unboost"):
        cfg = store.load_config()
        topic = args.topic or it.get("topic")
        if not topic:
            try:
                _, res = run_result(args.run)
                topic = res["topic"]
            except CliError:
                pass
        if topic not in cfg["topics"]:
            raise CliError("TOPIC_UNKNOWN", f"which topic? pass --topic KEY ({', '.join(cfg['topics'])})")
        t = cfg["topics"][topic]
        if action == "boost":
            words = boost_keywords(it.get("title") or "", t.get("keywords", []))
            if not words:
                raise CliError("BOOST_NOTHING_NEW", f"{label!r} adds no new keywords to {topic}")
            t["keywords"] = [*t.get("keywords", []), *words]
            fb["boosts"].append({"videoId": vid, "topic": topic, "keywords": words, "at": _iso_now()})
            store.save_config(cfg)
            store.save_feedback(fb)
            print(f"BOOSTED: {topic} keywords += {', '.join(words)} (undo: feedback unboost {vid})")
        else:
            gone = [b for b in fb["boosts"] if b["videoId"] == vid and b.get("topic") == topic]
            if not gone:
                raise CliError("BOOST_NOT_FOUND", f"no boost recorded for {vid} in {topic}")
            drop = {k for b in gone for k in b["keywords"]}
            t["keywords"] = [k for k in t.get("keywords", []) if k not in drop]
            fb["boosts"] = [b for b in fb["boosts"] if b not in gone]
            store.save_config(cfg)
            store.save_feedback(fb)
            print(f"UNBOOSTED: {topic} keywords -= {', '.join(sorted(drop))}")
    return 0


# ---------- topics ----------

def known_channels(cfg: dict | None = None) -> dict:
    """Channel id → title for every channel the user can put in a topic."""
    out = {c["id"]: c.get("title", "") for c in store.load_subscriptions().get("channels", [])}
    for name, cid in store.load_channel_ids().items():
        out.setdefault(cid, name)
    for r in store.load_reports():
        if r.get("channelId"):
            out.setdefault(r["channelId"], r.get("channel", ""))
    cfg = cfg or store.load_config()
    for t in cfg["topics"].values():
        for cid in t.get("channels", []):
            out.setdefault(cid, "")
    for cid, title in (cfg.get("channel_titles") or {}).items():
        if title:
            out[cid] = title
    return out


def _str_list(v, field, key):
    if v is None:
        return []
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise CliError("TOPICS_INVALID", f"{key}.{field} must be a list of strings")
    return [" ".join(x.split()) for x in v if x.strip()]


def validate_topics(topics: dict, cfg: dict) -> tuple[dict, list[str]]:
    if not isinstance(topics, dict) or not topics:
        raise CliError("TOPICS_INVALID", 'expected {"topics": {"key": {"label": …, "channels": […], …}}}')
    known = known_channels(cfg)
    notes, clean, labels = [], {}, {}
    max_q = int(cfg["defaults"].get("max_queries", 5))
    for key, t in topics.items():
        if not TOPIC_KEY_RE.fullmatch(key or ""):
            raise CliError("TOPICS_BAD_KEY", f"{key!r}: use lowercase letters, digits and dashes (e.g. ai, news-de)")
        if not isinstance(t, dict):
            raise CliError("TOPICS_INVALID", f"{key} must be an object")
        label = " ".join(str(t.get("label") or "").split())
        if not label:
            raise CliError("TOPICS_INVALID", f"{key} needs a label")
        if label.lower() in labels:
            raise CliError("TOPICS_DUPLICATE_LABEL", f"{key} and {labels[label.lower()]} share the label {label!r}")
        labels[label.lower()] = key
        channels = list(dict.fromkeys(_str_list(t.get("channels"), "channels", key)))
        for cid in channels:
            if not yt.CHANNEL_ID_RE.fullmatch(cid):
                raise CliError("TOPICS_BAD_CHANNEL", f"{key}: {cid!r} is not a UC… channel id; add channels by name with topics add-channel")
            if cid not in known:
                raise CliError("TOPICS_UNKNOWN_CHANNEL", f"{key}: {cid} is not in your subscriptions or library; use topics add-channel {key} @handle")
        queries = _str_list(t.get("queries"), "queries", key)
        if len(queries) > max_q:
            raise CliError("TOPICS_TOO_MANY_QUERIES", f"{key} has {len(queries)} queries (max {max_q})")
        entry = {"label": label, "channels": channels, "queries": queries,
                 "keywords": _str_list(t.get("keywords"), "keywords", key),
                 "exclude_keywords": _str_list(t.get("exclude_keywords"), "exclude_keywords", key),
                 "report_tags": store.normalize_tags(_str_list(t.get("report_tags"), "report_tags", key))}
        if t.get("languages") is not None:
            entry["languages"] = _str_list(t.get("languages"), "languages", key)
        for f in ("window_days", "min_duration_min", "max_duration_min"):
            if t.get(f) is not None:
                v = t[f]
                if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 600:
                    raise CliError("TOPICS_INVALID", f"{key}.{f} must be a whole number")
                entry[f] = v
        extra = set(t) - set(store.TOPIC_FIELDS)
        if extra:
            notes.append(f"{key}: ignored unknown field(s) {', '.join(sorted(extra))}")
        clean[key] = entry
    return clean, notes


def check_labels(topics: dict) -> None:
    seen = {}
    for key, t in topics.items():
        label = (t.get("label") or key).lower()
        if label in seen:
            raise CliError("TOPICS_DUPLICATE_LABEL", f"{key} and {seen[label]} share the label {t.get('label')!r}")
        seen[label] = key


def check_channel_spread(topics: dict) -> None:
    where = {}
    for key, t in topics.items():
        for cid in t.get("channels", []):
            where.setdefault(cid, []).append(key)
    for cid, keys in where.items():
        if len(keys) > MAX_TOPICS_PER_CHANNEL:
            raise CliError("TOPICS_CHANNEL_SPREAD", f"{cid} is in {', '.join(keys)} (max {MAX_TOPICS_PER_CHANNEL} topics per channel)")


def cmd_topics_apply(args) -> int:
    try:
        data = json.loads(pathlib.Path(args.file).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CliError("TOPICS_INVALID", f"cannot read {args.file}: {e}")
    cfg = store.load_config()
    topics = data.get("topics", data) if isinstance(data, dict) else data
    if isinstance(topics, dict):
        topics = {k: v for k, v in topics.items() if k != "languages"}
    clean, notes = validate_topics(topics, cfg)
    merged = clean if args.replace_all else {**cfg["topics"], **clean}
    check_labels(merged)
    check_channel_spread(merged)
    if isinstance(data, dict) and isinstance(data.get("languages"), list):
        cfg["defaults"]["languages"] = _str_list(data["languages"], "languages", "defaults") or ["en"]
    cfg["topics"] = merged
    store.save_config(cfg)
    for n in notes:
        print(f"NOTE: {n}")
    print(f"SAVED: {len(clean)} topic(s): {', '.join(clean)} · {len(merged)} topic(s) in total")
    return cmd_topics_list(args)


def cmd_topics_list(args) -> int:
    cfg = store.load_config()
    if not cfg["topics"]:
        print("NO_TOPICS: none yet — say \"set up video recommendations\"")
        return 0
    last = {}
    for r in store.read_shown():
        if r.get("event", "shown") == "shown" and r.get("topic"):
            last[r["topic"]] = max(last.get(r["topic"], ""), r.get("at", ""))
    print("key | label | channels | queries | window | last run")
    for key, t in cfg["topics"].items():
        win = t.get("window_days") or cfg["defaults"]["window_days"]
        print(f"{key} | {t.get('label', key)} | {len(t.get('channels', []))} | "
              f"{', '.join(t.get('queries', [])) or '(channels only)'} | {win}d | {last.get(key, '')[:10] or 'never'}")
    print(f"LANGUAGES: {', '.join(cfg['defaults']['languages'])} (discovery outside subscriptions)")
    return 0


def cmd_topics_show(args) -> int:
    cfg = store.load_config()
    t = cfg["topics"].get(args.key)
    if t is None:
        raise CliError("TOPIC_UNKNOWN", f"{args.key!r}; topics: {', '.join(cfg['topics'])}")
    known = known_channels()
    print(json.dumps({args.key: t}, ensure_ascii=False, indent=2))
    for cid in t.get("channels", []):
        print(f"CHANNEL: {cid} {known.get(cid, '')}")
    return 0


def _topic(cfg, key) -> dict:
    if key not in cfg["topics"]:
        raise CliError("TOPIC_UNKNOWN", f"{key!r}; topics: {', '.join(cfg['topics']) or '(none)'}")
    return cfg["topics"][key]


def _remember_title(cfg, cid, title):
    if title:
        cfg.setdefault("channel_titles", {})[cid] = title


def cmd_topics_edit(args) -> int:
    cfg = store.load_config()
    op = args.op
    if op == "add":
        if not TOPIC_KEY_RE.fullmatch(args.key):
            raise CliError("TOPICS_BAD_KEY", f"{args.key!r}: use lowercase letters, digits and dashes")
        if args.key in cfg["topics"]:
            raise CliError("TOPIC_EXISTS", f"{args.key} already exists; edit it with add-query/add-channel")
        cfg["topics"][args.key] = {"label": args.label or args.key, "channels": [], "queries": args.query or [],
                                   "keywords": args.keyword or [], "exclude_keywords": [],
                                   "report_tags": store.normalize_tags(args.tag or [])}
        for ch in args.channel or []:
            c = resolve_channel(ch)
            _remember_title(cfg, c["id"], c["title"])
            cfg["topics"][args.key]["channels"].append(c["id"])
        validate_topics({args.key: cfg["topics"][args.key]}, cfg)
        check_labels(cfg["topics"])
        check_channel_spread(cfg["topics"])
        store.save_config(cfg)
        print(f"ADDED: topic {args.key} ({args.label or args.key})")
        return 0
    if op == "delete":
        _topic(cfg, args.key)
        del cfg["topics"][args.key]
        store.save_config(cfg)
        print(f"DELETED: topic {args.key}")
        return 0
    if op == "set":
        t = _topic(cfg, args.key)
        field, value = args.field, args.value
        if field == "label":
            t["label"] = value
        elif field in ("window_days", "min_duration_min", "max_duration_min"):
            if not value.isdigit():
                raise CliError("TOPICS_INVALID", f"{field} must be a whole number")
            t[field] = int(value)
        elif field == "languages":
            t["languages"] = [x.strip() for x in value.split(",") if x.strip()]
        else:
            raise CliError("TOPICS_INVALID", "set FIELD is one of label, window_days, min_duration_min, max_duration_min, languages")
        validate_topics({args.key: t}, cfg)
        check_labels(cfg["topics"])
        store.save_config(cfg)
        print(f"SET: {args.key}.{field} = {t[field]}")
        return 0
    if op in ("add-channel", "remove-channel"):
        t = _topic(cfg, args.key)
        for target in args.values:
            c = resolve_channel(target)
            if not c["id"]:
                raise CliError("CHANNEL_NOT_FOUND", f"{target!r} has no channel id")
            if op == "add-channel":
                if c["id"] not in t["channels"]:
                    t["channels"].append(c["id"])
                _remember_title(cfg, c["id"], c["title"])
                print(f"ADDED: {c['title'] or c['id']} → {args.key}")
            else:
                t["channels"] = [x for x in t["channels"] if x != c["id"]]
                print(f"REMOVED: {c['title'] or c['id']} from {args.key}")
        check_channel_spread(cfg["topics"])
        store.save_config(cfg)
        return 0
    if op == "move-channel":
        c = resolve_channel(args.channel)
        _topic(cfg, args.key)
        for k, t in cfg["topics"].items():
            t["channels"] = [x for x in t.get("channels", []) if x != c["id"]]
        cfg["topics"][args.key]["channels"].append(c["id"])
        _remember_title(cfg, c["id"], c["title"])
        store.save_config(cfg)
        print(f"MOVED: {c['title'] or c['id']} → {args.key}")
        return 0
    field = {"add-query": "queries", "remove-query": "queries",
             "add-keyword": "keywords", "remove-keyword": "keywords"}[op]
    t = _topic(cfg, args.key)
    vals = [" ".join(v.split()) for v in args.values if v.strip()]
    if op.startswith("add"):
        t[field] = list(dict.fromkeys([*t.get(field, []), *vals]))
        if field == "queries" and len(t[field]) > int(cfg["defaults"].get("max_queries", 5)):
            raise CliError("TOPICS_TOO_MANY_QUERIES", f"{args.key} would have {len(t[field])} queries "
                           f"(max {cfg['defaults'].get('max_queries', 5)}); remove one first")
    else:
        t[field] = [x for x in t.get(field, []) if x.lower() not in {v.lower() for v in vals}]
    store.save_config(cfg)
    print(f"{field.upper()}: {args.key} = {', '.join(t[field]) or '(none)'}")
    return 0


LANG_STOPWORDS = {
    "en": set("the and of to is that it for with on as this are be not you they".split()),
    "de": set("der die das und ist nicht ein eine zu mit den auf für sich auch von dem".split()),
    "es": set("el la los las que y en un una es por con para se del no".split()),
    "fr": set("le la les et des est un une que en pour dans pas du qui sur".split()),
}


def report_language(text: str) -> str | None:
    words = re.findall(r"[^\W\d_]+", (text or "").lower())
    if len(words) < 12:
        return None
    scores = sorted(((sum(w in sw for w in words), lang) for lang, sw in LANG_STOPWORDS.items()), reverse=True)
    return scores[0][1] if scores[0][0] >= 3 and scores[0][0] >= 1.5 * scores[1][0] else None


def cmd_topics_propose(args) -> int:
    """Evidence for the model to group channels into topics (026 §10)."""
    cfg = store.load_config()
    subs = store.load_subscriptions().get("channels", [])
    reports = store.load_reports()
    cache = yt.Cache(store.cache_dir() / "sources")
    name_to_id = collect.channel_key_maps(reports, subs)
    lib_counts = {}
    for r in reports:
        if r.get("channel"):
            lib_counts[r["channel"]] = lib_counts.get(r["channel"], 0) + 1
    implicit = [n for n, k in sorted(lib_counts.items(), key=lambda kv: -kv[1]) if k >= 2]
    collect.resolve_library_channels(reports, implicit, name_to_id, cache, limit=30)

    tags_by_channel, count_by_channel = {}, {}
    for r in reports:
        cid = collect.report_channel_id(r, name_to_id)
        if not cid:
            continue
        count_by_channel[cid] = count_by_channel.get(cid, 0) + 1
        for t in r["tags"]:
            tags_by_channel.setdefault(cid, {}).setdefault(t, 0)
            tags_by_channel[cid][t] += 1
    subs_ids = {c["id"] for c in subs}
    channels = [(c["id"], c.get("title", ""), True) for c in subs]
    channels += [(name_to_id[n.lower()], n, False) for n in implicit
                 if n.lower() in name_to_id and name_to_id[n.lower()] not in subs_ids]
    assigned = {}
    for k, t in cfg["topics"].items():
        for cid in t.get("channels", []):
            assigned.setdefault(cid, []).append(k)
    if args.refresh:
        channels = [c for c in channels if c[0] not in assigned]

    listings = yt.fetch_many(lambda c: yt.channel_listing(c, cache), [c[0] for c in channels])
    tag_counts = {}
    for r in reports:
        for t in r["tags"]:
            tag_counts[t] = tag_counts.get(t, 0) + 1
    langs = {}
    for r in reports:
        lang = report_language(r.get("summary", ""))
        if lang:
            langs[lang] = langs.get(lang, 0) + 1

    print(f"LIBRARY: {len(reports)} reports · {len(subs)} subscriptions · {len(cfg['topics'])} topics configured")
    print("LIBRARY_TAGS: " + ", ".join(f"{t} {n}" for t, n in sorted(tag_counts.items(), key=lambda kv: -kv[1])[:40]))
    print("LIBRARY_LANGUAGES: " + (", ".join(f"{l} {n}" for l, n in sorted(langs.items(), key=lambda kv: -kv[1])) or "unknown"))
    if args.refresh and cfg["topics"]:
        recent = sorted(reports, key=lambda r: r.get("generationDate", ""), reverse=True)[:40]
        covered = {t for tp in cfg["topics"].values() for t in tp.get("report_tags", [])}
        fresh = {}
        for r in recent:
            for t in r["tags"]:
                if t not in covered:
                    fresh[t] = fresh.get(t, 0) + 1
        print("UNCOVERED_RECENT_TAGS: " + (", ".join(f"{t} {n}" for t, n in sorted(fresh.items(), key=lambda kv: -kv[1])[:15]) or "none"))
        gone = [cid for cid in assigned if cid not in subs_ids and subs_ids]
        if gone:
            print(f"NO_LONGER_SUBSCRIBED: {', '.join(gone)}")
    print("CHANNELS (id | title | subscribed | reports and their top tags | recent titles):")
    for cid, title, subscribed in channels:
        lst = listings.get(cid)
        recent = "; ".join(collect.clean_cell(e["title"], 60) for e in lst["entries"][:3]) \
            if isinstance(lst, dict) else "(listing failed)"
        tags = ", ".join(t for t, _ in sorted(tags_by_channel.get(cid, {}).items(), key=lambda kv: -kv[1])[:4])
        n = count_by_channel.get(cid, 0)
        rep = f"{n} reports ({tags})" if n else "0 reports"
        where = f" | in: {', '.join(assigned[cid])}" if cid in assigned else ""
        print(f"{cid} | {collect.clean_cell(title, 40)} | {'yes' if subscribed else 'no'} | {rep} | {recent}{where}")
    proposal = store.cache_dir() / "topics-proposal.json"
    proposal.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    proposal.unlink(missing_ok=True)
    print(f"PROPOSAL_PATH: {proposal}")
    print("NEXT: group the channels into topics, Write PROPOSAL_PATH as "
          '{"languages": ["en"], "topics": {"key": {"label": "…", "channels": ["UC…"], "queries": ["…"], '
          '"keywords": ["…"], "report_tags": ["…"]}}}, confirm it with the user, then run: '
          'recs.py topics apply "PROPOSAL_PATH"')
    return 0


# ---------- account ----------

def cmd_account(args) -> int:
    cfg = store.load_config()
    acc = cfg["account"]
    op = args.op
    if op == "status":
        subs = store.load_subscriptions()
        key_env = cfg["sources"].get("api_key_env") or "YOUTUBE_API_KEY"
        print(f"MODE: {acc['mode']}" + (f" ({acc.get('browser')})" if acc["mode"] == "live" else ""))
        print(f"SUBSCRIPTIONS: {len(subs.get('channels', []))} from {subs.get('source') or 'nowhere'}"
              + (f", synced {subs.get('synced_at', '')[:16]}" if subs.get("channels") else ""))
        print(f"WATCHED_CHECK: {'recent watches (about 40 per day of the window, at most ' + str(acc.get('watched_check_depth', 600)) + '), in memory' if acc['mode'] == 'live' else 'local only (library, shown-log, your feedback)'}")
        print(f"API_KEY: {'set' if collect.api_key(cfg) else 'not set'} (${key_env})")
        print(f"TOPICS: {len(cfg['topics'])}")
        return 0
    if op == "import-takeout":
        try:
            res = takeout.import_takeout(args.path)
        except takeout.TakeoutError as e:
            raise CliError(e.code, e.detail)
        store.save_subscriptions(res["channels"], "takeout", res["export_date"])
        if acc["mode"] == "none":
            acc["mode"] = "takeout"
        store.save_config(cfg)
        print(f"IMPORTED: {len(res['channels'])} subscriptions from {res['source_file']}"
              + (f" (export of {res['export_date']})" if res["export_date"] else ""))
        for name in res["ignored"]:
            print(f"IGNORED: {name} — watch and search history are never imported")
        print(f"MODE: {acc['mode']}")
        return 0
    if op == "live":
        prev = dict(acc)
        acc["mode"] = "live"
        acc["browser"] = args.browser or acc.get("browser") or "firefox"
        warns = []
        n = collect.sync_subscriptions(cfg, warns, force=True)
        if n is None:
            cfg["account"] = prev
            store.save_config(cfg)
            raise CliError("LIVE_SYNC_FAILED", "; ".join(warns) + f" — live mode not enabled (mode stays {prev['mode']})")
        print(f"MODE: live ({acc['browser']})")
        print(f"SYNCED: {n} subscriptions. Watch history is not imported: each run checks only its candidates "
              f"against your recent watches (at most {acc.get('watched_check_depth', 600)}), in memory, and records "
              "\"watched\" only for videos it showed you.")
        return 0
    if op == "off":
        acc["mode"] = "takeout" if store.load_subscriptions().get("channels") else "none"
        store.save_config(cfg)
        print(f"MODE: {acc['mode']} (no more cookie requests)")
        return 0
    if op == "sync":
        if acc["mode"] != "live":
            raise CliError("NOT_LIVE", "sync needs live mode; enable it with: recs.py account live --browser firefox")
        warns = []
        n = collect.sync_subscriptions(cfg, warns, force=args.force)
        if n is None and warns:
            raise CliError("LIVE_SYNC_FAILED", "; ".join(warns))
        for w in warns:
            print(f"WARN: {w}")
        print(f"SYNCED: {n} subscriptions" if n is not None else "SYNC_SKIPPED: synced less than 24 h ago (use --force)")
        return 0
    if op == "probe":
        return account_probe(args.browser or acc.get("browser") or "firefox", int(acc.get("watched_check_depth") or 600))
    raise CliError("BAD_COMMAND", op)


def account_probe(browser: str, depth: int) -> int:
    """The three P0 checks of 026 §5.6, printing counts and field names only — never IDs or titles."""
    print(f"PROBE: browser {browser}, depth {depth} (prints counts and field names only)")
    try:
        subs = yt.subscriptions_live(browser)
        print(f"SUBSCRIPTIONS: ok, {len(subs)} channels; with subscriber counts: {sum(1 for c in subs if c.get('subscribers'))}")
    except SourceError as e:
        print(f"SUBSCRIPTIONS: failed {e.code} — {collect._hint(e.code)}")
    try:
        ids = yt.recent_watch_ids(browser, depth)
        print(f"(a) HISTORY_DEPTH: asked {depth}, got {len(ids)} ids "
              f"({'paginates past the first page' if len(ids) > 200 else 'check: may stop at the first page' if ids else 'empty'})")
        print(f"(b) HISTORY_IDS: {len(ids)} valid video ids, {len(set(ids))} unique")
        del ids
    except SourceError as e:
        print(f"(a)(b) HISTORY: failed {e.code} — {collect._hint(e.code)}")
    try:
        raw = yt._ytdlp(["--flat-playlist", "-J", "--playlist-end", "20", ":ythistory"], "personal:history-probe",
                        browser=browser)
        entries = raw.get("entries") or []
        fields = sorted({k for e in entries for k, v in e.items() if v not in (None, "", [])})
        dated = sum(1 for e in entries if e.get("timestamp") or e.get("upload_date") or e.get("release_timestamp"))
        print(f"(c) HISTORY_FIELDS: {', '.join(fields)}")
        print(f"(c) HISTORY_DATES: {dated}/{len(entries)} entries carry a date field "
              "(note: a date may be the upload date, not the watch date)")
        del raw, entries
    except SourceError as e:
        print(f"(c) HISTORY_FIELDS: failed {e.code}")
    try:
        home = yt.home_feed(browser, limit=30)
        have = {k: sum(1 for e in home if e.get(k) not in (None, "")) for k in ("duration", "views", "channelId", "published")}
        print(f"HOME_FEED: ok, {len(home)} entries; " + ", ".join(f"{k} {v}/{len(home)}" for k, v in have.items()))
    except SourceError as e:
        print(f"HOME_FEED: failed {e.code}")
    return 0


# ---------- stats ----------

def cmd_stats(args) -> int:
    shown = store.fold_shown(store.read_shown())
    reports = {r["videoId"]: r.get("generationDate", "") for r in store.load_reports()}
    rows = {}
    for vid, st in shown.items():
        snap = st["snapshot"]
        if not snap:
            continue
        summarised = vid in reports and reports[vid] >= (st["first"] or "")[:10]
        for dim in (("topic", snap.get("topic")), ("section", snap.get("section")), ("source", snap.get("source"))):
            r = rows.setdefault(dim, {"shown": 0, "summarised": 0, "watched": 0, "dismissed": 0})
            r["shown"] += 1
            r["summarised"] += summarised
            r["watched"] += "watched" in st["outcomes"]
            r["dismissed"] += "dismissed" in st["outcomes"]
    if not rows:
        print("NO_STATS: nothing shown yet")
        return 0
    print("by | value | shown | summarised | watched | dismissed | acted on")
    for (dim, val), r in sorted(rows.items(), key=lambda kv: (kv[0][0], -kv[1]["shown"])):
        acted = (r["summarised"] + r["watched"]) / r["shown"] if r["shown"] else 0
        print(f"{dim} | {val} | {r['shown']} | {r['summarised']} | {r['watched']} | {r['dismissed']} | {acted:.0%}")
    print("TARGETS: about 1 in 3 for Top picks, at least 1 in 6 for Beyond (026 §12.4)")
    return 0


# ---------- main ----------

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="recs.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("recommend", cmd_recommend), ("preflight", cmd_preflight)):
        p = sub.add_parser(name)
        p.add_argument("--topic")
        p.add_argument("request", nargs="*")
        p.set_defaults(fn=fn)
    p = sub.add_parser("collect")
    p.add_argument("run_dir")
    p.set_defaults(fn=cmd_collect)
    p = sub.add_parser("render")
    p.add_argument("run_dir")
    p.add_argument("--no-serve", action="store_true")
    p.set_defaults(fn=cmd_render)
    p = sub.add_parser("next")
    p.add_argument("run_dir", nargs="?")
    p.add_argument("--no-serve", action="store_true")
    p.set_defaults(fn=cmd_next)
    p = sub.add_parser("resolve")
    p.add_argument("spec", nargs="+")
    p.set_defaults(fn=cmd_resolve)
    p = sub.add_parser("feedback")
    p.add_argument("action", choices=("dismiss", "watched", "mute", "unmute", "boost", "unboost"))
    p.add_argument("target", nargs="+")
    p.add_argument("--run")
    p.add_argument("--topic")
    p.set_defaults(fn=cmd_feedback)

    tp = sub.add_parser("topics").add_subparsers(dest="op", required=True)
    tp.add_parser("list").set_defaults(fn=cmd_topics_list)
    p = tp.add_parser("show")
    p.add_argument("key")
    p.set_defaults(fn=cmd_topics_show)
    p = tp.add_parser("propose")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(fn=cmd_topics_propose)
    p = tp.add_parser("apply")
    p.add_argument("file")
    p.add_argument("--replace-all", action="store_true")
    p.set_defaults(fn=cmd_topics_apply)
    p = tp.add_parser("add")
    p.add_argument("key")
    p.add_argument("--label")
    p.add_argument("--query", action="append")
    p.add_argument("--keyword", action="append")
    p.add_argument("--tag", action="append")
    p.add_argument("--channel", action="append")
    p.set_defaults(fn=cmd_topics_edit)
    p = tp.add_parser("delete")
    p.add_argument("key")
    p.set_defaults(fn=cmd_topics_edit)
    p = tp.add_parser("set")
    p.add_argument("key")
    p.add_argument("field")
    p.add_argument("value")
    p.set_defaults(fn=cmd_topics_edit)
    for op in ("add-channel", "remove-channel", "add-query", "remove-query", "add-keyword", "remove-keyword"):
        p = tp.add_parser(op)
        p.add_argument("key")
        p.add_argument("values", nargs="+")
        p.set_defaults(fn=cmd_topics_edit)
    p = tp.add_parser("move-channel")
    p.add_argument("channel")
    p.add_argument("key")
    p.set_defaults(fn=cmd_topics_edit)

    ac = sub.add_parser("account").add_subparsers(dest="op", required=True)
    ac.add_parser("status").set_defaults(fn=cmd_account)
    p = ac.add_parser("import-takeout")
    p.add_argument("path")
    p.set_defaults(fn=cmd_account)
    p = ac.add_parser("live")
    p.add_argument("--browser")
    p.set_defaults(fn=cmd_account)
    ac.add_parser("off").set_defaults(fn=cmd_account)
    p = ac.add_parser("sync")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_account)
    p = ac.add_parser("probe")
    p.add_argument("--browser")
    p.set_defaults(fn=cmd_account)

    sub.add_parser("stats").set_defaults(fn=cmd_stats)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "request", None) and args.request[:1] == ["--"]:
        args.request = args.request[1:]
    try:
        return args.fn(args)
    except CliError as e:
        print(f"ERROR:{e.code} {e.detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
