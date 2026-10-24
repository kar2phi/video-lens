"""Render for video-lens-recs: validate picks.json, rank, page, assign sections, write the
Discover page and the chat list (026 §6.2, §6.4, §7.4).

The model's whole output is picks.json: a flat array with one {n, relevance, reason?,
same_story_as?} per table row. Rows rated 3 or 2 are ranked and split into pages; "next"
shows the following page from the same run, without fetching again. Everything a user reads
as a number or a link comes from candidates.json, so it cannot be hallucinated. Errors are
one line each and name the fix.
"""
import datetime
import html
import json
import math
import os
import pathlib
import re
import subprocess
import urllib.parse

import collect
import scoring
import store

REASON_MAX = 160
TOP_MAX = 3
SECTION_TITLES = {
    "top": "Top picks",
    "own": "From your channels",
    "beyond": "Beyond your subscriptions",
    "waiting": "Still waiting from last time",
}
AGENT_DIRS = ("agents", "claude", "copilot", "gemini", "cursor", "windsurf", "opencode", "codex")


class PicksError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


# ---------- picks ----------

def load_picks(run_dir: pathlib.Path) -> list:
    path = pathlib.Path(run_dir) / "picks.json"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        raise PicksError("PICKS_MISSING", f"write {path} first: a JSON array of {{n, relevance, reason}}")
    try:
        data = json.loads(raw)
    except ValueError as e:
        raise PicksError("PICKS_INVALID_JSON", f"{e}. Re-write the whole file as a JSON array")
    if isinstance(data, dict) and isinstance(data.get("picks"), list):
        data = data["picks"]
    if not isinstance(data, list) or not data:
        raise PicksError("PICKS_SHAPE", "expected a non-empty JSON array of {\"n\", \"relevance\", \"reason\"} objects")
    return data


def _as_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("n#").isdigit():
        return int(v.strip().lstrip("n#"))
    return None


def validate_picks(picks: list, cands_by_n: dict) -> tuple[list, list]:
    """Check identity fields strictly (they must be fixed by the model) and soft fields
    leniently (trimmed with a NOTE). Returns (clean picks, notes)."""
    lo, hi = (min(cands_by_n), max(cands_by_n)) if cands_by_n else (0, 0)
    clean, notes, seen = [], [], set()
    for i, p in enumerate(picks, 1):
        if not isinstance(p, dict):
            raise PicksError("PICKS_SHAPE", f"item {i} is not an object; each row is {{\"n\", \"relevance\", \"reason\"}}")
        n = _as_int(p.get("n"))
        if n is None:
            raise PicksError("PICKS_SHAPE", f"item {i} has no integer \"n\"")
        if n not in cands_by_n:
            raise PicksError("PICKS_UNKNOWN_N", f"{n} (table has {lo}–{hi})")
        if n in seen:
            raise PicksError("PICKS_DUPLICATE_N", f"{n} is rated twice; keep one")
        seen.add(n)
        rel = _as_int(p.get("relevance"))
        if rel not in (0, 1, 2, 3):
            raise PicksError("PICKS_BAD_RELEVANCE", f"n={n} got {p.get('relevance')!r} (use 3, 2, 1 or 0)")
        reason = " ".join(str(p.get("reason") or "").split()) if rel else ""
        if rel >= 2 and not reason:
            raise PicksError("PICKS_REASON_EMPTY", f"n={n} is rated {rel} and needs a one-line reason: "
                                                   "what the video adds for this user")
        title = cands_by_n[n]["title"]
        if reason and scoring.jaccard(scoring.tokens(reason), scoring.tokens(title)) >= 0.8:
            raise PicksError("PICKS_REASON_IS_TITLE", f"n={n}: the reason repeats the title; say what the video adds")
        if len(reason) > REASON_MAX:
            cut = reason[:REASON_MAX - 1].rsplit(" ", 1)[0].rstrip(",;:—-")
            notes.append(f"reason for n={n} trimmed to {REASON_MAX} chars")
            reason = cut + "…"
        same = _as_int(p.get("same_story_as"))
        if same is not None and (same not in cands_by_n or same == n):
            same = None
        clean.append({"n": n, "relevance": rel, "reason": reason, "same_story_as": same})
    return clean, notes


