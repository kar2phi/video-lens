#!/usr/bin/env python3
"""video-lens-recs eval: run an agent on recorded topic pulls, gate its picks, score them
against labels (026 §12.3).

    python3 evals/run_recs_eval.py record ai-week --request "what's new in AI this week"
    python3 evals/run_recs_eval.py record ai-week --extend     # add what newer code fetches and shows
    python3 evals/run_recs_eval.py label ai-week               # yes / maybe / no per candidate
    python3 evals/run_recs_eval.py prior                       # precision of the prior alone, weight variants
    python3 evals/run_recs_eval.py run --agent claude          # every fixture, working-tree skill
    python3 evals/run_recs_eval.py run --agent pi --model qwen3.6:27b --ref HEAD
    python3 evals/run_recs_eval.py compare evals/results/A evals/results/B

Fixtures live in evals/recs_fixtures/<name>/, which is gitignored: a recorded fixture holds
the user's topic config, subscriptions and a snapshot of their library, and the repo is
public. Each one has fixture.json (the request, the pinned clock and that state), replay/
(the public source pulls, recorded once; personal feeds are never recorded, so fixtures run
in takeout mode, and YOUTUBE_API_KEY is ignored, so search goes through yt-dlp) and labels.json. The built-in `synthetic` fixture comes from
tests/recs_world.py (made-up channels), so the eval runs on a fresh checkout too.

Each case gets its own XDG dirs, library and server port, so the user's real state, shown
log and ~/Downloads/video-lens are never touched. The skill under test is copied (working
tree, or --ref via git archive) next to copies of video-lens and video-lens-gallery, which
render uses to serve the page and rebuild the index.

Output: evals/results/<stamp>-recs-<agent>-<arm>/ with, per case, trace.jsonl, the run's
run-{candidates,picks,result}.json and the eval's result.json, plus scorecard.json. Exit status 1 when any
gate failed.
"""
import argparse
import contextlib
import hashlib
import io
import json
import os
import pathlib
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from collections import Counter
from datetime import datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES_DIR = REPO_ROOT / "evals" / "recs_fixtures"
RESULTS_DIR = REPO_ROOT / "evals" / "results"
RECS_SCRIPTS = REPO_ROOT / "skills" / "video-lens-recs" / "scripts"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(RECS_SCRIPTS))
import checks  # noqa: E402
import collect  # noqa: E402
import run_eval  # noqa: E402
import scoring  # noqa: E402
import store  # noqa: E402
import yt_sources  # noqa: E402

SKILLS = ("video-lens-recs", "video-lens", "video-lens-gallery")
LABEL_SCORE = {"yes": 1.0, "maybe": 0.5, "no": 0.0}
MANIFEST_FIELDS = ("videoId", "title", "channel", "channelId", "tags", "keywords", "generationDate", "language")
PRIOR_VARIANTS = {
    "default": scoring.PRIOR_WEIGHTS,
    "perf-heavy": {"perf": 0.50, "kw": 0.15, "affinity": 0.15, "fresh": 0.10, "velocity": 0.10},
    "kw-heavy": {"perf": 0.20, "kw": 0.40, "affinity": 0.20, "fresh": 0.10, "velocity": 0.10},
    "affinity-heavy": {"perf": 0.20, "kw": 0.20, "affinity": 0.40, "fresh": 0.10, "velocity": 0.10},
    "fresh-heavy": {"perf": 0.20, "kw": 0.20, "affinity": 0.15, "fresh": 0.30, "velocity": 0.15},
}


# ---------- state ----------

def state_env(root: pathlib.Path) -> dict:
    return {"XDG_CONFIG_HOME": str(root / "config"), "XDG_DATA_HOME": str(root / "data"),
            "XDG_CACHE_HOME": str(root / "cache"), "VIDEO_LENS_LIBRARY": str(root / "library")}


@contextlib.contextmanager
def patched_env(env: dict):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class _EnvRecorder:
    """Stands in for pytest's monkeypatch so tests/recs_world.py can build a fixture here."""

    def __init__(self):
        self.env = {}

    def setenv(self, k, v):
        self.env[k] = str(v)

    def delenv(self, k, raising=True):
        self.env.pop(k, None)


SYNTHETIC_LABELS = {"alphahot": "yes", "alphafrsh": "yes", "srchgood": "yes", "betanew": "yes",
                    "gammaone": "yes", "betatwo": "maybe", "homeone": "yes"}


