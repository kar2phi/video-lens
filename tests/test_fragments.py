"""037 A4: the fragments the local report and the share page share (035 §4.5, 036 §6 F1–F3)
and keyPoints[].t (D7).

viewer/fragments.json is the contract with the Worker (video-lens-core service/src/render.ts,
page.ts): payload v1 in, exact bytes out. tools/build_viewer.py --vectors writes it from the
Python renderer; the Worker's tests assert the same bytes.
"""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "skills" / "video-lens" / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import render_report as rr  # noqa: E402
from fake_share_service import validate_payload  # noqa: E402

BUILD = ROOT / "tools" / "build_viewer.py"
_spec = importlib.util.spec_from_file_location("build_viewer", BUILD)
bv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bv)

VECTORS = ROOT / "viewer" / "fragments.json"
CASES = json.loads(VECTORS.read_text(encoding="utf-8"))
GOLDEN = ROOT / "tests" / "golden"
VIDEO_ID = "bjdBVZa66oU"


@pytest.fixture(autouse=True)
def no_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "METADATA_DIR", tmp_path / "metadata")


# ── the vectors ──

def test_committed_vectors_are_what_the_renderer_writes():
    assert VECTORS.read_text(encoding="utf-8") == bv.build_vectors(ROOT), \
        "viewer/fragments.json is stale: run python3 tools/build_viewer.py --vectors"


def test_check_fails_on_stale_vectors(tmp_path):
    shutil.copytree(ROOT / "viewer", tmp_path / "viewer")
    (tmp_path / "skills" / "video-lens").mkdir(parents=True)
    shutil.copy(ROOT / "skills" / "video-lens" / "template.html", tmp_path / "skills" / "video-lens")
    run = lambda *a: subprocess.run([sys.executable, str(BUILD), *a, "--root", str(tmp_path)],  # noqa: E731
                                    capture_output=True, text=True)
    assert run("--check").returncode == 0
    vec = tmp_path / "viewer" / "fragments.json"
    vec.write_text(vec.read_text().replace("<p>Summary.</p>", "<p>Summary!</p>", 1))
    r = run("--check")
    assert r.returncode == 1 and "fragments.json" in r.stderr
    assert run("--vectors").returncode == 0 and run("--check").returncode == 0


def test_vectors_cover_the_035_list():
    names = [c["name"] for c in CASES]
    for name in ("golden payload", "bold holding a star", "quotes and ampersands", "empty why and detail",
                 "empty outline", "t over one hour", "6000 stars", "key point t present and absent"):
        assert name in names
    assert all(set(c["expect"]) == {"outline", "keyPoints", "summary", "takeaway"} for c in CASES)
    timed = [k for c in CASES for k in c["payload"]["keyPoints"] if "t" in k]
    assert timed and any("t" not in k for c in CASES for k in c["payload"]["keyPoints"])


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_each_payload_is_valid_and_already_normalised(case):
    """The Worker renders the validated payload; a vector's payload is that form already."""
    assert validate_payload(case["payload"]) == case["payload"]
    assert list(case["payload"]) == list(bv.VECTOR_BASE)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_the_sanitiser_keeps_the_fragments_as_they_are(case):
    """Fragments still pass through the allowlist sanitiser (defence in depth); it must not
    change a byte, F3's time link in KEY_POINTS included."""
    vid = case["payload"]["videoId"]
    assert rr.sanitise_html("KEY_POINTS", case["expect"]["keyPoints"], vid) == case["expect"]["keyPoints"]
    assert rr.sanitise_html("OUTLINE", case["expect"]["outline"], vid) == case["expect"]["outline"]


def test_the_golden_report_holds_the_golden_fragments():
    golden = next(c for c in CASES if c["name"] == "golden payload")
    html = (GOLDEN / "share_report.html").read_text(encoding="utf-8")
    for key, fragment in golden["expect"].items():
        assert fragment in html, key


def test_a_report_shows_the_fragments_of_its_own_data_block(tmp_path):
    """The local report and the share page of its uploaded payload carry the same fragments."""
    payload = json.loads((GOLDEN / "share_payload.json").read_text(encoding="utf-8"))
    clean = rr.sanitise_payload(payload, str(tmp_path / "r.html"))
    data = json.loads(re.search(r'id="video-lens-data">(.*?)</script>', clean["VIDEO_LENS_DATA"]).group(1)
                      .replace("<\\/", "</"))
    expect = rr.fragments(data)
    assert {"outline": clean["OUTLINE"], "keyPoints": clean["KEY_POINTS"],
            "summary": clean["SUMMARY"], "takeaway": clean["TAKEAWAY"]} == expect


# ── the grammar (service/src/render.ts) ──

def test_esc_uses_the_workers_five_entities():
    assert rr.esc("& < > \" '") == "&amp; &lt; &gt; &quot; &#39;"


@pytest.mark.parametrize("text,html", [
    ("**a*b**", "*<em>a</em>b**"),
    ("x ** y ** z", "x ** y ** z"),
    ("2 * 3 * 4", "2 * 3 * 4"),
    ("`**x**` **y**", "<code>**x**</code> <strong>y</strong>"),
    ("**a\nb**", "**a\nb**"),
    ("*\ufeffx*", "*\ufeffx*"),          # U+FEFF is JavaScript whitespace, not Python's
    ("*x\x1c*", "<em>x\x1c</em>"),       # U+001C is Python whitespace, not JavaScript's
    ("*" * 6000, "*" * 6000),
])
def test_inline_markers(text, html):
    assert rr.inline(text) == html


