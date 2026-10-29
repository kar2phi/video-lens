"""Fast tests for 025-R5: the renderer lints the payload once. The first render of a
payload that fails a check writes nothing and names each fix; the next render of the
same run only warns, so a run can never get stuck."""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "skills" / "video-lens" / "scripts" / "render_report.py"
VIDEO_ID = "bjdBVZa66oU"


def payload(**overrides):
    base = {
        "VIDEO_ID": VIDEO_ID, "VIDEO_TITLE": "What are skills?",
        "VIDEO_URL": f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "SUMMARY": "Skills package the instructions and scripts an agent needs for a task, "
                   "and load only when relevant.",
        "TAKEAWAY": "Write a repeated procedure down once instead of re-explaining it in every chat.",
        "KEY_POINTS": [{"point": f"Point {i}", "why": "Why it matters.", "detail": "Depth."} for i in range(3)],
        "OUTLINE": [{"t": 0, "title": "Intro"}, {"t": 65, "title": "How"}, {"t": 150, "title": "Uses"}],
        "DESCRIPTION_SECTION": "", "TAGS": ["ai", "agents", "tools"], "DURATION": "2 min",
    }
    base.update(overrides)
    return base


def render(tmp_path, data, *mode):
    run_dir = tmp_path / "payload-x"
    run_dir.mkdir(exist_ok=True)
    (run_dir / "payload.json").write_text(json.dumps(data), encoding="utf-8")
    mode = mode or ("--output-dir", str(tmp_path / "reports"))
    return subprocess.run([sys.executable, str(SCRIPT), "--payload-file", str(run_dir / "payload.json"), *mode],
                          capture_output=True, text=True, timeout=10,
                          env={**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"})


def reports(tmp_path):
    return sorted((tmp_path / "reports").glob("*.html")) if (tmp_path / "reports").exists() else []


def test_a_good_payload_renders_without_lint_output(tmp_path):
    r = render(tmp_path, payload())
    assert r.returncode == 0, r.stderr
    assert "RENDER_LINT" not in r.stderr and "RENDER_WARN" not in r.stderr
    assert len(reports(tmp_path)) == 1


BAD = dict(
    KEY_POINTS=[{"point": "Only", "why": "one"}, {"point": "Two", "why": "two"}],
    OUTLINE=[{"t": 0, "title": "a"}, {"t": 90, "title": "b"}, {"t": 60, "title": "c"}, {"t": 200, "title": "d"}],
    TAGS=["a", "b", "c", "d", "e", "f"],
    TAKEAWAY="Skills package the instructions and scripts an agent needs for a task, and load only when relevant.",
)


def test_the_first_render_stops_with_every_fix_and_writes_nothing(tmp_path):
    r = render(tmp_path, payload(**BAD))
    assert r.returncode == 1
    err = r.stderr
    assert err.startswith("ERROR:RENDER_LINT")
    for needle in ("KEY_POINTS has 2 items", "detail on 0 of 2", "OUTLINE[2].t is 60, after 90",
                   "OUTLINE[3].t is 200", "TAGS has 6", "TAKEAWAY repeats the SUMMARY"):
        assert needle in err, needle
    assert "the next render saves the report" in err
    assert reports(tmp_path) == []


def test_the_second_render_only_warns(tmp_path):
    assert render(tmp_path, payload(**BAD)).returncode == 1
    r = render(tmp_path, payload(**BAD))
    assert r.returncode == 0, r.stderr
    assert "RENDER_WARN: KEY_POINTS has 2 items" in r.stderr
    assert "OUTPUT_PATH:" in r.stdout and len(reports(tmp_path)) == 1


def test_a_fixed_retry_renders_cleanly(tmp_path):
    assert render(tmp_path, payload(TAGS=["a"])).returncode == 1
    r = render(tmp_path, payload())
    assert r.returncode == 0 and "RENDER_WARN" not in r.stderr


def test_each_check_on_its_own(tmp_path):
    cases = {
        "KEY_POINTS has 9 items": dict(KEY_POINTS=[{"point": f"P{i}", "why": "w", "detail": "d"} for i in range(9)]),
        "detail on 1 of 3": dict(KEY_POINTS=[{"point": "a", "why": "w", "detail": "d"},
                                             {"point": "b", "why": "w"}, {"point": "c", "why": "w"}]),
        "TAGS has 2": dict(TAGS=["a", "b"]),
        "OUTLINE[1].t is 0, after 0": dict(OUTLINE=[{"t": 0, "title": "a"}, {"t": 0, "title": "b"}]),
    }
    for needle, overrides in cases.items():
        sub = tmp_path / needle.split()[0].lower().replace("[", "").replace("]", "")
        sub.mkdir(exist_ok=True)
        r = render(sub, payload(**overrides))
        assert r.returncode == 1 and needle in r.stderr, (needle, r.stderr)


def test_the_duration_check_allows_the_rest_of_the_last_minute(tmp_path):
    # "2 min" is floored by the fetchers: the video may run to 2:59.
    assert render(tmp_path, payload(OUTLINE=[{"t": 0, "title": "a"}, {"t": 179, "title": "b"}])).returncode == 0
    (tmp_path / "long").mkdir()
    r = render(tmp_path / "long", payload(DURATION="1h 2m", OUTLINE=[{"t": 0, "title": "a"}, {"t": 3800, "title": "b"}]))
    assert r.returncode == 1 and "beyond the video's 1h 2m" in r.stderr
    (tmp_path / "unknown").mkdir()
    r = render(tmp_path / "unknown", payload(DURATION="", OUTLINE=[{"t": 0, "title": "a"}, {"t": 99999, "title": "b"}]))
    assert r.returncode == 0, r.stderr


def test_html_string_payloads_are_linted_too(tmp_path):
    kps = "".join(f"<li><strong>P{i}</strong> — w<p>d</p></li>" for i in range(3))
    assert render(tmp_path, payload(KEY_POINTS=kps)).returncode == 0
    (tmp_path / "one").mkdir()
    r = render(tmp_path / "one", payload(KEY_POINTS="<li><strong>P</strong> — w</li>"))
    assert r.returncode == 1 and "KEY_POINTS has 1 item" in r.stderr


def test_a_revision_is_linted_like_a_first_render(tmp_path):
    assert render(tmp_path, payload()).returncode == 0
    target = reports(tmp_path)[0]
    r = render(tmp_path, payload(TAGS=["x"]), "--replace", str(target))
    assert r.returncode == 1 and "TAGS has 1" in r.stderr
    r = render(tmp_path, payload(TAGS=["x"]), "--replace", str(target))
    assert r.returncode == 0 and "RENDER_WARN: TAGS has 1" in r.stderr


def test_stdin_and_the_legacy_path_are_never_blocked(tmp_path):
    bad = json.dumps(payload(**BAD))
    env = {**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"}
    r = subprocess.run([sys.executable, str(SCRIPT), "--output-dir", str(tmp_path / "reports")],
                       input=bad, capture_output=True, text=True, timeout=10, env=env)
    assert r.returncode == 0 and "RENDER_WARN:" in r.stderr
    r = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "legacy.html")],
                       input=bad, capture_output=True, text=True, timeout=10, env=env)
    assert r.returncode == 0 and "RENDER_LINT" not in r.stderr and "RENDER_WARN" not in r.stderr


def test_any_earlier_rejection_uses_up_the_one_stop(tmp_path):
    """SKILL.md allows one retry: a run rejected for another reason must not then be
    stopped by the lint as well."""
    r = render(tmp_path, payload(KEY_POINTS=[{"point": "P", "paragraph": "misnamed"}]))
    assert r.returncode == 1 and "RENDER_INVALID_ITEM" in r.stderr
    r = render(tmp_path, payload(TAGS=["x"]))
    assert r.returncode == 0 and "RENDER_WARN: TAGS has 1" in r.stderr
    (tmp_path / "json").mkdir()
    bad_json = tmp_path / "json" / "payload-x"
    bad_json.mkdir()
    (bad_json / "payload.json").write_text("{not json", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), "--payload-file", str(bad_json / "payload.json"),
                        "--output-dir", str(tmp_path / "json" / "reports")], capture_output=True, text=True)
    assert r.returncode == 1 and (bad_json / ".render-lint").exists()
