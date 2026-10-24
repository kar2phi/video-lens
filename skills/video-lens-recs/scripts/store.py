"""Config and state for video-lens-recs (026 §8.3).

Everything personal lives outside ~/Downloads/video-lens, because serve_report.sh serves
that whole tree on loopback:

    $XDG_CONFIG_HOME/video-lens/recs.json            topics, defaults, account mode
    $XDG_DATA_HOME/video-lens/recs/subscriptions.json
    $XDG_DATA_HOME/video-lens/recs/shown.jsonl       what the skill showed, and outcomes
    $XDG_DATA_HOME/video-lens/recs/feedback.json     dismissed ids, muted channels, boosts
    $XDG_CACHE_HOME/video-lens/recs/                 source cache, run directories

Paths are resolved on every call, so tests can point HOME / XDG_* at a temp dir.
There is no watch-history file, by design (026 §5.6).
"""
import copy
import datetime
import json
import os
import pathlib
import tempfile

DEFAULT_CONFIG = {
    "version": 2,
    "account": {"mode": "none", "browser": "firefox", "subscriptions_synced": "",
                "watched_check_depth": 600},
    "sources": {"search": True, "api_key_env": "YOUTUBE_API_KEY", "home_feed": True},
    "ui": {"raycast_summarize": "auto"},
    "defaults": {"window_days": 14, "picks": 12, "min_duration_min": 4, "max_duration_min": None,
                 "per_channel_cap": 2, "languages": ["en"], "shortlist": 40, "max_queries": 5},
    "topics": {},
}
# Version 1 files hold every default, as written then; values equal to these were not chosen.
V1_DEFAULTS = {**DEFAULT_CONFIG, "defaults": {**DEFAULT_CONFIG["defaults"], "picks": 8}}
TOPIC_FIELDS = ("label", "channels", "queries", "keywords", "exclude_keywords", "report_tags",
                "languages", "window_days", "min_duration_min", "max_duration_min")


def _xdg(var: str, default: str) -> pathlib.Path:
    return pathlib.Path(os.environ.get(var) or (pathlib.Path.home() / default))


def config_path() -> pathlib.Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "video-lens" / "recs.json"


def data_dir() -> pathlib.Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "video-lens" / "recs"


def cache_dir() -> pathlib.Path:
    return _xdg("XDG_CACHE_HOME", ".cache") / "video-lens" / "recs"


def runs_dir() -> pathlib.Path:
    return cache_dir() / "runs"


def library_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("VIDEO_LENS_LIBRARY") or (pathlib.Path.home() / "Downloads" / "video-lens"))


def pages_dir() -> pathlib.Path:
    return library_dir() / "recs"


# ---------- io ----------

def read_json(path: pathlib.Path, default=None):
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(default)


def write_json(path: pathlib.Path, data, private: bool = True) -> None:
    """Atomic write; private files are 0600 in a 0700 directory."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700 if private else 0o755)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o600 if private else 0o644)
        os.replace(tmp, path)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict) and k != "topics":
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


# ---------- config ----------

def config_exists() -> bool:
    return config_path().exists()


def _strip_defaults(cfg: dict, base: dict) -> dict:
    """cfg minus the values equal to base, so a saved file holds only choices and state and
    later default changes reach it. Topics and the version are always kept."""
    out = {}
    for k, v in cfg.items():
        if k in ("topics", "version") or k not in base:
            out[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(base[k], dict):
            sub = _strip_defaults(v, base[k])
            if sub:
                out[k] = sub
        elif v != base[k]:
            out[k] = copy.deepcopy(v)
    return out


def load_config() -> dict:
    raw = read_json(config_path(), {}) or {}
    if raw.get("version", 1) < 2:
        raw = {**_strip_defaults(raw, V1_DEFAULTS), "version": 2}
    return _merge(DEFAULT_CONFIG, raw)


def save_config(cfg: dict) -> None:
    write_json(config_path(), _strip_defaults(cfg, DEFAULT_CONFIG))


def topic_settings(cfg: dict, topic: dict) -> dict:
    """A topic's effective settings: its own values over the defaults."""
    d = cfg["defaults"]
    return {
        "window_days": int(topic.get("window_days") or d["window_days"]),
        "min_duration_s": int(60 * (topic.get("min_duration_min") if topic.get("min_duration_min") is not None
                                    else d["min_duration_min"] or 0)),
        "max_duration_s": int(60 * m) if (m := topic.get("max_duration_min", d.get("max_duration_min"))) else None,
        "languages": topic.get("languages") or d["languages"],
        "picks": int(d["picks"]),
        "per_channel_cap": int(d["per_channel_cap"]),
        "shortlist": int(d.get("shortlist", 40)),
        "max_queries": int(d.get("max_queries", 5)),
    }


