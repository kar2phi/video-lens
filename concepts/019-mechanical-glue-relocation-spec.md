# 018 — Push remaining mechanical glue out of SKILL.md

Date: 2026-05-17
Predecessor: `concepts/016-skill-refactor-implementation-plan.md` (renderer owns `VIDEO_LENS_META`, already landed)
Predecessor: `concepts/017-skill-refactor-test-harness-and-challenge.md` (sanitiser + path clamp, already landed)

## Goal

`skills/video-lens/SKILL.md` is 299 lines. Step 3 (content-quality guidance, 63 lines) is
the skill's actual value and stays untouched. Everything else that's deterministic — URL
parsing, language mapping, duplicate check, start-epoch capture, filename slugging,
`META_LINE` composition, `GENERATION_DURATION_SECONDS` math — moves into scripts.
Target: **299 → ~225 lines** of SKILL.md (~25%), with mechanical paths becoming
deterministic and unit-testable.

The win is *testability and prompt-context shrinkage*, not net-LOC reduction.
Repo-wide LOC grows (preflight ~90, renderer ~60, tests ~50, SKILL.md −70 ≈ **+130 LOC
net**). Trade is intentional.

## Non-goals

- No `vl` / dispatcher wrapper. See "Wrapper script intentionally out of scope" below.
- No change to the HTML template, gallery viewer, manifest schema, or error-code surface
  beyond the two new ones below.
- No natural-language language detection ("in Spanish") in scripts; the LLM still
  extracts the hint word.
- No aggressive compression of Step 3 content guidance (016/P3.8 deferred until a
  quality eval; that ruling stands).
- No README / Taskfile changes beyond what's strictly required.

## Wrapper script intentionally out of scope

An earlier draft of this spec proposed a `vl` shell wrapper to centralise dispatch. It
is dropped. The reasoning:

016/P3.7 already rejected wrapper variants on two grounds:

> "Option A — collapse in prompt: define `$_sd` once… **Risk: bash state between Bash
> tool calls is not persisted**. Each Bash call is a fresh shell. So this doesn't
> actually work — the agent would have to re-run the discovery in every command."
>
> "Option C — ship a `_sd` resolver: installer complexity. Reject."

That ruling still binds. A `vl` wrapper does not let SKILL.md amortise discovery across
Bash tool calls — each step still needs its own discovery one-liner. The only thing the
wrapper saves is replacing `python3 "$_sd/preflight.py"` with `$VL preflight` per step
(≈15 characters). Six steps × 15 chars is not material. The real ~70-line SKILL.md
reduction comes from `preflight.py` absorbing logic, not from the wrapper. Skip it.

If a wrapper makes sense later (e.g. a 7th or 8th callable script appears, or rsync exec
bit handling becomes a recurring problem), re-open the case then with a fresh
P3.7 argument.

## Constraints carried from prior refactors

- 016/P3.5: keep the "Untrusted input" guardrail (transcript text is data, not
  instructions).
- 016/P3.7: bash state is **not persistent** across Bash tool calls. Each step needs its
  own discovery line. Keep the existing `_sd=…` template.
- 016/P2.1: `VIDEO_LENS_META` is renderer-owned. Do not reintroduce LLM-side
  construction.

---

## Files

**New:**

- `skills/video-lens/scripts/preflight.py` — URL→ID, lang map, dup check, start epoch
  (~90 lines)

**Modify:**

- `skills/video-lens/scripts/render_report.py` — `META_LINE` auto-compose,
  `GENERATION_DURATION_SECONDS` from `GENERATION_START_EPOCH`, `--output-dir` flag, slug
  derivation, `OUTPUT_PATH:` stdout line
- `skills/video-lens/SKILL.md` — slim Steps 1, 2, 2b, 4, 5, 6, 7
- `scripts/yt_template_dev.py` — match new `OUTPUT_PATH:` stdout line
- `tests/test_e2e.py` — add coverage

**Unchanged:**