def order_picks(clean: list, cands_by_n: dict) -> tuple[list, set, list]:
    """Rank by relevance, then prior, and merge same-story rows into the better one.
    Returns (showable picks in order, merged-away numbers, notes). A 3 or a 2 is showable,
    and so is a 1 that carries a reason (a picks.json written before every row was rated)."""
    notes = []
    order = sorted((p for p in clean if p["relevance"] >= 1),
                   key=lambda p: (-p["relevance"], -(cands_by_n[p["n"]].get("prior") or 0)))
    pos = {p["n"]: i for i, p in enumerate(order)}
    also: dict = {}
    dropped = set()
    for p in order:
        m = p["same_story_as"]
        if m is None:
            continue
        if m in pos and m not in dropped and p["n"] not in dropped:
            keep, lose = (p["n"], m) if pos[p["n"]] < pos[m] else (m, p["n"])
            dropped.add(lose)
            also.setdefault(keep, []).append(cands_by_n[lose]["channel"])
            notes.append(f"n={lose} merged into n={keep} (same story)")
        elif m not in pos and p["n"] not in dropped:
            also.setdefault(p["n"], []).append(cands_by_n[m]["channel"])
    showable = [{**p, "also": also.get(p["n"], [])} for p in order
                if p["n"] not in dropped and (p["relevance"] >= 2 or p["reason"])]
    return showable, dropped, notes


def paginate(order: list, cands_by_n: dict, size: int, per_channel: int, by_topic: bool = False) -> list:
    """Split ranked picks into pages of `size`, at most `per_channel` per channel on a page.
    With `by_topic` each topic first gets its fair share of a page; the rest of the page goes
    to the best remaining picks. A pick that does not fit moves to a later page."""
    topics = {cands_by_n[p["n"]].get("topic") for p in order}
    per_topic = max(2, math.ceil(size / len(topics))) if by_topic and len(topics) > 1 else None
    rank = {p["n"]: i for i, p in enumerate(order)}
    pages, rest = [], list(order)
    while rest:
        page, taken, chans, tops = [], set(), {}, {}
        for strict in ((True, False) if per_topic else (False,)):
            for p in rest:
                if len(page) >= size:
                    break
                c = cands_by_n[p["n"]]
                ch, tp = c.get("channelId") or c.get("channel"), c.get("topic")
                if p["n"] in taken or chans.get(ch, 0) >= per_channel:
                    continue
                if strict and tops.get(tp, 0) >= per_topic:
                    continue
                page.append(p)
                taken.add(p["n"])
                chans[ch] = chans.get(ch, 0) + 1
                tops[tp] = tops.get(tp, 0) + 1
        pages.append(sorted(page, key=lambda p: rank[p["n"]]))
        rest = [p for p in rest if p["n"] not in taken]
    return pages


def assign_sections(page: list, cands_by_n: dict, page_no: int, topics: dict) -> list:
    """Page 1 opens with up to 3 Top picks. Then, per topic in an all-topics run, or own
    channels before the rest."""
    tops = 0
    for p in page:
        c = cands_by_n[p["n"]]
        if page_no == 1 and p["relevance"] == 3 and tops < TOP_MAX:
            p["section"] = "top"
            tops += 1
        elif topics:
            p["section"] = "topic:" + (c.get("topic") or "")
        elif scoring.source_group(c) == "own":
            p["section"] = "own"
        else:
            p["section"] = "beyond"
    first: dict = {}
    for i, p in enumerate(page):
        first.setdefault(p["section"], i)
    fixed = {"top": -3, "own": -2, "beyond": -1}
    return sorted(page, key=lambda p: fixed.get(p["section"], first[p["section"]]))


