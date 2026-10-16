#!/usr/bin/env python3
"""Real-video eval: run an agent on the fixture videos, then validate every report and trace.

    python3 evals/run_eval.py --agent claude                    # slim set, working-tree skill
    python3 evals/run_eval.py --agent pi --model qwen3.6:27b    # local qwen through pi
    python3 evals/run_eval.py --agent claude --ref HEAD         # the committed skill (A/B arm)
    python3 evals/run_eval.py --agent claude --only smoke --runs 2
    python3 evals/run_eval.py --compare evals/results/A evals/results/B

The skill under test is copied into the run directory and loaded from there (claude:
project skill with --setting-sources project; pi: --no-skills --skill), so the installed
copy in ~/.agents or ~/.claude is never used or modified. Reports land in the live
~/Downloads/video-lens/reports (SKILL.md hardcodes it); each one is moved into its case
directory right after the run and the gallery index is rebuilt at the end.

The two network scripts are replayed from evals/cache/ (see replay.py): each fixture is
fetched from YouTube once, and both A/B arms then read the same transcript. --live fetches
everything fresh; the network tier (task test-real) always does.

Output: evals/results/<stamp>-<agent>-<arm>/ with, per case, trace.jsonl, the report and
result.json, plus scorecard.json. Exit status 1 when any gate failed, 2 when the only
problem was YouTube blocking transcript requests (those cases are not scored).
"""
import argparse
import hashlib
import io
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import checks  # noqa: E402
import replay  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES_PATH = REPO_ROOT / "evals" / "fixtures.json"
RESULTS_DIR = REPO_ROOT / "evals" / "results"
LIBRARY = pathlib.Path.home() / "Downloads" / "video-lens"
# pi re-sends the growing message on every streamed token (O(n²) bytes) and repeats whole
# transcripts in turn_end/agent_end; message_end and tool_execution_* carry everything needed.
BLOCKED_RE = re.compile(r"IpBlocked|RequestBlocked|ERROR:(IP|REQUEST)_BLOCKED")
PI_NOISE = tuple('{"type":"%s"' % t for t in
                 ("message_update", "tool_execution_update", "turn_end", "agent_end"))


def load_fixtures(selected_set: str, only):
    fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))["fixtures"]
    if only:
        names = set(only)
        unknown = names - {f["name"] for f in fixtures}
        if unknown:
            sys.exit(f"unknown fixture(s): {', '.join(sorted(unknown))}")
        return [f for f in fixtures if f["name"] in names]
    return [f for f in fixtures if selected_set in f["sets"]]


def materialise_skill(ref, dest: pathlib.Path) -> dict:
    """Copy skills/video-lens (working tree, or `ref` via git archive) to dest/video-lens."""
    target = dest / "video-lens"
    if ref:
        blob = subprocess.run(["git", "-C", str(REPO_ROOT), "archive", ref, "skills/video-lens"],
                              capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
            tar.extractall(dest / "_archive", filter="data")
        shutil.move(str(dest / "_archive" / "skills" / "video-lens"), target)
        shutil.rmtree(dest / "_archive")
    else:
        shutil.copytree(REPO_ROOT / "skills" / "video-lens", target,
                        ignore=shutil.ignore_patterns("__pycache__"))
    skill_md = (target / "SKILL.md").read_bytes()
    version = re.search(rb'^\s*version:\s*"?([^"\n]+)"?', skill_md, re.M)
    return {"path": str(target), "sha": hashlib.sha256(skill_md).hexdigest()[:12],
            "version": version.group(1).decode() if version else "?", "bytes": len(skill_md)}


_truth_cache = {}


def ground_truth(video: str, use_cache: bool) -> dict:
    """Duration and chapters straight from yt-dlp, independent of the agent run."""
    cached = replay.CACHE_DIR / f"truth.{video}.json"
    if use_cache and cached.exists():
        _truth_cache.setdefault(video, json.loads(cached.read_text(encoding="utf-8")))
    if video not in _truth_cache:
        r = subprocess.run(["yt-dlp", "--skip-download", "--quiet", "--no-warnings",
                            "--no-check-formats", "--dump-json", f"https://www.youtube.com/watch?v={video}"],
                           capture_output=True, text=True, timeout=120)
        try:
            data = json.loads(r.stdout)
            _truth_cache[video] = {"duration": data.get("duration"),
                                   "chapters": data.get("chapters") or []}
        except ValueError:
            _truth_cache[video] = {"duration": None, "chapters": []}
        if use_cache and _truth_cache[video]["duration"]:
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(json.dumps(_truth_cache[video], ensure_ascii=False), encoding="utf-8")
    return _truth_cache[video]


def agent_command(agent, skill_dir: pathlib.Path, work: pathlib.Path, prompt_args: str,
                  model, extra) -> list:
    if agent == "claude":
        skills = work / ".claude" / "skills"
        skills.mkdir(parents=True)
        (skills / "video-lens").symlink_to(skill_dir)
        # --setting-sources project: only the project skill above loads, never ~/.claude/skills.
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose",
               "--setting-sources", "project", "--dangerously-skip-permissions",
               "--allowedTools", "Bash,Read,Write"]
        prompt = ["--", f"/video-lens {prompt_args}"]
    else:
        cmd = ["pi", "-p", "--mode", "json", "--no-session", "--no-skills",
               "--no-context-files", "--skill", str(skill_dir)]
        prompt = [f"/skill:video-lens {prompt_args}"]
    if model:
        cmd += ["--model", model]
    return cmd + extra + prompt


