"""Single end-to-end test — replaces all existing tests.
Runs the full pipeline: transcript → metadata → render → serve.
Run with: pytest tests/test_e2e.py -v
"""
import html as html_lib
import json, os, pathlib, re, shutil, subprocess, sys, time, urllib.request
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT         = Path(__file__).resolve().parent.parent
SCRIPT_DIR        = REPO_ROOT / "skills" / "video-lens" / "scripts"
GALLERY_SCRIPT_DIR = REPO_ROOT / "skills" / "video-lens-gallery" / "scripts"
TEMPLATE          = REPO_ROOT / "skills" / "video-lens" / "template.html"

sys.path.insert(0, str(SCRIPT_DIR))
from render_report import (
    RenderValidationError,
    _render_clean,
    render_from_payload,
    sanitise_payload,
)
import render_report  # for monkeypatching time.time

# "What are skills?" (2 min, 496K views) — short, stable, good for quick pipeline validation
VIDEO_ID = "bjdBVZa66oU"


SAMPLE_META = json.dumps({
    "videoId": "TEST_VIDEO_ID",
    "title": "Test Title",
    "channel": "Test Channel",
    "duration": "10 min",
    "publishDate": "Jan 01 2025",
    "generationDate": "2025-01-01",
    "summary": "Test summary.",
    "tags": ["test"],
    "keywords": ["Point"],
    "filename": "2025-01-01-000000-video-lens_test.html",
})


def sample_render_payload(**overrides):
    payload = {
        "VIDEO_ID": VIDEO_ID,
        "VIDEO_TITLE": "Test Video Title",
        "VIDEO_URL": f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "META_LINE": "Test Channel · 10 min · Jan 01 2025 · 1.0M views",
        "SUMMARY": "E2E test summary.",
        "TAKEAWAY": "E2E test takeaway.",
        "KEY_POINTS": "<li><strong>Point</strong> — detail<p>More &ldquo;text&rdquo;.</p></li>",
        "OUTLINE": (
            f'<li><a class="ts" data-t="123" href="https://www.youtube.com/watch?v={VIDEO_ID}&t=123" '
            'target="_blank" rel="noopener noreferrer">▶ 2:03</a> — '
            '<span class="outline-title">Intro</span>'
            '<span class="outline-detail">Opening.</span></li>'
        ),
        "DESCRIPTION_SECTION": (
            '<details class="description-details"><summary>YouTube Description</summary>'
            '<div class="video-description">More links: '
            '<a href="https://example.com/path?q=1" target="_blank" rel="noopener">example</a>'
            '<br>Done.</div></details>'
        ),
        "VIDEO_LENS_META": SAMPLE_META,
    }
    payload.update(overrides)
    return payload


def new_shape_payload(**overrides):
    """Payload using the renderer-owns-meta shape (no VIDEO_LENS_META JSON blob)."""
    payload = {
        "VIDEO_ID": VIDEO_ID,
        "VIDEO_TITLE": "Test Video Title",
        "VIDEO_URL": f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "META_LINE": "Test Channel · 10 min · Jan 01 2025 · 1.0M views",
        "SUMMARY": "E2E test summary.",
        "TAKEAWAY": "E2E test takeaway.",
        "KEY_POINTS": "<li><strong>Point</strong> — detail<p>More &ldquo;text&rdquo;.</p></li>",
        "OUTLINE": (
            f'<li><a class="ts" data-t="123" href="https://www.youtube.com/watch?v={VIDEO_ID}&t=123" '
            'target="_blank" rel="noopener noreferrer">▶ 2:03</a> — '
            '<span class="outline-title">Intro</span>'
            '<span class="outline-detail">Opening.</span></li>'
        ),
        "DESCRIPTION_SECTION": "",
        "TAGS": ["test", "demo"],
        "CHANNEL": "Test Channel",
        "DURATION": "10 min",
        "PUBLISH_DATE": "Jan 01 2025",
        "VIEWS": "1.0M views",
        "GENERATION_DATE": "2025-01-01",
        "GENERATION_DURATION_SECONDS": 42,
        "AGENT_MODEL": "claude-opus-4-7",
    }
    payload.update(overrides)
    return payload


def assert_render_validation(code, payload):
    with pytest.raises(RenderValidationError) as exc:
        sanitise_payload(payload)
    assert exc.value.code == code
    return exc.value.detail


def test_template_placeholders(tmp_path):
    """Fast, no-network check: all 10 keys replaced, no {{...}} remain."""
    out = tmp_path / "report.html"
    _render_clean({
        "VIDEO_ID":            "TEST_VIDEO_ID",
        "VIDEO_TITLE":         "TEST_VIDEO_TITLE",
        "VIDEO_URL":           "TEST_VIDEO_URL",
        "META_LINE":           "TEST_META_LINE",
        "SUMMARY":             "TEST_SUMMARY",
        "TAKEAWAY":            "TEST_TAKEAWAY",
        "KEY_POINTS":          "TEST_KEY_POINTS",
        "OUTLINE":             "TEST_OUTLINE",
        "DESCRIPTION_SECTION": "TEST_DESCRIPTION_SECTION",
        "VIDEO_LENS_META":     SAMPLE_META,
    }, str(out), template_path=TEMPLATE)
    html = out.read_text(encoding="utf-8")
    assert "{{" not in html, "Unreplaced placeholders found in rendered HTML"
    assert 'id="video-lens-meta"' in html


def test_render_empty_content_fails(tmp_path):
    """Empty SUMMARY must produce a typed ERROR exit, not a silent rendered file."""
    out = tmp_path / "report.html"
    payload = json.dumps({
        "VIDEO_ID": "x", "VIDEO_TITLE": "x", "VIDEO_URL": "x",
        "META_LINE": "", "SUMMARY": "",
        "KEY_POINTS": "<li>x</li>", "TAKEAWAY": "x",
        "OUTLINE": "<li>x</li>", "DESCRIPTION_SECTION": "",
        "VIDEO_LENS_META": SAMPLE_META,
    })
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"), str(out)],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 1
    assert "ERROR:RENDER_PAYLOAD_INVALID" in r.stderr
    assert "empty_keys=" in r.stderr
    assert not out.exists(), "Report file must NOT be written when content is empty"