# ---------- subscriptions ----------

def subscriptions_path() -> pathlib.Path:
    return data_dir() / "subscriptions.json"


def load_subscriptions() -> dict:
    return read_json(subscriptions_path(), {"channels": []}) or {"channels": []}


def save_subscriptions(channels, source: str, export_date: str = "") -> dict:
    data = {"version": 1, "source": source,
            "synced_at": datetime.datetime.now().isoformat(timespec="seconds"),
            "export_date": export_date, "channels": channels}
    write_json(subscriptions_path(), data)
    return data


# ---------- shown-log ----------

def shown_path() -> pathlib.Path:
    return data_dir() / "shown.jsonl"


def append_shown(records) -> None:
    records = list(records)
    if not records:
        return
    p = shown_path()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    new = not p.exists()
    with open(p, "a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    if new:
        os.chmod(p, 0o600)


def read_shown() -> list[dict]:
    out = []
    try:
        lines = shown_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("videoId"):
            out.append(rec)
    return out


def fold_shown(records) -> dict:
    """videoId → {count, first, last, outcomes, snapshot, topics} from shown-log events."""
    out: dict = {}
    for r in records:
        st = out.setdefault(r["videoId"], {"count": 0, "first": "", "last": "", "outcomes": set(),
                                           "snapshot": None, "topics": set()})
        if r.get("event", "shown") == "shown":
            st["count"] += 1
            at = r.get("at", "")
            st["first"] = min(st["first"] or at, at)
            st["last"] = max(st["last"], at)
            st["snapshot"] = r
            if r.get("topic"):
                st["topics"].add(r["topic"])
        if r.get("outcome"):
            st["outcomes"].add(r["outcome"])
    return out


# ---------- feedback ----------

def feedback_path() -> pathlib.Path:
    return data_dir() / "feedback.json"


def load_feedback() -> dict:
    fb = read_json(feedback_path(), {}) or {}
    fb.setdefault("dismissed", [])
    fb.setdefault("muted_channels", [])
    fb.setdefault("boosts", [])
    return fb


def save_feedback(fb: dict) -> None:
    write_json(feedback_path(), fb)


# ---------- library (video-lens manifest) ----------

def normalize_tags(tags) -> list[str]:
    """Same fold as video-lens's build_index._normalize_tags."""
    seen, out = set(), []
    for tag in tags or []:
        if not isinstance(tag, str):
            continue
        norm = " ".join(tag.replace("-", " ").lower().split())
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def load_reports() -> list[dict]:
    """One entry per video (the newest report): re-runs with another model are model
    comparisons, not extra interest in the channel."""
    data = read_json(library_dir() / "manifest.json", {}) or {}
    reports = data.get("reports") if isinstance(data, dict) else None
    by_video: dict = {}
    for r in reports or []:
        if isinstance(r, dict) and r.get("videoId"):
            r = dict(r)
            r["tags"] = normalize_tags(r.get("tags"))
            old = by_video.get(r["videoId"])
            if old is None or (r.get("generationDate") or "") > (old.get("generationDate") or ""):
                if old and not r.get("channelId"):
                    r["channelId"] = old.get("channelId", "")
                by_video[r["videoId"]] = r
    return list(by_video.values())


# ---------- name → channel id cache (for library channels without a channelId) ----------

def channel_ids_path() -> pathlib.Path:
    return cache_dir() / "channel_ids.json"


def load_channel_ids() -> dict:
    return read_json(channel_ids_path(), {}) or {}


def save_channel_ids(mapping: dict) -> None:
    write_json(channel_ids_path(), mapping)