def run_case(fixture, run_idx, args, skill, out: pathlib.Path) -> dict:
    case = out / f"{fixture['name']}-{run_idx}"
    case.mkdir(parents=True)
    # cwd outside any git repo: inside this one, Claude Code attaches the repo's CLAUDE.md
    # and auto-memory to the session, which no real user run would have.
    work = pathlib.Path(tempfile.mkdtemp(prefix=f"video-lens-eval-{fixture['name']}-"))
    url = f"https://www.youtube.com/watch?v={fixture['video']}"
    prompt_args = f"{url} {fixture.get('lang', '')}".strip()
    cmd = agent_command(args.agent, pathlib.Path(skill["path"]), work, prompt_args,
                        args.model, shlex.split(args.agent_args or ""))
    (case / "command.txt").write_text(shlex.join(cmd) + "\n", encoding="utf-8")

    truth = ground_truth(fixture["video"], use_cache=not args.live)
    started = time.time()
    timed_out = threading.Event()
    trace_path = case / "trace.jsonl"
    with open(trace_path, "w", encoding="utf-8") as trace_file, \
            open(case / "stderr.txt", "w", encoding="utf-8") as err_file:
        proc = subprocess.Popen(cmd, cwd=work, stdout=subprocess.PIPE, stderr=err_file, text=True,
                                env={**os.environ, "NO_BROWSER": "1", replay.LOG_ENV: str(case / "replay.jsonl")})
        watchdog = threading.Timer(args.timeout, lambda: (timed_out.set(), proc.kill()))
        watchdog.start()
        for line in proc.stdout:
            if not (args.agent == "pi" and line.startswith(PI_NOISE)):
                trace_file.write(line)
        proc.wait()
        watchdog.cancel()
    wall = round(time.time() - started, 1)
    shutil.rmtree(work, ignore_errors=True)

    # Move what this run wrote out of the live library.
    reports = sorted(
        (p for p in (LIBRARY / "reports").glob(f"*video-lens_{fixture['video']}_*.html")
         if p.stat().st_mtime >= started - 1),
        key=lambda p: p.stat().st_mtime)
    moved = []
    for p in reports:
        dest = case / p.name
        shutil.move(str(p), dest)
        moved.append(dest)

    trace = checks.load_trace(trace_path.read_text(encoding="utf-8").splitlines(), args.agent)
    report = checks.parse_report(moved[-1].read_text(encoding="utf-8")) if moved else None
    replay_log = case / "replay.jsonl"
    fetches = [json.loads(l) for l in replay_log.read_text(encoding="utf-8").splitlines()] if replay_log.exists() else []
    existing = next((c["output"] for c in trace["calls"] if "preflight.py" in c["target"]), "")
    existing_tags = re.search(r"^EXISTING_TAGS: (.*)$", existing, re.M)
    existing_tags = [t.strip() for t in existing_tags.group(1).split(",")] if existing_tags else None

    gates = checks.gates(fixture, trace, report, len(moved), chapters=truth["chapters"])
    gates["finished"] = not timed_out.is_set() and proc.returncode == 0
    metrics = {"wall_s": wall, **checks.trace_metrics(trace)}
    if report:
        metrics.update(checks.report_metrics(report, truth["duration"], truth["chapters"], existing_tags))
    result = {
        "fixture": fixture["name"], "video": fixture["video"], "run": run_idx,
        "agent": args.agent, "model": trace["model"] or args.model or "", "exit_code": proc.returncode,
        "timed_out": timed_out.is_set(), "reports": [p.name for p in moved],
        "blocked": any(BLOCKED_RE.search(c["output"]) for c in trace["calls"]
                       if "fetch_transcript.py" in c["target"]),
        "inputs": {"replayed": sum(f["replayed"] for f in fetches),
                   "live": sum(not f["replayed"] for f in fetches)},
        "gates": gates, "metrics": metrics, "final": trace["final"][-600:],
    }
    (case / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def _failed(result) -> list:
    return [k for k, v in result["gates"].items() if v is False]


def youtube_blocked(video: str) -> bool:
    """One transcript request up front, so a blocked IP does not burn a whole agent run."""
    r = subprocess.run([sys.executable, str(REPO_ROOT / "skills" / "video-lens" / "scripts" / "fetch_transcript.py"),
                        "--", video], capture_output=True, text=True, timeout=60)
    return bool(BLOCKED_RE.search(r.stdout + r.stderr))


def print_case(r):
    failed = _failed(r)
    m = r["metrics"]
    bits = [f"{m['wall_s']:.0f}s", f"{m['tool_calls']} calls"]
    if "kp_count" in m:
        bits += [f"kp {m['kp_count']} ({m['kp_paragraph_share']:.0%} ¶)", f"outline {m['outline_count']}",
                 f"ts✗ {m['ts_mismatches']}"]
    if m.get("cost_usd"):
        bits.append(f"${m['cost_usd']:.2f}")
    status = ("BLOCKED by YouTube (not scored)" if r.get("blocked")
              else "PASS" if not failed else "FAIL " + ",".join(failed))
    print(f"  {r['fixture']:<14} #{r['run']}  {status:<40} {' · '.join(bits)}", flush=True)


def run(args) -> int:
    fixtures = load_fixtures(args.set, args.only.split(",") if args.only else None)
    for tool in ([args.agent, "yt-dlp"]):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found on PATH")
    arm = args.ref or "worktree"
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{args.agent}-{re.sub(r'[^A-Za-z0-9._-]+', '_', arm)}"
    out = pathlib.Path(args.out or RESULTS_DIR / run_id)
    out.mkdir(parents=True)
    skill = materialise_skill(args.ref, out / "skill")
    scripts = pathlib.Path(skill["path"]) / "scripts"
    skill["replay"] = not args.live
    if not args.live:
        replay.install(scripts)
    uncached = [f for f in fixtures if args.live or not replay.is_cached(
        scripts, "fetch_transcript.py", [f["video"], f.get("lang", "")])]
    if uncached and youtube_blocked(uncached[0]["video"]):
        shutil.rmtree(out)
        sys.exit("YouTube is blocking transcript requests from this IP (IpBlocked). "
                 "Blocks usually lift within a few hours; rerun then.")
    inputs = "live inputs" if args.live else f"{len(fixtures) - len(uncached)}/{len(fixtures)} fixtures replayed"
    print(f"{run_id}: {len(fixtures)} fixture(s) × {args.runs} · skill {skill['version']} "
          f"({skill['sha']}, {skill['bytes']} B) · {args.agent} {args.model or '(default model)'} · {inputs}",
          flush=True)

    results = []
    try:
        for fixture in fixtures:
            for i in range(1, args.runs + 1):
                last = results[-1]["inputs"] if results else None
                if last and (last["live"] or not last["replayed"]):   # no pause after a fully replayed case
                    time.sleep(args.pause)
                r = run_case(fixture, i, args, skill, out)
                results.append(r)
                print_case(r)
    finally:
        if results and any(r["reports"] for r in results):
            subprocess.run([sys.executable, str(REPO_ROOT / "skills" / "video-lens-gallery" / "scripts" / "build_index.py"),
                            "--dir", str(LIBRARY)], capture_output=True)
        card = {"run_id": run_id, "agent": args.agent, "model": next((r["model"] for r in results if r["model"]), args.model),
                "arm": arm, "skill": skill, "started": run_id[:15], "cases": results}
        (out / "scorecard.json").write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")

    scored = [r for r in results if not r["blocked"]]
    passed = sum(not _failed(r) for r in scored)
    blocked = len(results) - len(scored)
    print(f"{passed}/{len(scored)} cases passed every gate"
          + (f" ({blocked} blocked by YouTube, rerun them)" if blocked else "") + f" → {out}")
    if passed < len(scored):
        return 1
    return 2 if blocked else 0


# ---------- compare ----------

def _load_card(path) -> dict:
    p = pathlib.Path(path)
    return json.loads((p / "scorecard.json" if p.is_dir() else p).read_text(encoding="utf-8"))


def _mean(values):
    nums = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
    bools = [v for v in values if isinstance(v, bool)]
    if bools and not nums:
        return sum(bools) / len(bools)
    return sum(nums) / len(nums) if nums else None


COMPARE_METRICS = ("kp_count", "kp_paragraph_share", "outline_count", "ts_mismatches",
                   "chapter_title_match", "summary_in_band", "takeaway_overlap", "tags_reused_share",
                   "render_attempts", "tool_calls", "wall_s", "cost_usd")


def compare(path_a, path_b) -> int:
    a, b = _load_card(path_a), _load_card(path_b)
    for tag, card in (("A", a), ("B", b)):
        inputs = "replayed inputs" if card["skill"].get("replay") else "live inputs"
        print(f"{tag} = {card['run_id']} (skill {card['skill']['version']}/{card['skill']['sha']}, {card['model']}, {inputs})")
    print()
    fixtures = list(dict.fromkeys([r["fixture"] for r in a["cases"] + b["cases"]]))
    regressions = []
    print("| fixture | gates A | gates B | " + " | ".join(COMPARE_METRICS) + " |")
    print("|---" * (3 + len(COMPARE_METRICS)) + "|")
    for fx in fixtures:
        ra = [r for r in a["cases"] if r["fixture"] == fx and not r.get("blocked")]
        rb = [r for r in b["cases"] if r["fixture"] == fx and not r.get("blocked")]
        def gate_rate(rs):
            return f"{sum(not _failed(r) for r in rs)}/{len(rs)}" if rs else "—"
        for gate in sorted({g for r in ra + rb for g in r["gates"]}):
            held_a = ra and all(r["gates"].get(gate) is not False for r in ra)
            broke_b = any(r["gates"].get(gate) is False for r in rb)
            if held_a and broke_b:
                regressions.append(f"{fx}: {gate}")
        cells = []
        for key in COMPARE_METRICS:
            ma, mb = _mean([r["metrics"].get(key) for r in ra]), _mean([r["metrics"].get(key) for r in rb])
            fmt = lambda v: "—" if v is None else (f"{v:.2f}".rstrip("0").rstrip(".") if v % 1 else f"{v:.0f}")
            cells.append(f"{fmt(ma)} → {fmt(mb)}")
        print(f"| {fx} | {gate_rate(ra)} | {gate_rate(rb)} | " + " | ".join(cells) + " |")
    print()
    if regressions:
        print("Gate regressions (held in every A run, failed in a B run):")
        for reg in regressions:
            print(f"  - {reg}")
        return 1
    print("No gate regressions.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--agent", choices=("claude", "pi"), default="claude")
    ap.add_argument("--model", help="passed through as --model (default: the CLI's own default)")
    ap.add_argument("--ref", help="git ref of the skill to test (default: the working tree)")
    ap.add_argument("--set", default="slim", choices=("slim", "full"))
    ap.add_argument("--only", help="comma-separated fixture names (overrides --set)")
    ap.add_argument("--runs", type=int, default=1, help="runs per fixture (2+ to see sampling noise)")
    ap.add_argument("--timeout", type=int, default=1800, help="seconds per case")
    ap.add_argument("--pause", type=int, default=20,
                    help="seconds between cases; bursts of transcript requests get the IP blocked")
    ap.add_argument("--live", action="store_true",
                    help="fetch transcripts and metadata from YouTube on every call instead of replaying evals/cache/")
    ap.add_argument("--agent-args", help="extra CLI flags for the agent, e.g. '--thinking medium'")
    ap.add_argument("--out", help="run directory (default: evals/results/<stamp>-<agent>-<arm>)")
    ap.add_argument("--compare", nargs=2, metavar=("RUN_A", "RUN_B"))
    args = ap.parse_args(argv)
    if args.compare:
        return compare(*args.compare)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