def synthetic_fixture() -> dict:
    import recs_world as W
    return {"name": "synthetic", "request": "what's new on agents this week", "topic": None,
            "labels": {W.vid(k): {"label": v} for k, v in SYNTHETIC_LABELS.items()}, "builtin": True}


def load_fixtures(only) -> list[dict]:
    fixtures = [synthetic_fixture()]
    for d in sorted(FIXTURES_DIR.glob("*/fixture.json")):
        fx = json.loads(d.read_text(encoding="utf-8"))
        labels = d.parent / "labels.json"
        fx.update(name=d.parent.name, dir=str(d.parent),
                  labels=json.loads(labels.read_text(encoding="utf-8")) if labels.exists() else {})
        fixtures.append(fx)
    if only:
        names = set(only)
        unknown = names - {f["name"] for f in fixtures}
        if unknown:
            sys.exit(f"unknown fixture(s): {', '.join(sorted(unknown))}")
        fixtures = [f for f in fixtures if f["name"] in names]
    return fixtures


def materialise_state(fx: dict, root: pathlib.Path) -> dict:
    """Write the fixture's config, state and library under root; return the env for a run."""
    root.mkdir(parents=True, exist_ok=True)
    if fx.get("builtin"):
        import recs_world as W
        rec = _EnvRecorder()
        W.build(root, rec)
        env = {k: v for k, v in rec.env.items() if k != "HOME"}
        return env
    env = {**state_env(root), yt_sources.REPLAY_ENV: str(pathlib.Path(fx["dir"]) / "replay"),
           yt_sources.NOW_ENV: str(fx["now"]), "NO_BROWSER": "1"}
    with patched_env(env):
        store.save_config(fx["config"])
        subs = fx.get("subscriptions") or {}
        store.save_subscriptions(subs.get("channels", []), subs.get("source", "takeout"), subs.get("export_date", ""))
        store.save_feedback(fx.get("feedback") or {})
        store.save_channel_ids(fx.get("channel_ids") or {})
        store.write_json(store.library_dir() / "manifest.json",
                         {"count": len(fx["reports"]), "reports": fx["reports"]}, private=False)
    return env


def clean_environ(env: dict) -> dict:
    """os.environ plus env, minus anything that would bypass the replay (an API key, a record dir)."""
    base = {k: v for k, v in os.environ.items()
            if k not in ("YOUTUBE_API_KEY", yt_sources.RECORD_ENV, yt_sources.REPLAY_ENV, yt_sources.NOW_ENV)}
    return {**base, **env}


def recs_cli(env: dict, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RECS_SCRIPTS / "recs.py"), *args], capture_output=True,
                          text=True, env=clean_environ(env), timeout=900)


def excluded_ids(env: dict) -> set:
    """What the fixture's state says must never be picked: summarised and dismissed videos."""
    with patched_env(env):
        return {r["videoId"] for r in store.load_reports()} | set(store.load_feedback()["dismissed"])


def latest_run_dir(root_env: dict) -> pathlib.Path | None:
    runs = sorted(pathlib.Path(root_env["XDG_CACHE_HOME"], "video-lens", "recs", "runs").glob("*/candidates.json"),
                  key=lambda p: p.stat().st_mtime)
    return runs[-1].parent if runs else None


# ---------- record + label ----------

def seed_labels(fx_dir: pathlib.Path, candidates: list) -> int:
    """Add table rows to labels.json, unlabelled; returns how many were new."""
    path = fx_dir / "labels.json"
    labels = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    new = 0
    for c in candidates:
        if c["videoId"] not in labels:
            labels[c["videoId"]] = {"label": "", "title": c["title"], "channel": c["channel"], "source": c["source"]}
            new += 1
    path.write_text(json.dumps(labels, indent=1, ensure_ascii=False), encoding="utf-8")
    return new