def test_sanitise_payload_escapes_script_in_summary(tmp_path):
    out = tmp_path / "report.html"
    payload = sample_render_payload(SUMMARY="<script>alert(1)</script> & keep")
    render_from_payload(payload, str(out), template_path=TEMPLATE)
    html = out.read_text(encoding="utf-8")
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; keep" in html
    assert "<script>alert(1)</script>" not in html


def test_sanitise_payload_rejects_javascript_url_in_outline():
    detail = assert_render_validation(
        "RENDER_DISALLOWED_HTML",
        sample_render_payload(OUTLINE='<li><a href="javascript:alert(1)">x</a></li>'),
    )
    assert "key=OUTLINE" in detail


def test_sanitise_payload_rejects_disallowed_tag_in_key_points():
    detail = assert_render_validation(
        "RENDER_DISALLOWED_HTML",
        sample_render_payload(KEY_POINTS="<li><iframe src='evil'></iframe>x</li>"),
    )
    assert "key=KEY_POINTS" in detail


def test_sanitise_payload_rejects_list_valued_key_points():
    detail = assert_render_validation(
        "RENDER_INVALID_TYPE",
        sample_render_payload(KEY_POINTS=["<li>a</li>", "<li>b</li>"]),
    )
    assert "key=KEY_POINTS" in detail
    assert "got list" in detail


def test_sanitise_payload_rejects_event_handler():
    detail = assert_render_validation(
        "RENDER_DISALLOWED_HTML",
        sample_render_payload(KEY_POINTS='<li onclick="x">y</li>'),
    )
    assert "event handler onclick" in detail


def test_sanitise_payload_rejects_invalid_video_id():
    assert_render_validation(
        "RENDER_INVALID_VIDEO_ID",
        sample_render_payload(VIDEO_ID="abc<x>"),
    )


def test_sanitise_payload_rejects_invalid_video_url():
    assert_render_validation(
        "RENDER_INVALID_VIDEO_URL",
        sample_render_payload(VIDEO_URL="https://evil.example/"),
    )


def test_render_accepts_payload_without_meta_line(tmp_path):
    """META_LINE is optional — renderer composes it from CHANNEL/DURATION/PUBLISH_DATE/VIEWS."""
    out = tmp_path / "report.html"
    payload = new_shape_payload()
    del payload["META_LINE"]
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"), str(out)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=10,
        env={**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"},
    )
    assert r.returncode == 0, f"render failed: {r.stderr}"
    html = out.read_text(encoding="utf-8")
    assert "Test Channel · 10 min · Jan 01 2025 · 1.0M views" in html


def test_render_payload_file_argument(tmp_path):
    """--payload-file reads JSON from a file (used when quotes would mangle a heredoc)."""
    out = tmp_path / "report.html"
    payload_file = tmp_path / "payload.json"
    payload = sample_render_payload(
        KEY_POINTS='<li><strong>Quote</strong> — said <em>"failures are rare"</em></li>'
    )
    payload_file.write_text(json.dumps(payload), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"),
         str(out), "--payload-file", str(payload_file)],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"},
    )
    assert r.returncode == 0, f"render failed: {r.stderr}"
    html = out.read_text(encoding="utf-8")
    assert "&#x27;failures are rare&#x27;" in html or "failures are rare" in html


def test_render_payload_file_missing(tmp_path):
    """Missing --payload-file path emits a typed ERROR."""
    out = tmp_path / "report.html"
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"),
         str(out), "--payload-file", str(tmp_path / "does-not-exist.json")],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"},
    )
    assert r.returncode == 1
    assert "ERROR:RENDER_PAYLOAD_FILE_UNREADABLE" in r.stderr


def test_render_rejects_path_traversal_without_test_bypass():
    env = os.environ.copy()
    env.pop("PYTEST_CURRENT_TEST", None)
    env.pop("VIDEO_LENS_ALLOW_ANY_PATH", None)
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"), "/tmp/video-lens_escape.html"],
        input=json.dumps(sample_render_payload()),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    assert r.returncode == 1
    assert "ERROR:RENDER_INVALID_OUTPUT_PATH" in r.stderr


def test_sanitise_payload_preserves_legitimate_outline_and_description():
    clean = sanitise_payload(sample_render_payload())
    assert f"https://www.youtube.com/watch?v={VIDEO_ID}&amp;t=123" in clean["OUTLINE"]
    assert 'class="ts"' in clean["OUTLINE"]
    assert 'data-t="123"' in clean["OUTLINE"]
    assert 'rel="noopener noreferrer"' in clean["OUTLINE"]
    assert 'class="outline-title"' in clean["OUTLINE"]
    assert 'class="outline-detail"' in clean["OUTLINE"]
    assert 'href="https://example.com/path?q=1"' in clean["DESCRIPTION_SECTION"]
    assert 'rel="noopener noreferrer"' in clean["DESCRIPTION_SECTION"]


def test_renderer_builds_meta_from_new_shape(tmp_path):
    """New shape: renderer constructs VIDEO_LENS_META from structured fields."""
    out = tmp_path / "report.html"
    payload = new_shape_payload()
    clean = sanitise_payload(payload, str(out))
    meta = json.loads(clean["VIDEO_LENS_META"].replace("<\\/", "</"))
    assert meta["videoId"] == VIDEO_ID
    assert meta["title"] == "Test Video Title"
    assert meta["channel"] == "Test Channel"
    assert meta["duration"] == "10 min"
    assert meta["publishDate"] == "Jan 01 2025"
    assert meta["generationDate"] == "2025-01-01"
    assert meta["summary"] == "E2E test summary."
    assert meta["tags"] == ["test", "demo"]
    assert meta["keywords"] == ["Point"]
    assert meta["filename"] == "report.html"
    assert meta["agentModel"] == "claude-opus-4-7"
    assert meta["durationSeconds"] == 42
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", meta["generatedAt"])
    _render_clean(clean, str(out), template_path=TEMPLATE)
    html = out.read_text(encoding="utf-8")
    assert 'id="video-lens-meta"' in html
    assert "{{" not in html