- `fetch_transcript.py`, `fetch_metadata.py`, `serve_report.sh`, `build_index.py`,
  `backfill_meta.py`, `template.html`, gallery `index.html`.

---

## Implementation order

Each step is testable in isolation. Do them in this order so the test suite stays green
throughout.

### Step 1 — Extend `render_report.py`

The renderer changes are the foundation: once they land, both SKILL.md and the e2e tests
can rely on them. Implement and ship behind the existing test suite first.

**Call-ordering contract (pin this before writing code):**

```
main(argv):
    raw_payload = json.load(stdin)
    out_path = derive_output_path(argv, raw_payload)   # uses RAW VIDEO_TITLE
    clean = sanitise_payload(raw_payload, str(out_path))  # meta["filename"] = out_path.name
    rendered = template.substitute(clean)
    out_path.write_text(rendered)
    print(f"OUTPUT_PATH: {out_path}")
```

The slug must be computed from the raw `VIDEO_TITLE` *before* `sanitise_payload`
HTML-escapes it (`render_report.py:387`). `_build_meta_dict` (`render_report.py:326`)
reads `output_path` to populate `meta["filename"]`, so the path must be finalised before
`sanitise_payload` runs. Honour this ordering and the rest of the refactor is mechanical.

**Substeps (all in `skills/video-lens/scripts/render_report.py`):**

1a. **Add `VIEWS` and `GENERATION_START_EPOCH` to the optional-fields surface.** Update
the module docstring (`:10`) to mention them. Do **not** add to `EXPECTED_KEYS` (`:26`)
— they're optional.

1b. **Compose `META_LINE` when blank.** New helper next to `_coerce_duration_seconds`
(`:304`):

```python
META_LINE_FIELDS = ("CHANNEL", "DURATION", "PUBLISH_DATE", "VIEWS")

def _maybe_compose_meta_line(payload: dict) -> str:
    existing = str(payload.get("META_LINE", "")).strip()
    if existing:
        return existing
    parts = [str(payload.get(k, "")).strip() for k in META_LINE_FIELDS]
    return " · ".join(p for p in parts if p)
```

Call this in `sanitise_payload` (`:372`) before the plaintext-escape loop at `:386`.
Mutate a copy of `data`, or pass the composed value forward via the `clean` dict —
whichever fits the existing style. Make sure the composition happens before
`html.escape` runs at `:387`.

1c. **Auto-fill `GENERATION_DURATION_SECONDS` from `GENERATION_START_EPOCH`.** In
`_build_meta_dict` (`:326`), before the existing `_coerce_duration_seconds` call
(`:336`):

```python
if raw_payload.get("GENERATION_DURATION_SECONDS") in (None, ""):
    start_epoch = raw_payload.get("GENERATION_START_EPOCH")
    if start_epoch not in (None, ""):
        try:
            se = int(start_epoch)
            if se < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise RenderValidationError(
                "RENDER_INVALID_META_JSON",
                "GENERATION_START_EPOCH must be a non-negative integer",
            )
        raw_payload = {**raw_payload,
                       "GENERATION_DURATION_SECONDS": max(0, int(time.time()) - se)}
```

Add `import time` at the top of the file alongside `import json`.

1d. **Add `--output-dir DIR` to `main()`, mutually exclusive with the positional path.**
Use `argparse`:

```python
parser = argparse.ArgumentParser()
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("path", nargs="?")
group.add_argument("--output-dir")
args = parser.parse_args()
```

When `--output-dir` is set, derive the filename from the raw payload:

```python
def _slug_from_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:60] or "video"

def _derived_filename(payload: dict) -> str:
    slug = _slug_from_title(str(payload.get("VIDEO_TITLE", "")))
    hhmmss = datetime.now().strftime("%H%M%S")
    return (f"{payload['GENERATION_DATE']}-{hhmmss}-video-lens_"
            f"{payload['VIDEO_ID']}_{slug}.html")
```