def extend(args) -> int:
    """Run the working-tree code on a recorded fixture with replay and record on: pulls it
    asks for that the recording lacks are fetched live and added, at the fixture's pinned
    clock, and its table rows join labels.json. Both arms of a comparison then replay fully
    and every row either arm can show gets a label."""
    fx = next((f for f in load_fixtures([args.name]) if not f.get("builtin")), None)
    if fx is None:
        sys.exit(f"{args.name} is not a recorded fixture")
    fx_dir = pathlib.Path(fx["dir"])
    before = len(list((fx_dir / "replay").glob("*.json")))
    with tempfile.TemporaryDirectory(prefix="recs-extend-") as tmp:
        env = materialise_state(fx, pathlib.Path(tmp))
        env[yt_sources.RECORD_ENV] = str(fx_dir / "replay")
        topic = ["--topic", fx["topic"]] if fx.get("topic") else []
        r = recs_cli(env, "recommend", *topic, "--", fx["request"])
        if r.returncode != 0:
            print(r.stdout + r.stderr, file=sys.stderr)
            return 1
        data = json.loads((latest_run_dir(env) / "candidates.json").read_text(encoding="utf-8"))
    added = len(list((fx_dir / "replay").glob("*.json"))) - before
    new = seed_labels(fx_dir, data["candidates"])
    print(f"EXTENDED: {fx_dir} · {added} source pulls added · {len(data['candidates'])} rows in the table, "
          f"{new} new to labels.json")
    return 0


def record(args) -> int:
    if args.extend:
        return extend(args)
    if not args.request:
        sys.exit("record needs --request (or --extend for an existing fixture)")
    fx_dir = FIXTURES_DIR / args.name
    if fx_dir.exists() and not args.force:
        sys.exit(f"{fx_dir} exists; pass --force to re-record")
    if not store.config_exists():
        sys.exit("video-lens-recs is not set up yet (no topics); run its setup first")
    cfg = store.load_config()
    if cfg["account"]["mode"] == "live":
        cfg["account"]["mode"] = "takeout"     # personal feeds are never recorded
    reports = [{k: r[k] for k in MANIFEST_FIELDS if k in r} for r in store.load_reports()]
    fb = store.load_feedback()
    fx = {"request": args.request, "topic": args.topic, "now": time.time(), "config": cfg,
          "subscriptions": store.load_subscriptions(), "feedback": fb,
          "channel_ids": store.load_channel_ids(), "reports": reports}
    if fx_dir.exists():
        shutil.rmtree(fx_dir)
    (fx_dir / "replay").mkdir(parents=True)
    (fx_dir / "fixture.json").write_text(json.dumps(fx, indent=1, ensure_ascii=False), encoding="utf-8")
    fx.update(name=args.name, dir=str(fx_dir))
    with tempfile.TemporaryDirectory(prefix="recs-record-") as tmp:
        env = materialise_state(fx, pathlib.Path(tmp))
        env.pop(yt_sources.REPLAY_ENV)
        env[yt_sources.RECORD_ENV] = str(fx_dir / "replay")
        topic = ["--topic", args.topic] if args.topic else []
        r = recs_cli(env, "recommend", *topic, "--", args.request)
        if r.returncode != 0:
            print(r.stdout + r.stderr, file=sys.stderr)
            return 1
        run_dir = latest_run_dir(env)
        shutil.copy(run_dir / "candidates.json", fx_dir / "candidates.json")
    data = json.loads((fx_dir / "candidates.json").read_text(encoding="utf-8"))
    counts = next((l for l in r.stdout.splitlines() if l.startswith("COUNTS:")), "")
    seed_labels(fx_dir, data["candidates"])
    print(f"RECORDED: {fx_dir} · {len(list((fx_dir / 'replay').glob('*.json')))} source pulls · "
          f"{len(data['candidates'])} candidates in the table")
    print(counts)
    print(f"NEXT: label them: python3 evals/run_recs_eval.py label {args.name}")
    return 0