def test_renderer_keywords_are_li_aware(tmp_path):
    """CH1: only the FIRST <strong> of each <li> is a keyword, not inline ones."""
    kp = (
        "<li><strong>Headline A</strong> — short<p>The "
        "<strong>inline term</strong> should not appear in keywords.</p></li>"
        "<li><strong>Headline B</strong> — second<p>More text "
        "with <em>emphasis</em> and another <strong>inline</strong> term.</p></li>"
    )
    payload = new_shape_payload(KEY_POINTS=kp)
    clean = sanitise_payload(payload, "/tmp/x.html")
    meta = json.loads(clean["VIDEO_LENS_META"].replace("<\\/", "</"))
    assert meta["keywords"] == ["Headline A", "Headline B"]


def test_renderer_summary_truncates_on_word_boundary(tmp_path):
    """CH2: truncation breaks on whitespace and appends an ellipsis."""
    long_summary = ("alpha beta gamma " * 30).strip()  # > 300 chars
    payload = new_shape_payload(SUMMARY=long_summary)
    clean = sanitise_payload(payload, "/tmp/x.html")
    meta = json.loads(clean["VIDEO_LENS_META"].replace("<\\/", "</"))
    assert meta["summary"].endswith("…")
    assert len(meta["summary"]) <= 301
    # truncation point must be at a word boundary — no torn final word
    body = meta["summary"][:-1]  # strip ellipsis
    assert not body.endswith(" ")
    assert body.split()[-1] in {"alpha", "beta", "gamma"}


def test_renderer_unescapes_entities_in_summary(tmp_path):
    """CH2: SUMMARY HTML entities are decoded in meta.summary."""
    payload = new_shape_payload(SUMMARY="A &mdash; B &amp; C")
    clean = sanitise_payload(payload, "/tmp/x.html")
    meta = json.loads(clean["VIDEO_LENS_META"].replace("<\\/", "</"))
    assert meta["summary"] == "A — B & C"


def test_renderer_new_shape_optional_fields_default_empty(tmp_path):
    """Missing optional fields render as empty strings / empty array; info metadata is optional."""
    payload = new_shape_payload()
    for k in (
        "TAGS",
        "CHANNEL",
        "DURATION",
        "PUBLISH_DATE",
        "GENERATION_DATE",
        "GENERATION_DURATION_SECONDS",
        "AGENT_MODEL",
    ):
        payload.pop(k, None)
    clean = sanitise_payload(payload, "/tmp/x.html")
    meta = json.loads(clean["VIDEO_LENS_META"].replace("<\\/", "</"))
    assert meta["tags"] == []
    assert meta["channel"] == ""
    assert meta["agentModel"] == ""
    assert "durationSeconds" not in meta


def test_renderer_accepts_string_generation_duration():
    """GENERATION_DURATION_SECONDS may arrive from a shell calculation as a string."""
    payload = new_shape_payload(GENERATION_DURATION_SECONDS="7")
    clean = sanitise_payload(payload, "/tmp/x.html")
    meta = json.loads(clean["VIDEO_LENS_META"].replace("<\\/", "</"))
    assert meta["durationSeconds"] == 7


@pytest.mark.parametrize("value", ["abc", "-1", True, 1.5])
def test_renderer_rejects_invalid_generation_duration(value):
    """GENERATION_DURATION_SECONDS must be a non-negative integer if supplied."""
    payload = new_shape_payload(GENERATION_DURATION_SECONDS=value)
    detail = assert_render_validation("RENDER_INVALID_META_JSON", payload)
    assert "GENERATION_DURATION_SECONDS" in detail


def test_renderer_rejects_non_list_tags():
    """TAGS must be a JSON array — string is rejected with RENDER_INVALID_META_JSON."""
    payload = new_shape_payload(TAGS="not-a-list")
    with pytest.raises(RenderValidationError) as exc:
        sanitise_payload(payload, "/tmp/x.html")
    assert exc.value.code == "RENDER_INVALID_META_JSON"


def test_renderer_normalizes_and_dedupes_tags():
    """New reports embed normalized tags (lowercase, hyphen→space, deduped) so the
    feedback loop and gallery see a consistent vocabulary at the write point (F4)."""
    payload = new_shape_payload(TAGS=["AI-Coding", "ai coding", "  LLM  ", "llm", 5])
    clean = sanitise_payload(payload, "/tmp/x.html")
    meta = json.loads(clean["VIDEO_LENS_META"].replace("<\\/", "</"))
    assert meta["tags"] == ["ai coding", "llm"]  # folded, deduped, non-str dropped


def test_sanitiser_passes_bare_br_in_description():
    """N4: bare <br> in DESCRIPTION_SECTION sanitises through (allowlisted)."""
    payload = sample_render_payload(DESCRIPTION_SECTION=(
        '<details class="description-details"><summary>YouTube Description</summary>'
        '<div class="video-description">line1<br>line2<br/>line3</div></details>'
    ))
    clean = sanitise_payload(payload)
    # Both forms emit a self-closed start tag with no separate end tag.
    assert clean["DESCRIPTION_SECTION"].count("<br>") == 2
    assert "</br>" not in clean["DESCRIPTION_SECTION"]


def test_sanitiser_passes_unknown_entity():
    """N4: unknown named entity refs pass through verbatim (browser handles)."""
    payload = sample_render_payload(KEY_POINTS=(
        "<li><strong>X</strong> &nonsense; y<p>Then &mdash; ok.</p></li>"
    ))
    clean = sanitise_payload(payload)
    assert "&nonsense;" in clean["KEY_POINTS"]
    assert "&mdash;" in clean["KEY_POINTS"]


def test_sanitiser_rejects_nested_anchor_without_href_in_description():
    """N4: a nested <a> in DESCRIPTION_SECTION must still carry href; bare <a> is rejected."""
    payload = sample_render_payload(DESCRIPTION_SECTION=(
        '<details class="description-details"><summary>YouTube Description</summary>'
        '<div class="video-description">'
        '<a href="https://example.com" target="_blank" rel="noopener noreferrer">'
        'outer <a>inner</a> tail</a></div></details>'
    ))
    with pytest.raises(RenderValidationError) as exc:
        sanitise_payload(payload)
    assert exc.value.code == "RENDER_DISALLOWED_HTML"
    assert "a href missing" in exc.value.detail