Then call `validate_output_path(output_dir + "/" + filename)` with the existing
single-arg validator — no signature change, no polymorphism. The `.html` suffix check
and `ALLOWED_OUTPUT_ROOT` clamp run identically on the derived path; test bypass
(`VIDEO_LENS_ALLOW_ANY_PATH=1`) behaviour is unchanged for the legacy positional path.

The raw (un-escaped) `VIDEO_TITLE` from `raw_payload` must be used here — see
"Call-ordering contract" above.

**Known trade-off (acknowledge in commit message):** CJK / non-ASCII titles produce an
empty slug and fall back to `video`. Today the LLM at Step 4 could transliterate; the
script can't. Behavioural regression is small (the filename is still uniquely
identified by `VIDEO_ID` and date+time), and worth the determinism.

1e. **Change the final stdout line.** `:488`:

```python
print(f"OUTPUT_PATH: {result}")
```

No consumer parses the existing `Rendered → {result}` text — verified by grep against
the repo. Update `scripts/yt_template_dev.py:145` to match for cosmetic parity.

**Verification for Step 1 (run before moving on):**

```bash
pytest tests/test_e2e.py -v -k "not slow"
```

All existing tests must still pass — the new behaviours are opt-in. Then add the new
renderer tests from "Tests" below and rerun.

---

### Step 2 — Create `preflight.py`

Path: `skills/video-lens/scripts/preflight.py`. Shape:

```python
#!/usr/bin/env python3
"""Pre-flight checks for video-lens: URL→ID, language mapping, duplicate detection, start epoch.

Usage: python3 preflight.py URL_OR_ID [LANG_REQUEST]

URL_OR_ID may be:
- A YouTube URL (watch / youtu.be / embed / live)
- A bare 11-character video ID
- A bare ID followed by a 2–3 char language hint (e.g. "dQw4w9WgXcQ es") — passed as a single argv

Stdout on success (lines that apply only):
    VIDEO_ID: <11 chars>
    LANG_CODE: <code or empty>
    START_EPOCH: <int>
    DUPLICATE_PATH: <absolute>   # newest match by mtime, if any

Stderr + non-zero exit on:
    ERROR:SHORTS_NOT_SUPPORTED <url>
    ERROR:INVALID_INPUT <reason>
"""
import argparse
import pathlib
import re
import sys
import time
from urllib.parse import parse_qs, urlparse

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
REPORTS_DIR = pathlib.Path.home() / "Downloads" / "video-lens" / "reports"

LANGUAGE_MAP = {
    "english": "en", "spanish": "es", "french": "fr", "german": "de",
    "japanese": "ja", "portuguese": "pt", "italian": "it",
    "chinese": "zh", "korean": "ko", "russian": "ru",
}
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
YOUTUBE_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}


def extract_video_id(raw: str) -> tuple[str, str | None]:
    """Return (video_id, error_code). error_code is None on success."""
    raw = raw.strip()
    if VIDEO_ID_RE.fullmatch(raw):
        return raw, None

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if "/shorts/" in parsed.path:
        return "", "SHORTS_NOT_SUPPORTED"

    if host in YOUTUBE_SHORT_HOSTS:
        candidate = parsed.path.strip("/").split("/", 1)[0]
    elif host in YOUTUBE_HOSTS:
        if parsed.path == "/watch":
            candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        elif parsed.path.startswith("/embed/") or parsed.path.startswith("/live/"):
            parts = parsed.path.strip("/").split("/", 2)
            candidate = parts[1] if len(parts) >= 2 else ""
        else:
            return "", "INVALID_INPUT"
    else:
        return "", "INVALID_INPUT"

    if VIDEO_ID_RE.fullmatch(candidate):
        return candidate, None
    return "", "INVALID_INPUT"


def map_language(raw: str) -> str:
    """Map a name (english) or a short code (en) to a code. No format validation.

    Unknown codes pass through; fetch_transcript.py already emits LANG_WARN: when
    youtube-transcript-api rejects them, so a second validation layer here is dead weight.
    """
    raw = raw.strip().lower()
    if not raw:
        return ""
    return LANGUAGE_MAP.get(raw, raw)


def find_duplicate(video_id: str) -> pathlib.Path | None:
    if not REPORTS_DIR.is_dir():
        return None
    matches = sorted(
        REPORTS_DIR.glob(f"*video-lens*{video_id}*.html"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return matches[0] if matches else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url_or_id")
    parser.add_argument("lang_request", nargs="?", default="")
    args = parser.parse_args()

    # If url_or_id contains a space, treat the second token as the language hint.
    raw = args.url_or_id.strip()
    lang_request = args.lang_request
    if " " in raw and not lang_request:
        first, _, rest = raw.partition(" ")
        raw, lang_request = first, rest.strip()

    video_id, err = extract_video_id(raw)
    if err == "SHORTS_NOT_SUPPORTED":
        print(f"ERROR:SHORTS_NOT_SUPPORTED {raw}", file=sys.stderr)
        return 1
    if err:
        print(f"ERROR:INVALID_INPUT could not extract video id from {raw!r}", file=sys.stderr)
        return 1

    lang_code = map_language(lang_request)
    start_epoch = int(time.time())
    dup = find_duplicate(video_id)

    print(f"VIDEO_ID: {video_id}")
    print(f"LANG_CODE: {lang_code}")
    print(f"START_EPOCH: {start_epoch}")
    if dup is not None:
        print(f"DUPLICATE_PATH: {dup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Note on language validation (changed from earlier draft):** dropped the BCP-47 regex.
It accepted nonsense like `xy-Z` and rejected nothing the fetcher wouldn't already
catch via `LANG_WARN:`. Map known names → codes; pass everything else through.

**Verification:** add and run the preflight tests from "Tests" below.

---

### Step 3 — Rewrite affected SKILL.md sections

Target line counts after this step:

| Section | Before | After |
|---|---:|---:|
| Step 1 (lines 30–56) | 27 | ~10 |
| Step 2 preamble + transcript (lines 58–80) | 23 | ~10 |
| Step 2b (lines 93–105) | 13 | ~7 |
| Step 4 (lines 171–178) | 8 | 0 (deleted) |
| Step 5 (lines 180–247) | 68 | ~50 |
| Step 6 (lines 249–259) | 11 | ~5 |
| Step 7 (lines 261–269) | 9 | ~4 |

Each Bash step uses the **existing** `_sd=…` discovery one-liner — no wrapper. Per
016/P3.7, this duplication is irreducible across Bash tool calls; live with it. Use this
template at the top of each Bash command:

```bash
_sd=$(for d in ~/.agents ~/.claude ~/.copilot ~/.gemini ~/.cursor ~/.windsurf ~/.opencode ~/.codex; do [ -d "$d/skills/video-lens/scripts" ] && echo "$d/skills/video-lens/scripts" && break; done); [ -z "$_sd" ] && echo "Scripts not found — install from github.com/kar2phi/video-lens (see Bundled scripts above)" && exit 1
```

#### New Step 1 (replaces lines 30–56)

```markdown
### 1. Preflight — extract video ID, language, and check for duplicates

Run preflight, then read four prefixed lines from its stdout. Save `VIDEO_ID`,
`LANG_CODE`, and `START_EPOCH` for later steps.

\`\`\`bash
{_sd discovery}; python3 "$_sd/preflight.py" "$USER_INPUT"
\`\`\`

Substitute `$USER_INPUT` with the user's URL/ID and any language hint as a single
argument (preflight splits internally on the space).

- On `ERROR:SHORTS_NOT_SUPPORTED`: report the limitation and stop.
- On `ERROR:INVALID_INPUT`: report the message and stop.
- If a `DUPLICATE_PATH:` line is present, tell the user: "Note: an existing report for
  this video was found — `{filename}`. Proceeding with a fresh summary." This is a
  non-blocking notification.
```