def section_title(key: str, page_no: int, topics: dict) -> str:
    title = topics.get(key[6:], key[6:] or "Other") if key.startswith("topic:") else SECTION_TITLES[key]
    return title if page_no == 1 or key == "waiting" else f"More · {title}"


# ---------- chips ----------

def _ago(days) -> str:
    if days is None:
        return ""
    if days < 1:
        return f"{max(1, round(days * 24))} h ago"
    d = round(days)
    return "1 day ago" if d == 1 else f"{d} days ago"


def _minutes(seconds) -> str:
    if not seconds:
        return ""
    h, rem = divmod(int(seconds), 3600)
    return f"{h}h {rem // 60:02d}m" if h else f"{max(1, round(rem / 60))} min"


def _short_date(iso: str) -> str:
    try:
        d = datetime.datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return ""
    return f"{d:%b} {d.day}"


def chips(c: dict, also=(), waiting_at: str = "") -> list[tuple[str, str]]:
    """(kind, text) chips for one item, from candidates.json numbers only."""
    out = []
    if c.get("perf") is not None and c["perf"] >= 1.5:
        out.append(("perf", f"≈{collect.fmt_perf(c['perf'])} usual"))
    if c.get("views") is not None:
        out.append(("views", f"{collect.fmt_count(c['views'])} views"))
    if c.get("reports"):
        n = c["reports"]
        out.append(("affinity", f"you summarised {n} from this channel"))
    elif not c.get("subscribed"):
        subs = c.get("subscribers")
        out.append(("new", "new channel" + (f" · {collect.fmt_count(subs)} subs" if subs else "")))
    if c.get("source") == "search" and c.get("query"):
        out.append(("source", f"found via search \"{c['query']}\""))
    elif c.get("source") == "home":
        out.append(("source", "from your home feed"))
    if also:
        names = list(dict.fromkeys(also))
        out.append(("story", f"also covered by {names[0]}" if len(names) == 1
                    else f"also covered by {len(names)} channels"))
    if c.get("similar_report"):
        out.append(("story", "similar to a report you have"))
    if waiting_at:
        out.append(("waiting", f"shown {_short_date(waiting_at)}, not watched"))
    return out


# ---------- output ----------

def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def build_items(pages: list, cands_by_n: dict, waiting: list) -> list[dict]:
    """Numbered items for every page shown so far; numbers run on across pages."""
    items = []
    for page_no, page in enumerate(pages, 1):
        for p in page:
            c = cands_by_n[p["n"]]
            items.append({"num": len(items) + 1, "page": page_no, "section": p["section"], "n": p["n"],
                          "relevance": p["relevance"], "reason": p["reason"], "candidate": c,
                          "chips": chips(c, p["also"])})
        if page_no == 1:
            for w in waiting:
                c = {**w, "age_days": None, "subscribed": True, "source": "waiting"}
                items.append({"num": len(items) + 1, "page": 1, "section": "waiting", "n": None, "relevance": None,
                              "reason": w.get("reason") or "", "candidate": c,
                              "chips": chips({"views": None}, waiting_at=w.get("at", ""))})
    return items


def also_rows(clean: list, cands_by_n: dict, shown_ns: set, dropped: set) -> list[dict]:
    """Table rows not shown yet and not rated 0: queued picks first, then 1s, then rows the
    model did not rate. The Discover page lists them, collapsed, at no extra model cost."""
    judged = {p["n"]: p for p in clean}
    rows = []
    for n, c in cands_by_n.items():
        p = judged.get(n)
        if n in shown_ns or n in dropped or (p and p["relevance"] == 0):
            continue
        rows.append({"n": n, "relevance": p["relevance"] if p else None, "reason": p["reason"] if p else "",
                     "candidate": c})
    return sorted(rows, key=lambda r: (-(r["relevance"] or 0), -(r["candidate"].get("prior") or 0)))