def test_render_and_serve(tmp_path):
    """Fast, no-network check: render with canned data and verify HTTP serve."""
    out = tmp_path / "report.html"
    _render_clean({
        "VIDEO_ID":            VIDEO_ID,
        "VIDEO_TITLE":         "Test Video Title",
        "VIDEO_URL":           f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "META_LINE":           "Test Channel · 10 min · Jan 01 2025 · 1.0M views",
        "SUMMARY":             "E2E test summary.",
        "TAKEAWAY":            "E2E test takeaway.",
        "KEY_POINTS":          "<li><strong>Point</strong> — detail</li>",
        "OUTLINE":             f'<li><a class="ts" data-t="0" href="https://www.youtube.com/watch?v={VIDEO_ID}&t=0" target="_blank">▶ 0:00</a> — <span class="outline-title">Intro</span><span class="outline-detail"> Opening.</span></li>',
        "DESCRIPTION_SECTION": "",
        "VIDEO_LENS_META":     SAMPLE_META,
    }, str(out), template_path=TEMPLATE)
    assert out.exists()
    html = out.read_text(encoding="utf-8")
    assert VIDEO_ID in html
    assert "{{" not in html
    assert 'id="video-lens-meta"' in html
    assert 'id="summary"' in html
    assert 'id="takeaway"' in html
    assert 'id="key-points"' in html
    assert 'class="ts"' in html
    assert 'data-t=' in html
    assert 'class="outline-title"' in html
    assert 'class="outline-detail"' in html

    # Serve and verify HTTP
    try:
        r = subprocess.run(
            ["bash", str(SCRIPT_DIR / "serve_report.sh"), str(out)],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "NO_BROWSER": "1", "XDG_CACHE_HOME": str(tmp_path / "cache")},
        )
        assert r.returncode == 0, f"serve_report failed:\n{r.stderr}"
        assert f"HTML_REPORT: {out}" in r.stdout
        time.sleep(0.5)
        resp = urllib.request.urlopen(f"http://127.0.0.1:8765/{out.name}", timeout=5)
        assert resp.status == 200
    finally:
        subprocess.run(["bash", "-c", "for p in $(lsof -ti:8765 -sTCP:LISTEN 2>/dev/null); do ps -p \"$p\" -o args= 2>/dev/null | grep -q http.server && kill \"$p\"; done 2>/dev/null || true"],
                       capture_output=True)