def test_paragraphs_split_on_blank_lines_and_trim_javascript_whitespace():
    assert rr.paragraphs("\ufeffa\nb\n\n\n c \n\n") == "<p>a<br>b</p>\n<p>c</p>"
    assert rr.paragraphs("\x1ca") == "<p>\x1ca</p>"


# ── keyPoints[].t (D7) in the renderer ──

def _payload(**overrides):
    base = {
        "VIDEO_ID": VIDEO_ID, "VIDEO_TITLE": "T", "VIDEO_URL": f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "SUMMARY": "S.", "TAKEAWAY": "K.", "DESCRIPTION_SECTION": "",
        "KEY_POINTS": [{"point": "P", "why": "W", "t": 65}, {"point": "Q", "t": "1:05"}],
        "OUTLINE": [{"t": 0, "title": "Intro"}, {"t": "1:05", "title": "Middle"}],
    }
    base.update(overrides)
    return base


def _data(clean):
    return json.loads(re.search(r'id="video-lens-data">(.*?)</script>', clean["VIDEO_LENS_DATA"]).group(1))


def test_a_key_point_t_naming_an_outline_entry_is_kept_first(tmp_path, capsys):
    clean = rr.sanitise_payload(_payload(), str(tmp_path / "r.html"))
    points = _data(clean)["keyPoints"]
    assert points == [{"t": 65, "point": "P", "why": "W", "detail": ""},
                      {"t": 65, "point": "Q", "why": "", "detail": ""}]
    assert clean["KEY_POINTS"].count('<a class="ts" data-t="65"') == 2
    assert "RENDER_WARN" not in capsys.readouterr().err


@pytest.mark.parametrize("t", [5, "soon", True, -1, 64.0])
def test_a_key_point_t_naming_no_outline_entry_is_dropped_with_a_warning(tmp_path, capsys, t):
    clean = rr.sanitise_payload(_payload(KEY_POINTS=[{"point": "P", "t": t}]), str(tmp_path / "r.html"))
    assert _data(clean)["keyPoints"] == [{"point": "P", "why": "", "detail": ""}]
    assert "<a " not in clean["KEY_POINTS"]
    assert "RENDER_WARN: KEY_POINTS[0].t" in capsys.readouterr().err


def test_an_empty_key_point_t_is_no_t(tmp_path, capsys):
    clean = rr.sanitise_payload(_payload(KEY_POINTS=[{"point": "P", "t": None}, {"point": "Q", "t": ""}]),
                                str(tmp_path / "r.html"))
    assert all("t" not in k for k in _data(clean)["keyPoints"])
    assert capsys.readouterr().err == ""


def test_a_key_point_t_against_an_html_string_outline(tmp_path):
    outline = (f'<li><a class="ts" data-t="65" href="https://www.youtube.com/watch?v={VIDEO_ID}&t=65s">1:05</a> '
               '<span class="outline-title">Middle</span></li>')
    clean = rr.sanitise_payload(_payload(OUTLINE=outline, KEY_POINTS=[{"point": "P", "t": 65}]),
                                str(tmp_path / "r.html"))
    assert 'data-t="65"' in clean["KEY_POINTS"] and clean["VIDEO_LENS_DATA"] == ""


def test_the_cli_renders_and_warns_when_t_is_dropped(tmp_path):
    run_dir = tmp_path / "payload-x"
    run_dir.mkdir()
    payload = _payload(KEY_POINTS=[{"point": f"P{i}", "why": "w", "detail": "d", "t": 7} for i in range(3)],
                       TAGS=["a", "b", "c"])
    (run_dir / "payload.json").write_text(json.dumps(payload), encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "skills" / "video-lens" / "scripts" / "render_report.py"),
                        "--payload-file", str(run_dir / "payload.json"), "--output-dir", str(tmp_path / "out")],
                       capture_output=True, text=True, timeout=10,
                       env={"VIDEO_LENS_ALLOW_ANY_PATH": "1", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"})
    assert r.returncode == 0, r.stderr
    assert r.stderr.count("RENDER_WARN: KEY_POINTS[") == 3 and "OUTPUT_PATH:" in r.stdout


def test_key_points_html_may_hold_a_time_link_to_its_own_video_only(tmp_path):
    own = (f'<li><strong>P</strong> <a class="ts" data-t="65" '
           f'href="https://www.youtube.com/watch?v={VIDEO_ID}&amp;t=65s">1:05</a></li>')
    clean = rr.sanitise_payload(_payload(KEY_POINTS=own), str(tmp_path / "r.html"))
    assert 'target="_blank" rel="noopener noreferrer">1:05</a>' in clean["KEY_POINTS"]
    for bad in (own.replace(VIDEO_ID, "AAAAAAAAAAA"), own.replace('class="ts"', 'class="x"'),
                own.replace("https://www.youtube.com", "https://evil.example")):
        with pytest.raises(rr.RenderValidationError) as exc:
            rr.sanitise_payload(_payload(KEY_POINTS=bad), str(tmp_path / "r.html"))
        assert exc.value.code == "RENDER_DISALLOWED_HTML"


def test_skill_md_asks_for_the_optional_t():
    skill = (ROOT / "skills" / "video-lens" / "SKILL.md").read_text(encoding="utf-8")
    assert "**t** *(optional)* — the start time of the Outline section" in skill