def header_lines(data: dict) -> list[str]:
    c = data["counts"]
    src = [collect.plural(c["channels"], "channel") + " scanned"]
    if c["searches"]:
        src.append(collect.plural(c["searches"], "search", "searches"))
    if c["home"]:
        src.append("home feed")
    ex = data["excluded"]
    excl = [f"{n} {k}" for k, n in sorted(ex.items(), key=lambda kv: -kv[1]) if k != collect.OUT_OF_WINDOW]
    watched = f" (last {data['watched_checked']} watches checked)" if data.get("watched_checked") is not None else ""
    in_window = c["candidates"] - ex.get(collect.OUT_OF_WINDOW, 0)
    return [f"{data['label']} · last {data['window_days']} days · " + " + ".join(src),
            f"{in_window} candidates → {c['shortlisted']} judged → {data['_picked']} picks"
            + (f" · excluded {', '.join(excl)}" if excl else "") + watched]


def chat_facts(c: dict, item_chips) -> list[str]:
    """'18 min · 176K views (≈15× usual) · 3 days ago · <other chips>' (026 §6.2)."""
    kinds = dict(item_chips)
    facts = [_minutes(c.get("duration"))]
    if "views" in kinds:
        facts.append(kinds["views"] + (f" ({kinds['perf']})" if "perf" in kinds else ""))
    facts.append(_ago(c.get("age_days")))
    facts += [t for k, t in item_chips if k not in ("views", "perf", "new")]
    return [f for f in facts if f]


def _who(c: dict, section: str) -> str:
    who = c.get("channel") or "?"
    if section != "waiting" and scoring.source_group(c) != "own":
        subs = c.get("subscribers")
        who += " (not subscribed" + (f" · {collect.fmt_count(subs)} subs)" if subs else ")")
    return who


def chat_list(data: dict, items: list, page_no: int, page_url: str, left: int, also_n: int) -> str:
    """The newest page of picks, as relayed in chat."""
    topics = data.get("topics") or {}
    if page_no == 1:
        lines = header_lines(data)
    else:
        lines = [f"{data['label']} · more picks, page {page_no} · {data['_picked']} picks in this run"]
    section = None
    for it in (it for it in items if it["page"] == page_no):
        c = it["candidate"]
        if it["section"] != section:
            section = it["section"]
            lines += ["", section_title(section, page_no, topics).upper()]
        lines.append(f"{it['num']}. {c['title']} — {_who(c, section)}")
        lines.append("   " + " · ".join(chat_facts(c, it["chips"])))
        if it["reason"]:
            lines.append(f"   Why: {it['reason']}")
    lines.append("")
    if left:
        lines.append(f'{left} more picks ready: say "next".')
    if page_url:
        lines.append(f"Discover page: {page_url}" + (f" (lists {also_n} more candidates)" if also_n else ""))
    lines.append('Reply "summarize 1, 4" · "not interested in 3" · "I watched 5" · "mute <channel>" · '
                 '"more like 2" · "next"')
    return "\n".join(lines)


def raycast_enabled(cfg: dict) -> bool:
    setting = cfg["ui"].get("raycast_summarize", "auto")
    if setting == "auto":
        return (pathlib.Path.home() / ".raycast" / "scripts" / "video-lens.sh").exists()
    return bool(setting)


def find_template() -> pathlib.Path:
    local = pathlib.Path(__file__).resolve().parent.parent / "template.html"
    if local.exists():
        return local
    for agent in AGENT_DIRS:
        p = pathlib.Path.home() / f".{agent}" / "skills" / "video-lens-recs" / "template.html"
        if p.exists():
            return p
    raise FileNotFoundError("template.html not found — reinstall video-lens-recs")


def _e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def summarize_button(url: str, raycast: bool, cls: str = "btn btn-primary") -> str:
    if raycast:
        return (f'<a class="{cls}" href="raycast://script-commands/video-lens?arguments='
                f'{_e(urllib.parse.quote(url, safe=""))}">⚡ Summarize</a>')
    return (f'<button class="{cls}" type="button" data-copy="{_e("/video-lens " + url)}" '
            f'title="Copies the video-lens command; paste it into your agent">⚡ Summarize</button>')