def test_serve_takes_over_untracked_server(tmp_path):
    """A stale http.server on 8765 with no PID file must be killed, not bind-failed."""
    out = tmp_path / "report.html"
    _render_clean({
        "VIDEO_ID":            VIDEO_ID,
        "VIDEO_TITLE":         "Test Video Title",
        "VIDEO_URL":           f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "META_LINE":           "Test Channel",
        "SUMMARY":             "E2E test summary.",
        "TAKEAWAY":            "E2E test takeaway.",
        "KEY_POINTS":          "<li><strong>Point</strong> — detail</li>",
        "OUTLINE":             f'<li><a class="ts" data-t="0" href="https://www.youtube.com/watch?v={VIDEO_ID}&t=0" target="_blank">▶ 0:00</a> — <span class="outline-title">Intro</span><span class="outline-detail"> Opening.</span></li>',
        "DESCRIPTION_SECTION": "",
        "VIDEO_LENS_META":     SAMPLE_META,
    }, str(out), template_path=TEMPLATE)

    def _wait_for_server(deadline=5.0):
        end = time.monotonic() + deadline
        while time.monotonic() < end:
            try:
                return urllib.request.urlopen(
                    f"http://127.0.0.1:8765/{out.name}", timeout=1)
            except Exception:
                time.sleep(0.1)
        raise AssertionError("server on 8765 never became reachable")

    stray = subprocess.Popen(
        [sys.executable, "-m", "http.server", "8765", "--bind", "127.0.0.1",
         "--directory", str(tmp_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_server()
        r = subprocess.run(
            ["bash", str(SCRIPT_DIR / "serve_report.sh"), str(out)],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "NO_BROWSER": "1", "XDG_CACHE_HOME": str(tmp_path / "cache")},
        )
        assert r.returncode == 0, f"serve_report failed:\n{r.stderr}"
        assert f"HTML_REPORT: {out}" in r.stdout
        resp = _wait_for_server()
        assert resp.status == 200
    finally:
        stray.kill()
        subprocess.run(["bash", "-c", "for p in $(lsof -ti:8765 -sTCP:LISTEN 2>/dev/null); do ps -p \"$p\" -o args= 2>/dev/null | grep -q http.server && kill \"$p\"; done 2>/dev/null || true"],
                       capture_output=True)


def test_build_index(tmp_path):
    """Fast, no-network check: build_index.py scans reports and writes manifest.json."""
    BUILD_INDEX = GALLERY_SCRIPT_DIR / "build_index.py"

    # Create two sample reports with video-lens-meta blocks
    vid, title, gen_date = "bjdBVZa66oU", "Test Video One", "2025-01-01"
    meta = json.dumps({
        "videoId": vid,
        "title": title,
        "channel": "Test Channel",
        "duration": "5 min",
        "publishDate": "Jan 01 2025",
        "generationDate": gen_date,
        "summary": f"Summary for {title}.",
        "tags": ["test"],
        "keywords": ["Point"],
        "filename": f"{gen_date}-000000-video-lens_test_0.html",
    })
    report = tmp_path / f"{gen_date}-000000-video-lens_test_0.html"
    report.write_text(
        f'<html><body><script type="application/json" id="video-lens-meta">{meta}</script></body></html>',
        encoding="utf-8",
    )

    r = subprocess.run(
        [sys.executable, str(BUILD_INDEX), "--dir", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"build_index failed:\n{r.stderr}"

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists(), "manifest.json not created"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["count"] == 1
    assert len(manifest["reports"]) == 1
    assert manifest["reports"][0]["title"] == "Test Video One"


def test_build_index_normalize_tags_folds_variants():
    """_normalize_tags: lowercase, hyphen→space, dedupe in first-seen order (F4)."""
    sys.path.insert(0, str(GALLERY_SCRIPT_DIR))
    from build_index import _normalize_tags  # type: ignore
    assert _normalize_tags(["AI-Coding", "ai coding", "LLM", "llm"]) == ["ai coding", "llm"]
    assert _normalize_tags(["  Developer   Tools  "]) == ["developer tools"]
    assert _normalize_tags(["ok", 123, None, ""]) == ["ok"]


def test_build_index_folds_tags_in_manifest(tmp_path):
    """End-to-end: build_index writes a manifest with tags folded to normalized form."""
    BUILD_INDEX = GALLERY_SCRIPT_DIR / "build_index.py"
    meta = json.dumps({
        "videoId": "bjdBVZa66oU",
        "title": "T",
        "tags": ["AI-Coding", "ai coding", "Productivity"],
        "keywords": ["P"],
    })
    report = tmp_path / "2025-01-01-000000-video-lens_test_0.html"
    report.write_text(
        f'<html><body><script type="application/json" id="video-lens-meta">{meta}</script></body></html>',
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(BUILD_INDEX), "--dir", str(tmp_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"build_index failed:\n{r.stderr}"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["reports"][0]["tags"] == ["ai coding", "productivity"]


# --- preflight ---

from preflight import (  # noqa: E402
    extract_video_id,
    find_duplicate,
    map_language,
    read_existing_tags,
    sweep_stale_payloads,
)


@pytest.mark.parametrize("inp,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?t=30", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
])
def test_preflight_extracts_id_from_each_url_form(inp, expected):
    vid, err = extract_video_id(inp)
    assert err is None
    assert vid == expected


def test_preflight_rejects_shorts():
    _, err = extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ")
    assert err == "SHORTS_NOT_SUPPORTED"


def test_preflight_invalid_input():
    _, err = extract_video_id("https://example.com/x")
    assert err == "INVALID_INPUT"


@pytest.mark.parametrize("inp,expected", [
    ("Spanish", "es"),
    ("english", "en"),
    ("fr", "fr"),
    ("", ""),
    ("klingon", "klingon"),
])
def test_preflight_maps_language_names(inp, expected):
    assert map_language(inp) == expected


def test_preflight_main_splits_argv_on_space(monkeypatch, capsys, tmp_path):
    """When LANG_REQUEST is folded into url_or_id as 'id es', preflight must split.

    Routed through the helper so REPORTS_DIR, PAYLOAD_BASE_DIR, and MANIFEST_PATH
    are all pinned to tmp_path — the run must not touch the live ~/Downloads.
    """
    rc, out = _run_preflight_main(
        monkeypatch, capsys, tmp_path, ["preflight.py", "dQw4w9WgXcQ es"],
    )
    assert rc == 0
    assert "VIDEO_ID: dQw4w9WgXcQ" in out
    assert "LANG_CODE: es" in out


def test_preflight_emits_newest_duplicate_only(tmp_path, monkeypatch):
    import preflight  # type: ignore
    fake_reports = tmp_path / "Downloads" / "video-lens" / "reports"
    fake_reports.mkdir(parents=True)
    older = fake_reports / "2025-01-01-000000-video-lens_dQw4w9WgXcQ_old.html"
    newer = fake_reports / "2025-06-01-000000-video-lens_dQw4w9WgXcQ_new.html"
    older.write_text("x")
    newer.write_text("x")
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_750_000_000, 1_750_000_000))
    monkeypatch.setattr(preflight, "REPORTS_DIR", fake_reports)
    assert preflight.find_duplicate("dQw4w9WgXcQ") == newer


def test_preflight_sweeps_stale_payload_dirs(tmp_path):
    """Payload dirs older than the TTL are removed; fresh ones survive (F1)."""
    import preflight  # type: ignore
    base = tmp_path / ".tmp"
    base.mkdir()
    stale = base / "payload-old"
    fresh = base / "payload-new"
    keep = base / "not-a-payload"
    for d in (stale, fresh, keep):
        d.mkdir()
        (d / "payload.json").write_text("{}")
    now = 2_000_000_000
    os.utime(stale, (now - preflight.PAYLOAD_TTL_SECONDS - 60,) * 2)
    os.utime(fresh, (now - 60,) * 2)
    os.utime(keep, (now - preflight.PAYLOAD_TTL_SECONDS - 60,) * 2)

    sweep_stale_payloads(base, now=now)

    assert not stale.exists()
    assert fresh.exists()
    assert keep.exists()  # only payload-* dirs are swept


def test_read_existing_tags_ranks_and_folds_variants(tmp_path):
    """Tags are counted most-frequent-first, with trivial variants folded (F4)."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"reports": [
        {"tags": ["ai", "AI-Coding"]},
        {"tags": ["ai coding", "ai"]},
        {"tags": ["ai", "productivity"]},
    ]}), encoding="utf-8")
    tags = read_existing_tags(manifest, limit=40)
    # "ai" (3) > "ai coding"/"AI-Coding" folded (2) > "productivity" (1)
    assert tags == ["ai", "ai coding", "productivity"]


def test_read_existing_tags_ignores_string_tags(tmp_path):
    """A report whose `tags` is a string (malformed) must not be char-split into
    single-letter tags — it is skipped entirely (F4 hardening)."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"reports": [
        {"tags": "ai"},               # malformed: string, not a list
        {"tags": ["ai", "llm"]},      # valid
    ]}), encoding="utf-8")
    tags = read_existing_tags(manifest)
    assert tags == ["ai", "llm"]      # no 'a', 'i' character tags


def test_read_existing_tags_dedupes_variants_within_a_report(tmp_path):
    """Two normalized-equal tags in one report count once, matching build_index."""
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"reports": [
        {"tags": ["ai", "AI", "A-I"]},   # all fold to "ai" → one count for this report
        {"tags": ["ai"]},                # second report → second count
    ]}), encoding="utf-8")
    # If per-report dedup were missing, "ai" would count 4×, not 2×; ranking is the
    # same here, so assert the count via a second tag that must rank below it.
    manifest.write_text(json.dumps({"reports": [
        {"tags": ["ai", "AI", "A-I", "llm"]},
        {"tags": ["llm"]},
    ]}), encoding="utf-8")
    # Without dedup: ai=3, llm=2 → ai first. With dedup: ai=1, llm=2 → llm first.
    assert read_existing_tags(manifest)[0] == "llm"


