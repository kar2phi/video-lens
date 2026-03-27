"""Single end-to-end test — replaces all existing tests.
Runs the full pipeline: transcript → metadata → render → serve.
Run with: pytest tests/test_e2e.py -v
"""
import json, re, shutil, subprocess, sys, time, urllib.request
from pathlib import Path

import pytest

REPO_ROOT         = Path(__file__).resolve().parent.parent
SCRIPT_DIR        = REPO_ROOT / "skills" / "video-lens" / "scripts"
GALLERY_SCRIPT_DIR = REPO_ROOT / "skills" / "video-lens-gallery" / "scripts"
TEMPLATE          = REPO_ROOT / "skills" / "video-lens" / "template.html"

sys.path.insert(0, str(SCRIPT_DIR))
from render_report import render

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


def test_template_placeholders(tmp_path):
    """Fast, no-network check: all 10 keys replaced, no {{...}} remain."""
    out = tmp_path / "report.html"
    render({
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


def test_render_and_serve(tmp_path):
    """Fast, no-network check: render with canned data and verify HTTP serve."""
    out = tmp_path / "report.html"
    render({
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
            env={**__import__("os").environ, "NO_BROWSER": "1"},
        )
        assert r.returncode == 0, f"serve_report failed:\n{r.stderr}"
        assert f"HTML_REPORT: {out}" in r.stdout
        time.sleep(0.5)
        resp = urllib.request.urlopen(f"http://localhost:8765/{out.name}", timeout=5)
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
    metadata_ok = "YTDLP_ERROR" not in r.stdout
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
