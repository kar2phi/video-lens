"""Record/replay for the skill's network scripts during an eval.

run_eval.py swaps fetch_transcript.py and fetch_metadata.py in its copy of the skill for a
three-line shim that calls main() here. The first call for a given script and argument list
runs the real script (moved to scripts/.live/) and records its output in evals/cache/; later
calls replay it. The key includes the script's hash, so an arm that changes the fetcher
records its own inputs, and arms with the same fetcher see byte-identical transcripts.

Only outputs that will not change on retry are recorded: successes and the per-video errors
below. Blocks, timeouts and network errors always run live.
"""
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

CACHE_DIR = pathlib.Path(__file__).resolve().parent / "cache"
NETWORK_SCRIPTS = ("fetch_transcript.py", "fetch_metadata.py")
STABLE_ERRORS = re.compile(r"^ERROR:(CAPTIONS_DISABLED|NO_TRANSCRIPT|VIDEO_UNAVAILABLE|AGE_RESTRICTED|INVALID_VIDEO_ID)\b", re.M)
LOG_ENV = "VIDEO_LENS_REPLAY_LOG"

SHIM = '''#!/usr/bin/env python3
"""Eval replay shim for {name} (evals/replay.py). Not part of the skill."""
import sys
sys.path.insert(0, {evals!r})
import replay
sys.exit(replay.main({name!r}, {live!r}, {cache!r}))
'''


def cache_path(cache_dir, live_script, argv) -> pathlib.Path:
    script = pathlib.Path(live_script)
    sha = hashlib.sha256(script.read_bytes()).hexdigest()[:12]
    args = "_".join(re.sub(r"[^A-Za-z0-9_-]+", "-", a) for a in argv if a not in ("--", "")) or "noargs"
    return pathlib.Path(cache_dir) / f"{script.stem}.{sha}.{args}.json"


def install(scripts_dir: pathlib.Path, cache_dir=CACHE_DIR):
    """Replace the network scripts in a skill copy with replay shims."""
    live_dir = scripts_dir / ".live"
    live_dir.mkdir()
    for name in NETWORK_SCRIPTS:
        live = live_dir / name
        (scripts_dir / name).rename(live)
        (scripts_dir / name).write_text(SHIM.format(
            name=name, evals=str(pathlib.Path(__file__).resolve().parent),
            live=str(live), cache=str(cache_dir)), encoding="utf-8")


def is_cached(scripts_dir: pathlib.Path, name, argv, cache_dir=CACHE_DIR) -> bool:
    live = scripts_dir / ".live" / name
    return live.exists() and cache_path(cache_dir, live, argv).exists()


def main(name, live, cache_dir) -> int:
    argv = sys.argv[1:]
    path = cache_path(cache_dir, live, argv)
    hit = path.exists()
    if hit:
        rec = json.loads(path.read_text(encoding="utf-8"))
        # The transcript's DATE: header is the fetch date, which the report shows.
        stdout = re.sub(r"^DATE: \d{4}-\d{2}-\d{2}$", f"DATE: {datetime.date.today().isoformat()}",
                        rec["stdout"], count=1, flags=re.M)
        stderr, code = rec["stderr"], rec["returncode"]
    else:
        r = subprocess.run([sys.executable, live, *argv], capture_output=True, text=True)
        stdout, stderr, code = r.stdout, r.stderr, r.returncode
        if code == 0 or STABLE_ERRORS.search(stdout):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"argv": argv, "stdout": stdout, "stderr": stderr, "returncode": code,
                                        "recorded": datetime.datetime.now().isoformat(timespec="seconds")},
                                       ensure_ascii=False), encoding="utf-8")
    log = os.environ.get(LOG_ENV)
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"script": name, "argv": argv, "replayed": hit}) + "\n")
    sys.stdout.write(stdout)
    sys.stderr.write(stderr)
    return code