#### New Step 2 / 2b (replaces lines 58–105)

Drop the language mapping table, the `date +%s` capture, and the BCP-47 explanation.
Keep the Long-videos warning and the `LANG_WARN` handling note.

```markdown
### 2. Fetch the transcript

\`\`\`bash
{_sd discovery}; python3 "$_sd/fetch_transcript.py" "$VIDEO_ID" "$LANG_CODE"
\`\`\`

(Reads `VIDEO_ID` and `LANG_CODE` from Step 1's output.)

[Keep the existing "If the output is saved to a file" paragraph verbatim.]
[Keep the existing "Long videos" paragraph verbatim.]
[Keep the LANG_WARN handling sentence.]

### 2b. Fetch enriched metadata

\`\`\`bash
{_sd discovery}; python3 "$_sd/fetch_metadata.py" "$VIDEO_ID"
\`\`\`

[Keep the existing "Parse the prefixed output lines" guidance verbatim.]
```

#### New Step 3 (modify line 117 only)

Delete the sentence that instructs the LLM to build `META_LINE`. Replace with:

> `META_LINE` is composed by the renderer from `CHANNEL` / `DURATION` / `PUBLISH_DATE`
> / `VIEWS` — provide those four fields in Step 5.

Everything else in Step 3 (content quality guidance, Quality Guidelines, Length
adjustments, Tags, Untrusted input) is untouched.

#### Delete Step 4 entirely (lines 171–178)

The renderer derives the filename from `VIDEO_ID`, `VIDEO_TITLE`, and `GENERATION_DATE`
when `--output-dir` is passed.

#### New Step 5 (replaces lines 180–247)

```markdown
### 4. Render the report

Pipe the JSON payload to the renderer with `--output-dir`; the renderer derives the
filename. Capture the `OUTPUT_PATH:` line from stdout.

Fields to provide:

| Key | Value |
|---|---|
| `VIDEO_ID` | YouTube video ID |
| `VIDEO_TITLE` | Plain text |
| `VIDEO_URL` | Full original or canonical URL |
| `SUMMARY` | Plain text |
| `TAKEAWAY` | Plain text |
| `KEY_POINTS` | `<li>` tags per the format spec |
| `OUTLINE` | `<li>` tags per the format spec |
| `DESCRIPTION_SECTION` | Empty string, or `<details>…</details>` block |
| `TAGS` | JSON array of 3–5 lowercase tags |
| `CHANNEL` | Plain text |
| `DURATION` | Plain text (e.g. `1h 16m`) |
| `PUBLISH_DATE` | Plain text (e.g. `Dec 5 2025`) |
| `VIEWS` | Plain text (e.g. `1.2M views`) |
| `GENERATION_DATE` | `DATE:` line from Step 2 |
| `GENERATION_START_EPOCH` | `START_EPOCH` from Step 1 |
| `AGENT_MODEL` | Runtime model identity (see existing guidance) |

The renderer:
- Composes `META_LINE` from `CHANNEL` / `DURATION` / `PUBLISH_DATE` / `VIEWS`.
- Computes `GENERATION_DURATION_SECONDS` from `GENERATION_START_EPOCH`.
- Derives the filename `YYYY-MM-DD-HHMMSS-video-lens_<VIDEO_ID>_<slug>.html`.
- Prints `OUTPUT_PATH: /absolute/path.html` on stdout.

\`\`\`bash
{_sd discovery}; OUTPUT_PATH=$(cat <<'JSON' | python3 "$_sd/render_report.py" --output-dir ~/Downloads/video-lens/reports/ | grep '^OUTPUT_PATH:' | cut -d' ' -f2-
{… JSON payload …}
JSON
)
\`\`\`

[Keep the existing Tag allowlist + Common rejection causes paragraphs verbatim.]
```

#### New Step 6 / 7 (replaces lines 249–269)