def item_html(it: dict, raycast: bool) -> str:
    c = it["candidate"]
    vid = c["videoId"]
    url = video_url(vid)
    chip_html = "".join(f'<span class="chip chip-{_e(k)}">{_e(t)}</span>' for k, t in it["chips"])
    meta = [c.get("channel") or ""]
    if c.get("duration"):
        meta.append(_minutes(c["duration"]))
    if c.get("age_days") is not None:
        meta.append(_ago(c["age_days"]))
    meta_html = " · ".join(_e(m) for m in meta if m)
    dur = f'<span class="dur">{_e(_clock(c["duration"]))}</span>' if c.get("duration") else ""
    return (
        f'<article class="pick" id="pick-{it["num"]}" data-video="{_e(vid)}">'
        f'<a class="thumb" href="{_e(url)}" target="_blank" rel="noopener noreferrer">'
        f'<img src="https://i.ytimg.com/vi/{_e(vid)}/mqdefault.jpg" alt="" loading="lazy" decoding="async">{dur}</a>'
        f'<div class="pick-body">'
        f'<h3><span class="num">{it["num"]}</span><a href="{_e(url)}" target="_blank" rel="noopener noreferrer">{_e(c["title"])}</a></h3>'
        f'<p class="pick-meta">{meta_html}</p>'
        f'<div class="chips">{chip_html}</div>'
        + (f'<p class="reason">{_e(it["reason"])}</p>' if it["reason"] else "")
        + f'<div class="actions"><a class="btn" href="{_e(url)}" target="_blank" rel="noopener noreferrer">▶ Watch</a>'
        f'{summarize_button(url, raycast)}<button class="btn" type="button" data-copy="{_e(url)}">⧉ Copy link</button></div>'
        f'</div></article>'
    )


def also_html(rows: list, raycast: bool) -> str:
    lis = []
    for r in rows:
        c = r["candidate"]
        url = video_url(c["videoId"])
        meta = [_who(c, "also"), _minutes(c.get("duration")), _ago(c.get("age_days"))]
        if c.get("views") is not None:
            meta.append(f"{collect.fmt_count(c['views'])} views")
        lis.append(
            f'<li><div class="also-main"><a href="{_e(url)}" target="_blank" rel="noopener noreferrer">{_e(c["title"])}</a>'
            f'<span class="also-meta">{" · ".join(_e(m) for m in meta if m)}</span>'
            + (f'<span class="also-reason">{_e(r["reason"])}</span>' if r["reason"] else "")
            + f'</div>{summarize_button(url, raycast, "btn btn-small")}</li>')
    return ('<section id="sec-also"><details class="also"><summary>Also in the window '
            f'<span>{len(rows)}</span></summary><ol>{"".join(lis)}</ol></details></section>')


def _clock(seconds) -> str:
    if not seconds:
        return ""
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def page_html(data: dict, items: list, also: list, cfg: dict, date: str) -> str:
    raycast = raycast_enabled(cfg)
    topics = data.get("topics") or {}
    blocks: list = []
    for it in items:
        key = (it["page"], it["section"])
        if not blocks or blocks[-1][0] != key:
            blocks.append((key, []))
        blocks[-1][1].append(it)
    sections, nav = [], []
    for i, ((page_no, section), its) in enumerate(blocks):
        title = section_title(section, page_no, topics)
        nav.append(f'<a class="nav-pill" href="#sec-{i}">{_e(title)} <span>{len(its)}</span></a>')
        sections.append(f'<section id="sec-{i}"><h2>{_e(title)}</h2>'
                        + "".join(item_html(it, raycast) for it in its) + "</section>")
    if not sections:
        sections.append('<section><p class="empty">No picks this time.</p></section>')
    if also:
        nav.append(f'<a class="nav-pill" href="#sec-also">Also in the window <span>{len(also)}</span></a>')
        sections.append(also_html(also, raycast))
    head = header_lines(data)
    meta = {"run": data["run"], "topic": data["topic"], "label": data["label"], "date": date,
            "windowDays": data["window_days"], "picks": sum(it["section"] != "waiting" for it in items),
            "videoIds": [it["candidate"]["videoId"] for it in items]}
    values = {
        "PAGE_TITLE": _e(f"Discover — {data['label']} · {date}"),
        "TOPIC_LABEL": _e(data["label"]),
        "SUBTITLE": _e(f"last {data['window_days']} days · {date}"),
        "NAV": "".join(nav),
        "SECTIONS": "".join(sections),
        "FOOTER": " │ ".join(_e(h) for h in head),
        "RECS_META": json.dumps(meta, ensure_ascii=True).replace("</", "<\\/"),
    }
    tpl = find_template().read_text(encoding="utf-8")
    missing = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", tpl)) - set(values))
    if missing:
        raise ValueError(f"RENDER_UNREPLACED_PLACEHOLDERS {missing}")
    return re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: values[m.group(1)], tpl)