def test_read_existing_tags_respects_limit(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"reports": [
        {"tags": [f"tag{i}" for i in range(10)]},
    ]}), encoding="utf-8")
    assert len(read_existing_tags(manifest, limit=3)) == 3


def test_read_existing_tags_missing_manifest_returns_empty(tmp_path):
    """Fresh install has no manifest — must degrade gracefully, never raise (F4 caveat)."""
    assert read_existing_tags(tmp_path / "does-not-exist.json") == []


def test_read_existing_tags_malformed_manifest_returns_empty(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{not json", encoding="utf-8")
    assert read_existing_tags(manifest) == []


def test_preflight_main_emits_existing_tags(monkeypatch, capsys, tmp_path):
    """When a manifest exists, main() emits an EXISTING_TAGS line."""
    import preflight  # type: ignore
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"reports": [{"tags": ["ai", "llm"]}]}), encoding="utf-8")
    monkeypatch.setattr(preflight, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(preflight, "PAYLOAD_BASE_DIR", tmp_path / "payload-base")
    monkeypatch.setattr(preflight, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(sys, "argv", ["preflight.py", "dQw4w9WgXcQ"])
    assert preflight.main() == 0
    out = capsys.readouterr().out
    assert re.search(r"^EXISTING_TAGS: .*\bai\b.*\bllm\b", out, re.M)


def test_preflight_main_omits_existing_tags_without_manifest(monkeypatch, capsys, tmp_path):
    """No manifest → no EXISTING_TAGS line (the line is optional)."""
    rc, out = _run_preflight_main(
        monkeypatch, capsys, tmp_path, ["preflight.py", "dQw4w9WgXcQ"],
    )
    assert rc == 0
    assert "EXISTING_TAGS:" not in out


def _run_preflight_main(monkeypatch, capsys, tmp_path, argv):
    """Helper: run preflight.main() with REPORTS_DIR and PAYLOAD_BASE_DIR pinned to tmp_path."""
    import preflight  # type: ignore
    monkeypatch.setattr(preflight, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(preflight, "PAYLOAD_BASE_DIR", tmp_path / "payload-base")
    monkeypatch.setattr(preflight, "MANIFEST_PATH", tmp_path / "manifest.json")
    monkeypatch.setattr(sys, "argv", argv)
    rc = preflight.main()
    out = capsys.readouterr().out
    return rc, out


def test_preflight_payload_path_is_unique_and_unpredictable(monkeypatch, capsys, tmp_path):
    """PAYLOAD_PATH lives inside a fresh 0700 tempdir; the file itself does NOT exist
    so the agent's Write tool can create it without a prior Read. Guards against the
    previous f-string `/tmp/video-lens-payload-{id}-{epoch}.json` shape (symlink-attackable)
    and against the mkstemp regression that pre-created the file."""
    import re as _re

    paths = []
    for _ in range(2):
        rc, out = _run_preflight_main(
            monkeypatch, capsys, tmp_path,
            ["preflight.py", "dQw4w9WgXcQ"],
        )
        assert rc == 0
        m = _re.search(r"^PAYLOAD_PATH: (.+)$", out, _re.M)
        assert m, f"No PAYLOAD_PATH line in: {out}"
        paths.append(m.group(1))

    assert paths[0] != paths[1], "Two runs produced identical PAYLOAD_PATHs"
    for p in paths:
        # Old predictable shape: `…video-lens-payload-{11chars}-{digits}.json`
        assert not _re.search(
            r"video-lens-payload-dQw4w9WgXcQ-\d+\.json$", p
        ), f"PAYLOAD_PATH matches the old predictable shape: {p}"
        path = pathlib.Path(p)
        assert not path.exists(), f"Payload file pre-created — Write tool would refuse: {p}"
        parent = path.parent
        assert parent.is_dir(), f"Payload parent dir missing: {parent}"
        assert parent.stat().st_mode & 0o777 == 0o700, (
            f"Parent dir mode not 0700: {oct(parent.stat().st_mode)}"
        )


def test_preflight_emits_scripts_dir(monkeypatch, capsys, tmp_path):
    """SCRIPTS_DIR: line must point to the directory containing preflight.py."""
    rc, out = _run_preflight_main(
        monkeypatch, capsys, tmp_path,
        ["preflight.py", "dQw4w9WgXcQ"],
    )
    assert rc == 0
    m = re.search(r"^SCRIPTS_DIR: (.+)$", out, re.M)
    assert m, f"No SCRIPTS_DIR line in: {out}"
    scripts_dir = pathlib.Path(m.group(1))
    assert (scripts_dir / "preflight.py").exists()
    assert scripts_dir.resolve() == SCRIPT_DIR.resolve()

    # Also clean up the payload file mkstemp created
    payload_m = re.search(r"^PAYLOAD_PATH: (.+)$", out, re.M)
    if payload_m:
        pathlib.Path(payload_m.group(1)).unlink(missing_ok=True)


# --- renderer extensions ---


def test_renderer_composes_meta_line_from_parts():
    payload = new_shape_payload(META_LINE="")
    clean = sanitise_payload(payload, "/tmp/x.html")
    assert clean["META_LINE"] == html_lib.escape(
        "Test Channel · 10 min · Jan 01 2025 · 1.0M views"
    )


def test_renderer_meta_line_omits_empty_parts():
    payload = new_shape_payload(META_LINE="", VIEWS="")
    clean = sanitise_payload(payload, "/tmp/x.html")
    assert clean["META_LINE"].count("·") == 2


def test_renderer_keeps_meta_line_when_supplied():
    payload = new_shape_payload(META_LINE="Custom Line", VIEWS="ignored")
    clean = sanitise_payload(payload, "/tmp/x.html")
    assert clean["META_LINE"] == "Custom Line"


def test_renderer_computes_duration_from_start_epoch(monkeypatch):
    """Pin time.time() so the assertion is exact, not '>= 7'."""
    fixed_now = 1_750_000_007
    monkeypatch.setattr(render_report.time, "time", lambda: fixed_now)
    payload = new_shape_payload(
        GENERATION_DURATION_SECONDS="",
        GENERATION_START_EPOCH=fixed_now - 7,
    )
    clean = sanitise_payload(payload, "/tmp/x.html")
    meta = json.loads(clean["VIDEO_LENS_META"].replace("<\\/", "</"))
    assert meta["durationSeconds"] == 7


def test_renderer_rejects_negative_start_epoch():
    payload = new_shape_payload(
        GENERATION_DURATION_SECONDS="",
        GENERATION_START_EPOCH=-1,
    )
    with pytest.raises(RenderValidationError) as exc:
        sanitise_payload(payload, "/tmp/x.html")
    assert exc.value.code == "RENDER_INVALID_META_JSON"


def test_renderer_derives_filename_with_output_dir(tmp_path):
    out_dir = tmp_path / "reports"
    out_dir.mkdir()
    payload = new_shape_payload(GENERATION_DATE="2026-05-17")
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"),
         "--output-dir", str(out_dir)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("OUTPUT_PATH: ")
    written = pathlib.Path(r.stdout.split(": ", 1)[1].strip())
    assert written.exists()
    assert re.match(
        r"2026-05-17-\d{6}-video-lens_" + VIDEO_ID + r"_test_video_title\.html",
        written.name,
    )


def test_renderer_output_dir_defaults_empty_generation_date_to_today(tmp_path):
    """With --output-dir, an empty GENERATION_DATE defaults to today rather than
    rejecting — the filename's HHMMSS already comes from the same clock (F5)."""
    out_dir = tmp_path / "reports"
    out_dir.mkdir()
    payload = new_shape_payload(GENERATION_DATE="")
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"),
         "--output-dir", str(out_dir)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"},
    )
    assert r.returncode == 0, r.stderr
    written = pathlib.Path(r.stdout.split(": ", 1)[1].strip())
    assert written.exists()
    today = date.today().isoformat()
    assert written.name.startswith(today + "-"), written.name


def test_renderer_slug_falls_back_for_non_ascii_title(tmp_path):
    out_dir = tmp_path / "reports"
    out_dir.mkdir()
    payload = new_shape_payload(VIDEO_TITLE="日本語タイトル", GENERATION_DATE="2026-05-17")
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"),
         "--output-dir", str(out_dir)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"},
    )
    assert r.returncode == 0, r.stderr
    written = pathlib.Path(r.stdout.split(": ", 1)[1].strip())
    assert written.name.endswith("_video.html")


def test_renderer_rejects_malformed_generation_date_with_output_dir(tmp_path):
    """With --output-dir, GENERATION_DATE must match YYYY-MM-DD; otherwise the
    derived filename would embed garbage like 'December 5, 2025-HHMMSS-…'."""
    out_dir = tmp_path / "reports"
    out_dir.mkdir()
    payload = new_shape_payload(GENERATION_DATE="December 5, 2025")
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"),
         "--output-dir", str(out_dir)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"},
    )
    assert r.returncode != 0
    assert "RENDER_PAYLOAD_INVALID" in r.stderr
    assert "bad_format_keys" in r.stderr
    assert "GENERATION_DATE" in r.stderr