def label(args) -> int:
    fx_dir = FIXTURES_DIR / args.name
    data = json.loads((fx_dir / "candidates.json").read_text(encoding="utf-8"))
    path = fx_dir / "labels.json"
    labels = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for c in data["candidates"]:
        labels.setdefault(c["videoId"], {"label": "", "title": c["title"], "channel": c["channel"],
                                         "source": c["source"]})
    # --review steps through every row, drafts first; Enter keeps the current label.
    todo = [v for v, l in labels.items() if args.review or l["label"] not in LABEL_SCORE]
    todo.sort(key=lambda v: labels[v].get("by") != "draft")
    if not sys.stdin.isatty():
        path.write_text(json.dumps(labels, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{len(todo)} to label; set \"label\" to yes, maybe or no in {path}")
        return 0
    print(f"{len(todo)} to label · y = would watch, m = maybe, n = no, Enter = keep, q = save and quit")
    for i, vid in enumerate(todo, 1):
        l = labels[vid]
        draft = f" [{l.get('by', 'yours')}: {l['label']}]" if l["label"] else ""
        ans = input(f"[{i}/{len(todo)}] {l['title']} — {l['channel']} ({l['source']}){draft} > ").strip().lower()[:1]
        if ans == "q":
            break
        if ans in ("y", "m", "n"):
            l["label"] = {"y": "yes", "m": "maybe", "n": "no"}[ans]
            l["by"] = "you"
        elif not ans and l["label"]:
            l["by"] = "you"
        path.write_text(json.dumps(labels, indent=1, ensure_ascii=False), encoding="utf-8")
    path.write_text(json.dumps(labels, indent=1, ensure_ascii=False), encoding="utf-8")
    left = sum(l["label"] not in LABEL_SCORE for l in labels.values())
    print(f"saved {path} · {left} unlabelled")
    return 0


# ---------- metrics ----------

def precision_at(video_ids: list, labels: dict, k: int, pool: int) -> float | None:
    """Mean label score of the first k picks; the denominator is min(k, pool size)."""
    if not labels:
        return None
    denom = min(k, pool)
    if denom == 0:
        return None
    got = [LABEL_SCORE.get((labels.get(v) or {}).get("label"), 0.0) for v in video_ids[:k]]
    return round(sum(got) / denom, 3)


def collect_once(fx: dict, root: pathlib.Path) -> tuple[dict, pathlib.Path]:
    env = materialise_state(fx, root)
    topic = ["--topic", fx["topic"]] if fx.get("topic") else []
    r = recs_cli(env, "recommend", *topic, "--", fx["request"])
    if r.returncode != 0:
        raise RuntimeError(r.stdout + r.stderr)
    run_dir = latest_run_dir(env)
    return json.loads((run_dir / "candidates.json").read_text(encoding="utf-8")), run_dir


def prior(args) -> int:
    fixtures = load_fixtures(args.only.split(",") if args.only else None)
    print("Precision of the prior alone, within the shortlist the default weights chose "
          "(yes = 1, maybe = 0.5).\n")
    print("| fixture | labelled | variant | P@5 | P@10 |")
    print("|---|---|---|---|---|")
    for fx in fixtures:
        with tempfile.TemporaryDirectory(prefix="recs-prior-") as tmp:
            data, _ = collect_once(fx, pathlib.Path(tmp))
        cands, labels = data["candidates"], fx.get("labels") or {}
        n_lab = sum(c["videoId"] in labels and labels[c["videoId"]].get("label") in LABEL_SCORE for c in cands)
        for name, weights in PRIOR_VARIANTS.items():
            scores = scoring.prior_scores(cands, weights)
            order = [c["videoId"] for _, c in sorted(zip(scores, cands), key=lambda t: -t[0])]
            p5, p10 = (precision_at(order, labels, k, len(cands)) for k in (5, 10))
            print(f"| {fx['name']} | {n_lab}/{len(cands)} | {name} | {p5} | {p10} |")
    return 0


# ---------- agent run ----------

def materialise_skills(ref, dest: pathlib.Path) -> dict:
    """Copy the three skills (working tree or `ref`) to dest/; pin the recs discovery loop."""
    if ref:
        blob = subprocess.run(["git", "-C", str(REPO_ROOT), "archive", ref, *(f"skills/{s}" for s in SKILLS)],
                              capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            tar.extractall(dest / "_archive", filter="data")
        for s in SKILLS:
            shutil.move(str(dest / "_archive" / "skills" / s), dest / s)
        shutil.rmtree(dest / "_archive")
    else:
        for s in SKILLS:
            shutil.copytree(REPO_ROOT / "skills" / s, dest / s, ignore=shutil.ignore_patterns("__pycache__"))
    target = dest / "video-lens-recs"
    skill_md = (target / "SKILL.md").read_bytes()
    pinned = f'for d in {shlex.quote(str(target))}; do [ -d "$d/scripts" ] && echo "$d/scripts"'
    text, n = DISCOVERY_RE.subn(lambda _: pinned, (target / "SKILL.md").read_text(encoding="utf-8"))
    (target / "SKILL.md").write_text(text, encoding="utf-8")
    version = re.search(rb'^\s*version:\s*"?([^"\n]+)"?', skill_md, re.M)
    return {"path": str(target), "sha": hashlib.sha256(skill_md).hexdigest()[:12], "pinned": n,
            "version": version.group(1).decode() if version else "?", "bytes": len(skill_md)}


DISCOVERY_RE = re.compile(r'for d in ~/\.agents[^;]*; do \[ -d "\$d/skills/video-lens-recs/scripts" \] '
                          r'&& echo "\$d/skills/video-lens-recs/scripts"')


def agent_command(agent, skill_dir: pathlib.Path, work: pathlib.Path, request: str, model, extra) -> list:
    if agent == "claude":
        skills = work / ".claude" / "skills"
        skills.mkdir(parents=True)
        (skills / "video-lens-recs").symlink_to(skill_dir)
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose",
               "--setting-sources", "project", "--dangerously-skip-permissions",
               "--allowedTools", "Bash,Read,Write"]
        prompt = ["--", f"/video-lens-recs {request}"]
    else:
        cmd = ["pi", "-p", "--mode", "json", "--no-session", "--no-skills",
               "--no-context-files", "--skill", str(skill_dir)]
        prompt = [f"/skill:video-lens-recs {request}"]
    if model:
        cmd += ["--model", model]
    return cmd + extra + prompt


def stop_server(env: dict) -> None:
    pid_file = pathlib.Path(env["XDG_CACHE_HOME"]) / "video-lens" / "server.pid"
    try:
        pid = int(pid_file.read_text().strip())
    except (OSError, ValueError):
        return
    cmd = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout
    if "http.server" in cmd and env.get("VIDEO_LENS_PORT", "") in cmd:
        os.kill(pid, signal.SIGTERM)


QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def _norm(s: str) -> str:
    """Whitespace, bold, backticks and curly quotes don't count as changing a relayed line."""
    return re.sub(r"\s+", " ", s.replace("**", "").replace("`", "").translate(QUOTES)).strip()


def chat_list(render_output: str) -> list[str]:
    m = re.search(r"--- CHAT LIST \(relay this verbatim\) ---\n(.*?)\n--- END CHAT LIST ---", render_output, re.S)
    return [l for l in m.group(1).splitlines() if l.strip()] if m else []


def topic_resolver(fx):
    """For all-topics fixtures: candidate → topic key by its channel or its search query, from
    the fixture's config, so both arms are counted the same way whatever the code assigns."""
    if fx.get("builtin") or fx.get("topic") not in (None, "all"):
        return None
    topics = (fx.get("config") or {}).get("topics") or {}
    if (fx.get("topic") or collect.match_topic(fx["request"], topics)[0]) != "all":
        return None
    by_channel = {cid: k for k, t in topics.items() for cid in t.get("channels", [])}
    by_query = {q: k for k, t in topics.items() for q in t.get("queries", [])}
    return lambda c: by_channel.get(c.get("channelId")) or by_query.get(c.get("query"))


def judge(fx, trace, run_dir, final, excluded: set) -> tuple[dict, dict]:
    labels = fx.get("labels") or {}
    data = json.loads((run_dir / "candidates.json").read_text(encoding="utf-8")) if run_dir else None
    cands = data["candidates"] if data else []
    by_n = {c["n"]: c for c in cands}
    raw = None
    if run_dir and (run_dir / "picks.json").exists():
        try:
            raw = json.loads((run_dir / "picks.json").read_text(encoding="utf-8"))
            raw = raw.get("picks") if isinstance(raw, dict) else raw
        except ValueError:
            raw = None
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8")) \
        if run_dir and (run_dir / "result.json").exists() else None
    items = result["items"] if result else []
    renders = [c for c in trace["calls"] if c["name"] == "bash" and "recs.py" in c["target"]
               and re.search(r"\brender\b", c["target"])]
    render_out = next((c["output"] for c in reversed(renders) if "CHAT LIST" in c["output"]), "")
    recommend_out = next((c["output"] for c in trace["calls"] if c["name"] == "bash"
                          and re.search(r"recs\.py\"? (recommend|collect)", c["target"])), "")

    settings = (data or {}).get("settings") or {}
    page_size, cap = settings.get("picks", 8), settings.get("per_channel_cap", 2)
    page1 = [i for i in items if i.get("page", 1) == 1 and i.get("section") != "waiting"]
    picked = [i["videoId"] for i in items]
    raw_ns = [p.get("n") for p in raw if isinstance(p, dict)] if isinstance(raw, list) else []
    rated = [p for p in raw if isinstance(p, dict) and p.get("relevance") is not None] if isinstance(raw, list) else []
    per_channel = Counter(i.get("channelId") or i.get("channel") for i in page1)
    yes = {v for v, l in labels.items() if l.get("label") == "yes"}
    yes_in_pool = [c for c in cands if c["videoId"] in yes]
    # A page holds at most `cap` rows of one channel, so that is all of a channel's yes rows
    # a full first page can be asked to show.
    yes_per_channel = Counter(c.get("channelId") or c.get("channel") for c in yes_in_pool)
    yes_showable = sum(min(cap, n) for n in yes_per_channel.values())
    discovery_yes = any(scoring.source_group(c) != "own" for c in yes_in_pool)
    cand_by_vid = {c["videoId"]: c for c in cands}
    beyond = [v for v in picked if v in cand_by_vid and scoring.source_group(cand_by_vid[v]) != "own"]
    lines = chat_list(render_out)
    final_n = _norm(final)
    numbered = [l for l in lines if re.match(r"\s*\d+\. ", l)]

    gates = {
        "recommended": bool(cands),
        "rendered": result is not None,
        "picks_known": bool(raw_ns) and all(n in by_n for n in raw_ns),
        "no_excluded": result is not None and all(v in cand_by_vid and v not in excluded for v in picked),
        "pick_count": (min(page_size, yes_showable) <= len(page1) <= page_size) if labels and result else None,
        "channel_cap": result is not None and max(per_channel.values() or [0]) <= cap,
        "beyond": bool(beyond) if discovery_yes and result else None,
        "reasons_ok": result is not None and all(i.get("reason", "").strip() and
                                                 _norm(i["reason"]).lower() != _norm(i["title"]).lower()
                                                 for i in items),
        "chat_relayed": bool(numbered) and all(_norm(l) in final_n for l in numbered),
        "served": "HTML_REPORT:" in render_out,
    }
    table_channels = Counter(c["channelId"] or c["channel"] for c in cands)
    lab = [(labels.get(c["videoId"]) or {}).get("label") for c in cands]
    page1_c = [cand_by_vid[v] for v in (i["videoId"] for i in page1) if v in cand_by_vid]
    topic_of = topic_resolver(fx)
    metrics = {
        "candidates": len(cands), "picks": len(page1), "picks_raw": len(raw_ns),
        "rated": len(rated), "showable": result.get("picks") if result else None,
        "table_channels": len(table_channels), "table_max_per_channel": max(table_channels.values() or [0]),
        "table_yes": lab.count("yes"), "table_maybe": lab.count("maybe"), "table_no": lab.count("no"),
        "table_unlabelled": sum(l not in LABEL_SCORE for l in lab) if labels else None,
        "page1_yes": sum((labels.get(c["videoId"]) or {}).get("label") == "yes" for c in page1_c) if labels else None,
        "table_topics": len({topic_of(c) for c in cands} - {None}) if topic_of else None,
        "page1_topics": len({topic_of(c) for c in page1_c} - {None}) if topic_of else None,
        "beyond_picks": len([v for v in beyond if v in {i["videoId"] for i in page1}]),
        "top_picks": sum(i.get("section") == "top" for i in items),
        "render_attempts": len(renders), "replay_misses": recommend_out.count("REPLAY_MISS"),
        "chat_lines_relayed": round(sum(_norm(l) in final_n for l in lines) / len(lines), 2) if lines else None,
        "p_at_5": precision_at([i["videoId"] for i in page1], labels, 5, len(cands)),
        "p_at_10": precision_at([i["videoId"] for i in page1], labels, 10, len(cands)),
        "prior_p_at_5": precision_at([c["videoId"] for c in sorted(cands, key=lambda c: -(c.get("prior") or 0))],
                                     labels, 5, len(cands)),
    }
    return gates, metrics


def run_case(fx, run_idx, args, skill, out: pathlib.Path) -> dict:
    case = out / f"{fx['name']}-{run_idx}"
    case.mkdir(parents=True)
    env = materialise_state(fx, case / "state")
    env["VIDEO_LENS_PORT"] = str(args.port)
    excluded = excluded_ids(env)
    work = pathlib.Path(tempfile.mkdtemp(prefix=f"video-lens-recs-eval-{fx['name']}-"))
    cmd = agent_command(args.agent, pathlib.Path(skill["path"]), work, fx["request"], args.model,
                        shlex.split(args.agent_args or ""))
    (case / "command.txt").write_text(shlex.join(cmd) + "\n", encoding="utf-8")
    started = time.time()
    timed_out = threading.Event()
    trace_path = case / "trace.jsonl"
    with open(trace_path, "w", encoding="utf-8") as trace_file, \
            open(case / "stderr.txt", "w", encoding="utf-8") as err_file:
        proc = subprocess.Popen(cmd, cwd=work, stdout=subprocess.PIPE, stderr=err_file, text=True,
                                env=clean_environ(env))
        watchdog = threading.Timer(args.timeout, lambda: (timed_out.set(), proc.kill()))
        watchdog.start()
        for line in proc.stdout:
            if not (args.agent == "pi" and line.startswith(run_eval.PI_NOISE)):
                trace_file.write(line)
        proc.wait()
        watchdog.cancel()
    wall = round(time.time() - started, 1)
    stop_server(env)
    shutil.rmtree(work, ignore_errors=True)

    run_dir = latest_run_dir(env)
    for name in ("candidates.json", "picks.json", "result.json"):
        if run_dir and (run_dir / name).exists():
            shutil.copy(run_dir / name, case / f"run-{name}")
    trace = checks.load_trace(trace_path.read_text(encoding="utf-8").splitlines(), args.agent)
    gates, metrics = judge(fx, trace, run_dir, trace["final"], excluded)
    gates["finished"] = not timed_out.is_set() and proc.returncode == 0
    metrics.update(wall_s=wall, tool_calls=len(trace["calls"]),
                   bash_calls=sum(c["name"] == "bash" for c in trace["calls"]),
                   turns=trace["turns"], cost_usd=trace["cost_usd"])
    result = {"fixture": fx["name"], "run": run_idx, "agent": args.agent,
              "model": trace["model"] or args.model or "", "exit_code": proc.returncode,
              "timed_out": timed_out.is_set(), "gates": gates, "metrics": metrics,
              "final": trace["final"][-1500:]}
    (case / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(case / "state", ignore_errors=True)
    return result


def print_case(r):
    failed = run_eval._failed(r)
    m = r["metrics"]
    bits = [f"{m['wall_s']:.0f}s", f"{m['tool_calls']} calls", f"{m['picks']} picks ({m['beyond_picks']} beyond)"]
    if m.get("p_at_5") is not None:
        bits.append(f"P@5 {m['p_at_5']:.2f} (prior {m['prior_p_at_5']:.2f})")
    if m.get("cost_usd"):
        bits.append(f"${m['cost_usd']:.2f}")
    status = "PASS" if not failed else "FAIL " + ",".join(failed)
    print(f"  {r['fixture']:<14} #{r['run']}  {status:<40} {' · '.join(bits)}", flush=True)


def run(args) -> int:
    fixtures = load_fixtures(args.only.split(",") if args.only else None)
    arm = (args.ref or "wt").replace("/", "_")
    # Absolute: the agent runs in a temp dir and reaches the skill copy through this path.
    out = pathlib.Path(args.out).resolve() if args.out else \
        RESULTS_DIR / f"{datetime.now():%Y%m%d-%H%M%S}-recs-{args.agent}-{arm}"
    out.mkdir(parents=True)
    skill = materialise_skills(args.ref, out / "_skills")
    if not skill["pinned"]:
        sys.exit("could not pin the scripts-discovery loop in SKILL.md; update DISCOVERY_RE")
    print(f"recs eval → {out}  (skill {skill['version']}/{skill['sha']}, agent {args.agent}"
          f"{' ' + args.model if args.model else ''}, {len(fixtures)} fixture(s) × {args.runs})")
    cases = []
    for fx in fixtures:
        for i in range(1, args.runs + 1):
            r = run_case(fx, i, args, skill, out)
            print_case(r)
            cases.append(r)
    card = {"run_id": out.name, "agent": args.agent, "model": next((c["model"] for c in cases if c["model"]), ""),
            "skill": {**skill, "replay": True}, "cases": cases}
    (out / "scorecard.json").write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.rmtree(out / "_skills", ignore_errors=True)
    failed = [c for c in cases if run_eval._failed(c)]
    print(f"\n{len(cases) - len(failed)}/{len(cases)} cases passed every gate · {out / 'scorecard.json'}")
    return 1 if failed else 0


def rejudge(args) -> int:
    """Score a finished run again from its saved traces and run files, with today's labels
    and gates: after a label review, no agent has to run again."""
    out = pathlib.Path(args.run).resolve()
    card = json.loads((out / "scorecard.json").read_text(encoding="utf-8"))
    fixtures = {f["name"]: f for f in load_fixtures(None)}
    for r in card["cases"]:
        case, fx = out / f"{r['fixture']}-{r['run']}", fixtures.get(r["fixture"])
        if fx is None:
            print(f"  {r['fixture']:<14} #{r['run']}  skipped: no such fixture")
            continue
        with tempfile.TemporaryDirectory(prefix="recs-rejudge-") as tmp:
            excluded = excluded_ids(materialise_state(fx, pathlib.Path(tmp) / "state"))
            run_dir = pathlib.Path(tmp) / "run"
            run_dir.mkdir()
            for name in ("candidates.json", "picks.json", "result.json"):
                if (case / f"run-{name}").exists():
                    shutil.copy(case / f"run-{name}", run_dir / name)
            trace = checks.load_trace((case / "trace.jsonl").read_text(encoding="utf-8").splitlines(), card["agent"])
            gates, metrics = judge(fx, trace, run_dir if (run_dir / "candidates.json").exists() else None,
                                   trace["final"], excluded)
        r["gates"] = {**gates, "finished": r["gates"].get("finished")}
        r["metrics"] = {**r["metrics"], **metrics}
        (case / "result.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
        print_case(r)
    (out / "scorecard.json").write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
    failed = [c for c in card["cases"] if run_eval._failed(c)]
    print(f"\n{len(card['cases']) - len(failed)}/{len(card['cases'])} cases passed every gate · {out / 'scorecard.json'}")
    return 1 if failed else 0


COMPARE_METRICS = ("picks", "showable", "rated", "beyond_picks", "top_picks", "p_at_5", "p_at_10", "prior_p_at_5",
                   "page1_yes", "table_yes", "table_no", "table_unlabelled", "table_channels",
                   "table_max_per_channel", "table_topics", "page1_topics",
                   "chat_lines_relayed", "render_attempts", "tool_calls", "wall_s", "cost_usd")


def compare(args) -> int:
    run_eval.COMPARE_METRICS = COMPARE_METRICS
    return run_eval.compare(args.run_a, args.run_b)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("record", help="record a fixture from your current recs state (gitignored)")
    p.add_argument("name")
    p.add_argument("--request")
    p.add_argument("--topic")
    p.add_argument("--force", action="store_true")
    p.add_argument("--extend", action="store_true", help="add what the working tree fetches and shows")
    p = sub.add_parser("label", help="label a recorded fixture's candidates yes / maybe / no")
    p.add_argument("name")
    p.add_argument("--review", action="store_true", help="step through every row, drafts first")
    p = sub.add_parser("prior", help="precision of the prior alone, for each weight variant")
    p.add_argument("--only")
    p = sub.add_parser("run", help="run an agent on the fixtures")
    p.add_argument("--agent", choices=("claude", "pi"), default="claude")
    p.add_argument("--model")
    p.add_argument("--ref", help="git ref of the skills to test (default: the working tree)")
    p.add_argument("--only", help="comma-separated fixture names")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--timeout", type=int, default=1200, help="seconds per case")
    p.add_argument("--port", type=int, default=8797, help="port for the served page (not the user's 8765)")
    p.add_argument("--agent-args", help="extra CLI flags for the agent")
    p.add_argument("--out")
    p = sub.add_parser("rejudge", help="score a finished run again with the current labels and gates")
    p.add_argument("run")
    p = sub.add_parser("compare", help="compare two runs; exits 1 on a gate regression")
    p.add_argument("run_a")
    p.add_argument("run_b")
    args = ap.parse_args(argv)
    return {"record": record, "label": label, "prior": prior, "run": run, "rejudge": rejudge,
            "compare": compare}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