# ---------- page path, index, serve ----------

def page_path(run_dir: pathlib.Path, topic: str, date: str) -> pathlib.Path:
    prev = store.read_json(pathlib.Path(run_dir) / "result.json", {}) or {}
    if prev.get("page"):
        return pathlib.Path(prev["page"])
    base = store.pages_dir()
    slug = re.sub(r"[^a-z0-9-]+", "-", topic.lower()).strip("-") or "topic"
    p = base / f"{date}_{slug}.html"
    i = 2
    while p.exists():
        p = base / f"{date}_{slug}-{i}.html"
        i += 1
    return p


def _sibling_script(skill: str, name: str) -> pathlib.Path | None:
    here = pathlib.Path(__file__).resolve().parent.parent.parent / skill / "scripts" / name
    if here.exists():
        return here
    for agent in AGENT_DIRS:
        p = pathlib.Path.home() / f".{agent}" / "skills" / skill / "scripts" / name
        if p.exists():
            return p
    return None


def rebuild_index() -> str | None:
    script = _sibling_script("video-lens-gallery", "build_index.py")
    if not script or not (store.library_dir() / "manifest.json").exists():
        return None
    r = subprocess.run(["python3", str(script), "--dir", str(store.library_dir())],
                       capture_output=True, text=True, timeout=120)
    return None if r.returncode == 0 else "gallery index not rebuilt"


def serve(path: pathlib.Path) -> tuple[list[str], str]:
    """Run video-lens's serve_report.sh; returns (output lines, page URL or '')."""
    script = _sibling_script("video-lens", "serve_report.sh")
    if not script:
        return [f"ERROR:SERVE_SCRIPT_MISSING install video-lens (npx skills add kar2phi/video-lens) "
                f"to serve the page; it is saved at {path}"], ""
    r = subprocess.run(["bash", str(script), str(path), str(store.library_dir())],
                       capture_output=True, text=True, timeout=60)
    lines = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith(("ERROR:", "HTML_REPORT:"))]
    if not any(l.startswith("HTML_REPORT:") for l in lines):
        return lines or [f"ERROR:SERVE_FAILED {r.stderr.strip()[-300:]}"], ""
    port = os.environ.get("VIDEO_LENS_PORT", "8765")
    rel = path.resolve().relative_to(store.library_dir().resolve()).as_posix()
    return lines, f"http://localhost:{port}/{urllib.parse.quote(rel)}"


# ---------- render ----------

