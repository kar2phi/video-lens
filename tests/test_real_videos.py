"""Real-video tier: the fetch scripts against live YouTube, one case per fixture. No LLM.

Run with: task test-real   (pytest -m network). Fixtures live in evals/fixtures.json;
a fixture with `known_bug` is a strict xfail, so fixing the bug fails the test until the
marker is removed.
"""
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "skills" / "video-lens" / "scripts"
FIXTURES = json.loads((REPO_ROOT / "evals" / "fixtures.json").read_text(encoding="utf-8"))["fixtures"]

sys.path.insert(0, str(REPO_ROOT / "evals"))
import checks  # noqa: E402

pytestmark = pytest.mark.network

_metadata = {}


def _script(name, *args, timeout=90, env=None):
    return subprocess.run([sys.executable, str(SCRIPT_DIR / name), "--", *args],
                          capture_output=True, text=True, timeout=timeout, env=env)


def _headers(stdout):
    return dict(l.split(": ", 1) for l in stdout.splitlines()
                if re.match(r"^[A-Z_]+: ", l))


def metadata(video):
    if video not in _metadata:
        r = _script("fetch_metadata.py", video)
        assert not r.stdout.startswith("ERROR:"), r.stdout[:300]
        h = _headers(r.stdout)
        h["chapters"] = json.loads(h.get("YTDLP_CHAPTERS", "[]"))
        _metadata[video] = h
    return _metadata[video]


def _fixture_params():
    for fx in FIXTURES:
        if "fetch" in fx["sets"]:
            marks = [pytest.mark.xfail(reason=fx["known_bug"], strict=True)] if fx.get("known_bug") else []
            yield pytest.param(fx, id=fx["name"], marks=marks)


@pytest.mark.parametrize("fx", list(_fixture_params()))
def test_fetch_matches_fixture(fx, tmp_path):
    expect, video, lang = fx["expect"], fx["video"], fx.get("lang", "")

    # XDG_CACHE_HOME keeps preflight's payload dir out of the real cache.
    pre = _script("preflight.py", f"https://www.youtube.com/watch?v={video} {lang}".strip(),
                  env={**os.environ, "XDG_CACHE_HOME": str(tmp_path)})
    assert pre.returncode == 0, pre.stderr
    assert _headers(pre.stdout)["VIDEO_ID"] == video
    assert _headers(pre.stdout).get("LANG_CODE", "") == lang

    tr = _script("fetch_transcript.py", video, *([lang] if lang else []))
    if "error" in expect:
        assert tr.returncode != 0
        assert tr.stdout.startswith(f"ERROR:{expect['error']}"), tr.stdout[:300]
        return
    assert tr.returncode == 0, (tr.stdout + tr.stderr)[:500]
    h = _headers(tr.stdout)
    assert h["LANG"] == expect["lang"]
    assert ("LANG_WARN:" in tr.stdout) == bool(expect.get("lang_warn"))
    assert h["TITLE"] and not h["TITLE"].startswith("YouTube video ")

    times = [checks.ts_to_seconds(t) for t in re.findall(r"^\[([\d:]+)\]", tr.stdout, re.M)]
    assert len(times) >= 20
    assert times == sorted(times), "transcript timestamps go backwards"

    md = metadata(video)
    if "chapters" in expect:
        assert len(md["chapters"]) == expect["chapters"]
    duration = ground_duration(md)
    # A transcript that stops early would let the agent summarise half a video unknowingly.
    assert times[-1] >= 0.85 * duration, f"transcript ends at {times[-1]}s of {duration}s"


def ground_duration(md):
    """YTDLP_DURATION is formatted ('12 min', '1h 36m'); the last chapter bounds it from below."""
    m = re.fullmatch(r"(?:(\d+)h (\d+)m|(\d+) min)", md["YTDLP_DURATION"])
    minutes = int(m.group(1)) * 60 + int(m.group(2)) if m.group(1) else int(m.group(3))
    return minutes * 60


def test_real_data_renders_a_report_the_checks_accept(tmp_path):
    """Smoke fixture end to end without an agent: real title, chapters and description
    in, a rendered report out, and the eval gates agree it is well-formed. Keeps the
    checker honest against the renderer's actual markup."""
    fx = next(f for f in FIXTURES if f["name"] == "smoke")
    video, md = fx["video"], metadata(fx["video"])

    def ts(s):
        return f"{s // 60}:{s % 60:02d}"
    outline = "".join(
        f'<li><a class="ts" data-t="{int(c["start_time"])}" '
        f'href="https://www.youtube.com/watch?v={video}&t={int(c["start_time"])}" target="_blank" '
        f'rel="noopener noreferrer">▶ {ts(int(c["start_time"]))}</a> — '
        f'<span class="outline-title">{html.escape(c["title"])}</span><span class="outline-detail">Detail.</span></li>'
        for c in md["chapters"])
    payload = {
        "VIDEO_ID": video, "VIDEO_TITLE": md["YTDLP_TITLE"],
        "VIDEO_URL": f"https://www.youtube.com/watch?v={video}",
        "SUMMARY": "Skills package the instructions and scripts an agent needs for a task. "
                   "The video explains how they load only when relevant.",
        "TAKEAWAY": "Write the procedure down once as a skill instead of re-explaining it in every chat.",
        "KEY_POINTS": "".join(f"<li><strong>Point {i}</strong> — why it matters.<p>Depth for point {i}.</p></li>"
                              for i in range(1, 4)),
        "OUTLINE": outline,
        "DESCRIPTION_SECTION": (f'<details class="description-details"><summary>YouTube Description</summary>'
                                f'<div class="video-description">{md["YTDLP_DESC_HTML"]}</div></details>'),
        "TAGS": ["ai", "agents", "tools"], "CHANNEL": md["YTDLP_CHANNEL"],
        "DURATION": md["YTDLP_DURATION"], "PUBLISH_DATE": md["YTDLP_PUBLISHED"], "VIEWS": md["YTDLP_VIEWS"],
    }
    payload_path = tmp_path / "payload.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT_DIR / "render_report.py"), "--payload-file", str(payload_path),
                        "--output-dir", str(tmp_path / "reports")], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    report = checks.parse_report(Path(r.stdout.split("OUTPUT_PATH: ", 1)[1].strip()).read_text(encoding="utf-8"))

    gates = checks.gates(fx, None, report, 1, chapters=md["chapters"])
    assert {k: v for k, v in gates.items() if k != "language"} == {
        "report_written": True, "structure": True, "outline_links_own_video": True, "chapters_anchored": True}
    m = checks.report_metrics(report, ground_duration(md), md["chapters"])
    assert m["ts_mismatches"] == 0
    assert m["chapter_title_match"] == 1.0
    assert report["title"] == md["YTDLP_TITLE"]