```markdown
### 5. Serve and open

\`\`\`bash
{_sd discovery}; bash "$_sd/serve_report.sh" "$OUTPUT_PATH" "$HOME/Downloads/video-lens"
\`\`\`

Stop if `serve_report.sh` emits any `ERROR:` line or fails to print `HTML_REPORT:`.

### 6. Rebuild the gallery index

\`\`\`bash
{gallery_sd discovery — same 8-agent loop but looking for video-lens-gallery/scripts}; python3 "$_sd/build_index.py" --dir "$HOME/Downloads/video-lens" || echo "WARNING: index rebuild failed"
\`\`\`

Index failure is non-fatal — continue to the final message.
```

(Renumber Steps 5/6/7 → 4/5/6 throughout SKILL.md to reflect the deletion of old Step 4.)

#### Output / Error Handling sections (lines 271–298)

Untouched, except:

- Update the Error Handling table to add: `ERROR:SHORTS_NOT_SUPPORTED`,
  `ERROR:INVALID_INPUT` (preflight). Action: report and stop.

---

### Step 4 — Tests

Add to `tests/test_e2e.py`. All fast; no network. Place after the existing renderer tests.

```python
import pathlib, time
from preflight import (  # type: ignore
    extract_video_id, map_language, find_duplicate,
)

# --- preflight ---

@pytest.mark.parametrize("inp,expected", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?t=30", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
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
    ("Spanish", "es"), ("english", "en"), ("fr", "fr"),
    ("", ""), ("klingon", "klingon"),  # unknown passes through (fetch_transcript handles via LANG_WARN)
])
def test_preflight_maps_language_names(inp, expected):
    assert map_language(inp) == expected

def test_preflight_main_splits_argv_on_space(monkeypatch, capsys, tmp_path):
    """When LANG_REQUEST is folded into url_or_id as 'id es', preflight must split."""
    import preflight  # type: ignore
    monkeypatch.setattr(preflight, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["preflight.py", "dQw4w9WgXcQ es"])
    rc = preflight.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "VIDEO_ID: dQw4w9WgXcQ" in out
    assert "LANG_CODE: es" in out

def test_preflight_emits_newest_duplicate_only(tmp_path, monkeypatch):
    import preflight  # type: ignore
    fake_reports = tmp_path / "Downloads" / "video-lens" / "reports"
    fake_reports.mkdir(parents=True)
    older = fake_reports / "2025-01-01-000000-video-lens_dQw4w9WgXcQ_old.html"
    newer = fake_reports / "2025-06-01-000000-video-lens_dQw4w9WgXcQ_new.html"
    older.write_text("x"); newer.write_text("x")
    import os
    os.utime(older, (1_700_000_000, 1_700_000_000))
    os.utime(newer, (1_750_000_000, 1_750_000_000))
    monkeypatch.setattr(preflight, "REPORTS_DIR", fake_reports)
    assert preflight.find_duplicate("dQw4w9WgXcQ") == newer

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
    assert clean["META_LINE"].count("·") == 2  # 3 non-empty parts joined → 2 separators

def test_renderer_keeps_meta_line_when_supplied():
    payload = new_shape_payload(META_LINE="Custom Line", VIEWS="ignored")
    clean = sanitise_payload(payload, "/tmp/x.html")
    assert clean["META_LINE"] == "Custom Line"

def test_renderer_computes_duration_from_start_epoch(monkeypatch):
    """Pin time.time() so the assertion is exact, not '>= 7'."""
    fixed_now = 1_750_000_007
    monkeypatch.setattr(time, "time", lambda: fixed_now)
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
```

Update `new_shape_payload` (`test_e2e.py:68`) to include `VIEWS`:

```python
"VIEWS": "1.0M views",
```

(Required for `test_renderer_composes_meta_line_from_parts` to match the expected
4-part `META_LINE`.)

---

### Step 5 — Update `scripts/yt_template_dev.py`

Single edit, line 145:

```python
print(f"OUTPUT_PATH: {result}")
```

---

### Step 6 — End-to-end verification

1. **Fast suite:**
   ```bash
   pytest tests/test_e2e.py -v -k "not slow"
   ```
   All existing tests + all new tests pass.

2. **Deploy local:**
   ```bash
   task install-skill-local AGENT=claude
   ```

3. **Live skill run:**
   ```bash
   pytest tests/test_e2e.py::test_claude_session -v
   ```

4. **Manual smoke (5 minutes):**
   - Feed a long YouTube URL with chapters. Confirm:
     - filename matches `YYYY-MM-DD-HHMMSS-video-lens_<id>_<slug>.html` under
       `~/Downloads/video-lens/reports/`
     - `META_LINE` in the report header is correctly assembled with ` · ` separators
     - info modal shows non-empty `durationSeconds` and the correct agent model
     - browser opens to `http://localhost:8765/reports/<filename>.html` automatically
   - Run the same URL a second time. Confirm:
     - duplicate note appears in the chat: `Note: an existing report for this video was
       found — …`
     - a fresh report is still generated
   - Feed a YouTube URL with a CJK-only title (Japanese / Chinese / Korean). Confirm
     filename slug = `video` and no error.
   - Feed a YouTube Shorts URL. Confirm the skill stops with the Shorts-not-supported
     message and no report is created.

---

## Rollback plan

The new SKILL.md hard depends on the new renderer behaviour (`META_LINE` compose,
`--output-dir`, `OUTPUT_PATH:` stdout). The two commits are **coupled in the forward
direction** — old SKILL.md works against the new renderer, but the new SKILL.md does
not work against the old renderer.

- If `preflight.py` regresses: revert the preflight commit alone. SKILL.md falls back to
  needing the inline URL/lang/dup logic — but since SKILL.md was rewritten to call
  preflight, you must also revert the SKILL.md commit.
- If the renderer regresses: revert BOTH the renderer commit AND the SKILL.md commit.
- If only SKILL.md is wrong: revert SKILL.md alone; scripts are backward-compatible.

Suggested commit order (one PR per commit is fine):

1. `feat(renderer): auto-compose META_LINE, compute duration, derive filename via --output-dir`
2. `feat(scripts): add preflight.py for URL/lang/dup checks`
3. `refactor(skill): move mechanical glue out of SKILL.md`
4. `test: cover preflight and renderer extensions`

---

## Open issues to flag during implementation

1. **`VIDEO_LENS_META.filename` ordering** — the meta JSON is built at
   `render_report.py:350` using `output_path`. The `--output-dir` derivation must
   complete before `_build_meta_dict` runs. Derive in `main()` before calling
   `render_from_payload`. (Pinned in "Call-ordering contract" above.)
2. **Slug from raw vs escaped title** — `sanitise_payload` HTML-escapes `VIDEO_TITLE` at
   `:387`. The slug must use the raw value. Compute the slug from the raw payload before
   sanitisation. (Pinned in "Call-ordering contract" above.)

---

## Expected outcome

- `SKILL.md`: 299 → ~225 lines (~25% smaller)
- Mechanical paths (URL parsing, language map, duplicate detection, filename slugging,
  META_LINE composition, duration math) become deterministic and unit-testable
- New script: `preflight.py` (~90 LOC)
- Renderer grows by ~60 LOC (META_LINE composer, duration auto-fill, `--output-dir`
  derived filename, slug)
- Test suite grows by ~13 new tests, all fast
- **Net repo LOC: ~+130** — the win is testability and prompt-context reduction, not
  code shrinkage
- **Known trade-off:** CJK / non-ASCII titles slug to `video` (LLM-side transliteration
  is no longer available). Filename remains uniquely identified by `VIDEO_ID` and
  date+time.
- No new error codes beyond `ERROR:SHORTS_NOT_SUPPORTED` and `ERROR:INVALID_INPUT`
  (preflight only).