def render(run_dir: pathlib.Path, do_serve: bool = True, advance: bool = False) -> tuple[list[str], list[str], int]:
    """Render the run's pages so far. `advance` adds the next page ("next")."""
    run_dir = pathlib.Path(run_dir)
    data = store.read_json(run_dir / "candidates.json")
    if not data:
        return [], [f"ERROR:RUN_DIR_INVALID {run_dir} has no candidates.json; run collect first"], 1
    cands_by_n = {c["n"]: c for c in data["candidates"]}
    try:
        picks = load_picks(run_dir)
        clean, notes = validate_picks(picks, cands_by_n)
    except PicksError as e:
        return [], [f"ERROR:{e.code} {e.detail}"], 1
    cfg = store.load_config()
    topics = data.get("topics") or {}
    order, dropped, more = order_picks(clean, cands_by_n)
    notes += more
    pages = paginate(order, cands_by_n, data["settings"]["picks"], data["settings"]["per_channel_cap"],
                     by_topic=bool(topics)) or [[]]
    prev = store.read_json(run_dir / "result.json", {}) or {}
    shown_pages = (prev.get("pages_shown") or 1) if prev else 1
    if advance:
        shown_pages += 1
        if shown_pages > len(pages):
            return [f"NO_MORE: all {len(order)} picks of this run are shown. Run Step 1 again with the same "
                    "request for fresh candidates; what was shown is skipped."], [], 0
    pages = [assign_sections(p, cands_by_n, i, topics) for i, p in enumerate(pages[:shown_pages], 1)]
    items = build_items(pages, cands_by_n, data.get("waiting") or [])
    also = also_rows(clean, cands_by_n, {it["n"] for it in items if it["n"] is not None}, dropped)
    left = len(order) - sum(it["section"] != "waiting" for it in items)
    data["_picked"] = len(order)
    date = datetime.date.fromtimestamp(data["created"]).isoformat()

    out = [f"NOTE: {n}" for n in notes] if not advance else []
    try:
        page = page_html(data, items, also, cfg, date)
    except (FileNotFoundError, ValueError) as e:
        return out, [f"ERROR:RENDER_TEMPLATE {e}"], 1
    path = page_path(run_dir, data["topic"], date)
    path.parent.mkdir(parents=True, exist_ok=True)
    logged = prev.get("pages_logged", 1) if prev else 0
    path.write_text(page, encoding="utf-8")
    out.append(f"OUTPUT_PATH: {path}")

    new = [it for it in items if it["page"] > logged]
    if new:
        at = datetime.datetime.fromtimestamp(data["created"]).isoformat(timespec="seconds")
        store.append_shown([{
            "event": "shown", "run": data["run"], "topic": data["topic"], "videoId": it["candidate"]["videoId"],
            "rank": it["num"], "section": it["section"], "source": it["candidate"].get("source"), "at": at,
            "title": it["candidate"].get("title"), "channel": it["candidate"].get("channel"),
            "channelId": it["candidate"].get("channelId"), "duration": it["candidate"].get("duration"),
            "published": it["candidate"].get("published"), "reason": it["reason"],
        } for it in new])
    result = {"run": data["run"], "topic": data["topic"], "page": str(path), "created": data["created"],
              "pages_shown": len(pages), "pages_logged": max(logged, len(pages)), "picks": len(order),
              "items": [{"num": it["num"], "videoId": it["candidate"]["videoId"],
                         "url": video_url(it["candidate"]["videoId"]), "title": it["candidate"].get("title"),
                         "channel": it["candidate"].get("channel"), "channelId": it["candidate"].get("channelId"),
                         "page": it["page"], "section": it["section"], "n": it["n"],
                         "relevance": it.get("relevance"), "reason": it["reason"]} for it in items]}
    store.write_json(run_dir / "result.json", result)
    store.write_json(store.cache_dir() / "last_run.json", {"run_dir": str(run_dir)})

    warn = rebuild_index()
    if warn:
        out.append(f"WARN: {warn}")
    url = ""
    if do_serve:
        lines, url = serve(path)
        out += [l for l in lines if l.startswith("ERROR:")]
        served = [l for l in lines if l.startswith("HTML_REPORT:")]
    else:
        served = []
    out.append("--- CHAT LIST (relay this verbatim) ---")
    out.append(chat_list(data, items, len(pages), url, left, len(also)))
    out.append("--- END CHAT LIST ---")
    out += served
    return out, [], 0
