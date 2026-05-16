"""Single end-to-end test — replaces all existing tests.
Runs the full pipeline: transcript → metadata → render → serve.
Run with: pytest tests/test_e2e.py -v
"""
import json, os, re, shutil, subprocess, sys, time, urllib.request
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
    assert "ERROR:RENDER_EMPTY_CONTENT" in r.stderr
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
        subprocess.run(["bash", "-c", "kill $(lsof -ti:8765 -sTCP:LISTEN) 2>/dev/null || true"],
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
    subprocess.run(["bash", "-c", "kill $(lsof -ti:8765 -sTCP:LISTEN) 2>/dev/null || true"],
                   capture_output=True)