def test_renderer_accepts_http_video_url(tmp_path):
    """VIDEO_URL with http:// must be accepted; renderer canonicalises to https.
    Preflight already accepts http URLs; the renderer must agree."""
    out = tmp_path / "report.html"
    payload = new_shape_payload(
        VIDEO_URL=f"http://www.youtube.com/watch?v={VIDEO_ID}",
    )
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"), str(out)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=10,
        env={**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"},
    )
    assert r.returncode == 0, f"render failed: {r.stderr}"
    html = out.read_text(encoding="utf-8")
    assert f"https://www.youtube.com/watch?v={VIDEO_ID}" in html


def test_renderer_keeps_payload_file_on_success(tmp_path):
    """Renderer must NOT delete the payload file — debugging the LLM's output
    requires retaining the input."""
    out = tmp_path / "report.html"
    payload_file = tmp_path / "payload.json"
    payload_file.write_text(json.dumps(sample_render_payload()), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"),
         str(out), "--payload-file", str(payload_file)],
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"},
    )
    assert r.returncode == 0, r.stderr
    assert payload_file.exists(), "Renderer deleted the payload file"


def test_renderer_uses_slug_hint_when_provided(tmp_path):
    """SLUG_HINT overrides the title-derived slug. The renderer normalizes
    `my-talk-name` → `my_talk_name`."""
    out_dir = tmp_path / "reports"
    out_dir.mkdir()
    payload = new_shape_payload(
        VIDEO_TITLE="日本語タイトル",
        GENERATION_DATE="2026-05-17",
        SLUG_HINT="my-talk-name",
    )
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"),
         "--output-dir", str(out_dir)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"},
    )
    assert r.returncode == 0, r.stderr
    written = pathlib.Path(r.stdout.split(": ", 1)[1].strip())
    assert written.name.endswith("_my_talk_name.html"), f"Got {written.name!r}"


def test_renderer_output_dir_outside_clamp_rejected(tmp_path):
    """--output-dir outside ALLOWED_OUTPUT_ROOT must reject (bypass NOT set)."""
    out_dir = tmp_path / "elsewhere"
    out_dir.mkdir()
    payload = new_shape_payload(GENERATION_DATE="2026-05-17")
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTEST_CURRENT_TEST", "VIDEO_LENS_ALLOW_ANY_PATH")}
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"),
         "--output-dir", str(out_dir)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
        env=env,
    )
    assert r.returncode != 0
    assert "RENDER_INVALID_OUTPUT_PATH" in r.stderr


def test_renderer_positional_path_still_works(tmp_path):
    """Legacy file-path arg keeps working (the test bypass governs it)."""
    target = tmp_path / "out.html"
    payload = new_shape_payload()
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "render_report.py"), str(target)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "VIDEO_LENS_ALLOW_ANY_PATH": "1"},
    )
    assert r.returncode == 0, r.stderr
    assert target.exists()
    assert r.stdout.startswith("OUTPUT_PATH: ")


