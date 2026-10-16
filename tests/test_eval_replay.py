"""Fast tests for evals/replay.py: the eval must replay real fetches faithfully, and never
pin a transient failure (an IP block) into the cache."""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "evals"))
import replay  # noqa: E402

# Stands in for fetch_transcript.py: counts its live runs, and the output depends on argv.
FAKE = '''import pathlib, sys
runs = pathlib.Path(sys.argv[0]).with_name("runs")
runs.write_text(str(int(runs.read_text()) + 1) if runs.exists() else "1")
video = [a for a in sys.argv[1:] if a not in ("--", "")][0]
if video == "blocked":
    print("ERROR:TRANSCRIPT_FETCH_FAILED IpBlocked: too many requests"); sys.exit(1)
if video == "nocaps":
    print("ERROR:CAPTIONS_DISABLED: none"); sys.exit(1)
print("TITLE: T\\nDATE: 2001-01-01\\nLANG: de\\n[0:00] hallo " + " ".join(sys.argv[1:]))
'''


def setup(tmp_path):
    scripts = tmp_path / "skill" / "scripts"
    scripts.mkdir(parents=True)
    for name in replay.NETWORK_SCRIPTS:
        (scripts / name).write_text(FAKE, encoding="utf-8")
    cache = tmp_path / "cache"
    replay.install(scripts, cache)
    return scripts, cache


def call(scripts, *args, log=None):
    env = {**os.environ, **({replay.LOG_ENV: str(log)} if log else {})}
    return subprocess.run([sys.executable, str(scripts / "fetch_transcript.py"), *args],
                          capture_output=True, text=True, env=env)


def live_runs(scripts):
    return int((scripts / ".live" / "runs").read_text())


def test_replays_the_recorded_output_and_logs_it(tmp_path):
    scripts, cache = setup(tmp_path)
    log = tmp_path / "replay.jsonl"
    first = call(scripts, "--", "vid", "", log=log)
    assert first.returncode == 0 and "hallo" in first.stdout
    again = call(scripts, "--", "vid", log=log)            # "" and no "" are the same call
    assert live_runs(scripts) == 1
    def undated(out):
        return [l for l in out.splitlines() if not l.startswith("DATE:")]
    assert undated(again.stdout) == undated(first.stdout) and again.stderr == first.stderr
    assert "DATE: 2001-01-01" not in again.stdout          # the fetch date is today's, not the recording's
    assert [json.loads(l)["replayed"] for l in log.read_text().splitlines()] == [False, True]
    assert replay.is_cached(scripts, "fetch_transcript.py", ["vid", ""], cache)

    call(scripts, "--", "vid", "de")                        # other arguments are another recording
    assert live_runs(scripts) == 2
    # A changed fetcher (another A/B arm) must not be served this one's output.
    live = scripts / ".live" / "fetch_transcript.py"
    live.write_text(live.read_text() + "\n# changed\n")
    call(scripts, "--", "vid")
    assert live_runs(scripts) == 3


def test_blocks_are_never_recorded_but_per_video_errors_are(tmp_path):
    scripts, _ = setup(tmp_path)
    for _ in range(2):
        r = call(scripts, "--", "blocked")
        assert r.returncode == 1 and "IpBlocked" in r.stdout
    assert live_runs(scripts) == 2
    for _ in range(2):
        r = call(scripts, "--", "nocaps")
        assert r.returncode == 1 and r.stdout.startswith("ERROR:CAPTIONS_DISABLED")
    assert live_runs(scripts) == 3