@pytest.mark.slow
def test_full_pipeline(tmp_path):
    # --- Step 1: Fetch transcript ---
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "fetch_transcript.py"), VIDEO_ID],
        capture_output=True, text=True, timeout=30,
    )
    assert r.returncode == 0, f"fetch_transcript failed:\n{r.stderr}"
    lines = r.stdout.splitlines()
    headers = {l.split(": ", 1)[0]: l.split(": ", 1)[1]
               for l in lines if ": " in l and not l.startswith("[")}
    assert headers.get("TITLE"), "Missing TITLE"
    assert headers.get("LANG"), "Missing LANG"
    assert "CHANNEL" in headers, "Missing CHANNEL key"  # value may be empty if scraping fails
    transcript_lines = [l for l in lines if re.match(r"^\[\d+:\d+", l)]
    assert len(transcript_lines) >= 10, f"Too few transcript lines: {len(transcript_lines)}"

    # --- Step 2: Fetch metadata ---
    r = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "fetch_metadata.py"), VIDEO_ID],
        capture_output=True, text=True, timeout=90,
    )
    assert r.returncode == 0, f"fetch_metadata failed:\n{r.stderr}"
    metadata_ok = not any(l.startswith("ERROR:YTDLP_") for l in r.stdout.splitlines())
    if metadata_ok:
        assert "YTDLP_CHANNEL:" in r.stdout
        assert "YTDLP_DURATION:" in r.stdout
        assert "YTDLP_CHAPTERS:" in r.stdout
        chapters_line = next(
            (l for l in r.stdout.splitlines() if l.startswith("YTDLP_CHAPTERS:")), None
        )
        if chapters_line:
            chapters_json = chapters_line.split(": ", 1)[1]
            chapters = json.loads(chapters_json)
            assert isinstance(chapters, list)


@pytest.mark.slow
def test_claude_session():
    if not shutil.which("claude"):
        pytest.skip("claude CLI not available")

    if not (Path.home() / ".claude/skills/video-lens/SKILL.md").exists():
        pytest.skip("video-lens skill not installed — run: task install-skill-local AGENT=claude")

    before = time.time()
    result = subprocess.run(
        ["claude", "--print", "--dangerously-skip-permissions",
         "--allowedTools", "Bash,Read",
         "--",
         f"Summarize this video: https://www.youtube.com/watch?v={VIDEO_ID}"],
        capture_output=True, text=True, timeout=300,
        env={**__import__("os").environ, "NO_BROWSER": "1"},
    )
    assert result.returncode == 0, f"claude exited {result.returncode}:\n{result.stderr[:500]}"

    # Locate the report via filesystem — bash tool output does not appear in
    # claude --print stdout (only the final assistant text response does).
    downloads = Path.home() / "Downloads" / "video-lens"
    matches = sorted(
        [p for p in downloads.glob("reports/????-??-??-??????-video-lens_*.html")
         if p.stat().st_mtime >= before],
        key=lambda p: p.stat().st_mtime,
    )
    assert matches, "No video-lens HTML report found in ~/Downloads/video-lens/reports/ after claude session"

    report_path = matches[-1]
    # Filename: YYYY-MM-DD-HHMMSS-video-lens_<VIDEO_ID>_<slug>.html
    assert re.match(r"\d{4}-\d{2}-\d{2}-\d{6}-video-lens_[A-Za-z0-9_-]+_[a-z0-9_]+\.html$", report_path.name)
    html = report_path.read_text(encoding="utf-8")
    assert "{{" not in html                        # no unreplaced placeholders
    assert VIDEO_ID in html                        # iframe + JS embed
    assert 'id="summary"' in html
    assert 'id="takeaway"' in html
    assert 'id="key-points"' in html
    assert 'class="ts"' in html                   # outline timestamp links
    assert len(re.findall(r'data-t="\d+"', html)) >= 3  # at least 3 outline entries
    # Non-trivial content
    summary_m = re.search(r'id="summary".*?<p>(.*?)</p>', html, re.DOTALL)
    assert summary_m, "Could not find summary <p> in rendered HTML"
    assert len(re.sub(r"<[^>]+>", "", summary_m.group(1)).strip()) >= 50
    takeaway_m = re.search(r'id="takeaway".*?<p>(.*?)</p>', html, re.DOTALL)
    assert takeaway_m, "Could not find takeaway <p> in rendered HTML"
    assert len(re.sub(r"<[^>]+>", "", takeaway_m.group(1)).strip()) >= 30
    # Key points: count <li> only within the key-points section
    kp_match = re.search(r'id="key-points".*?</section>', html, re.DOTALL)
    assert kp_match and kp_match.group().count("<li>") >= 3
    subprocess.run(["bash", "-c", "for p in $(lsof -ti:8765 -sTCP:LISTEN 2>/dev/null); do ps -p \"$p\" -o args= 2>/dev/null | grep -q http.server && kill \"$p\"; done 2>/dev/null || true"],
                   capture_output=True)


# ---------- tag-normalization drift guard ----------

def test_normalize_tags_identical_across_call_sites():
    """`_normalize_tags` is copy-pasted into preflight.py, render_report.py, and
    build_index.py (they live in different skill dirs and can't share a module).
    The EXISTING_TAGS feedback loop's correctness depends on all three folding
    tags identically — this asserts they have not drifted."""
    sys.path.insert(0, str(GALLERY_SCRIPT_DIR))
    import preflight
    import build_index
    import render_report as rr

    vectors = [
        ["AI", "ai", "AI-Coding", "ai coding", "  Developer   Tools  "],
        ["Agents", "agentic", "AI Agents"],
        ["", "  ", 123, None, "valid-tag"],     # non-str + empty entries dropped
        [],
        ["LLM", "llm", "L L M"],
    ]
    for tags in vectors:
        base = preflight._normalize_tags(tags)
        assert build_index._normalize_tags(tags) == base, tags
        assert rr._normalize_tags(tags) == base, tags
