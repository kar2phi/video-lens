# Error Hardening & Duplicate Detection (QW4, QW5)

## Context

Following the competitive analysis in concepts/010, this report documents the implementation of two quick wins: structured error codes (QW4) and duplicate report detection (QW5). QW1–QW3 and QW6 were challenged and dropped. This is the implementation record.

---

## Decisions

### QW1 (Shorts), QW2 (Caption type), QW3 (Proxy) — Dropped

All three were deferred after challenge:

- **QW1 (Shorts):** The URL parser change is trivial, but the output format is wrong for 60-second content. The current report template (2–4 sentence summary, 3–8 key points with analytical paragraphs) would dwarf the source material. Deferred until a condensed template variant exists.
- **QW2 (Caption type):** YouTube's auto-captions have improved significantly. The `is_generated` flag signals lower trust but doesn't improve quality. The structural fix is MT2 (Whisper fallback); a metadata label is noise.
- **QW3 (Proxy):** The primary user is a home Mac user — not behind a firewall blocking YouTube. The `HTTPS_PROXY` approach requires users to manage their own proxy, which is non-trivial. IP blocking errors are now surfaced clearly by QW4 with actionable guidance.

### QW6 (Script discovery consolidation) — Dropped

The proposed solution required the LLM to hold a resolved path in working memory and perform text substitution on command templates across separate shell invocations. No Claude Code skill uses this pattern. The discovery loop is 8 `[ -d ]` stat calls repeated 4 times — negligible overhead (<50ms). Adding a Step 0 would add more latency (tool-call round-trip) than it saves. Dropped.

---

## Implementation

### QW4 — Structured Error Codes

**Problem:** Both scripts emitted free-text errors (`TRANSCRIPT_ERROR: ...`, `YTDLP_ERROR: ...`) that required the LLM to string-match for recovery decisions. No typed dispatch was possible.

**Files changed:** `fetch_transcript.py`, `fetch_metadata.py`, `SKILL.md`

**Approach — `fetch_transcript.py`:**

Used defensive imports to guard against library renames across versions:

```python
try:
    from youtube_transcript_api import (
        TranscriptsDisabled, VideoUnavailable, NoTranscriptFound, InvalidVideoId,
    )
except ImportError:
    TranscriptsDisabled = VideoUnavailable = NoTranscriptFound = InvalidVideoId = None
```

The exception handler iterates a priority-ordered map and falls through to `ERROR:TRANSCRIPT_FETCH_FAILED` if no class matches (including when all imports failed):

```python
_error_map = [
    (TranscriptsDisabled,  "ERROR:CAPTIONS_DISABLED"),
    (VideoUnavailable,     "ERROR:VIDEO_UNAVAILABLE"),
    (AgeRestricted,        "ERROR:AGE_RESTRICTED"),
    ...
    (YouTubeRequestFailed, "ERROR:NETWORK_ERROR"),
]
code = "ERROR:TRANSCRIPT_FETCH_FAILED"
for cls, mapped_code in _error_map:
    if cls is not None and isinstance(e, cls):
        code = mapped_code
        break
print(f"{code}: {e}")
```

The `ImportError` for the library itself was also updated to `ERROR:LIBRARY_MISSING`.

**Approach — `fetch_metadata.py`:**

The four existing `YTDLP_ERROR:` prefixes were renamed for consistency:

| Before | After |
|--------|-------|
| `YTDLP_ERROR: yt-dlp not installed` | `ERROR:YTDLP_MISSING: ...` |
| `YTDLP_ERROR: yt-dlp timed out` | `ERROR:YTDLP_TIMEOUT: ...` |
| `YTDLP_ERROR: yt-dlp produced no output` | `ERROR:YTDLP_NO_OUTPUT: ...` |
| `YTDLP_ERROR: {json decode error}` | `ERROR:YTDLP_JSON_ERROR: ...` |

Human-readable messages were preserved after the code.

**Approach — `SKILL.md`:**

The error handling table was rewritten with 15 typed codes. The distinction between fatal (stop) and non-fatal (continue with degraded metadata) is now explicit per-code. Two key design choices:

1. Prefixes are **advisory context** for user-facing messages, not a routing mechanism — exit code 1 remains the sole stop signal. This avoids dual-channel error signaling.
2. `ERROR:IP_BLOCKED` suggests trying a different network, not a `YT_PROXY` env var (which wasn't implemented).

---

### QW5 — Duplicate Detection

**Problem:** Re-summarising the same video silently created a new report, wasting 30–60 seconds of LLM work.

**Original proposal:** Check at Step 4 (after analysis), ask blocking question.

**Two challenges resolved before implementation:**

1. **Check runs too late.** Moved to Step 1, immediately after video ID extraction, before any network calls. Zero wasted work.
2. **Blocking question punishes intentional re-runs.** Changed to a non-blocking informational note: the pipeline continues by default; the user can ask to open the existing report if they want it.

**Final implementation in `SKILL.md` Step 1:**

```bash
ls ~/Downloads/video-lens/reports/*video-lens*VIDEO_ID*.html 2>/dev/null
```

The glob pattern `*video-lens*VIDEO_ID*` is tighter than the original `*VIDEO_ID*` proposal — limits matches to video-lens report filenames, avoids collisions with future cache files (MT1).

On match: print a non-blocking note (`Note: an existing report for this video was found — {filename}. Proceeding with a fresh summary.`), then continue.

---

## Results

### Tests

4/5 tests pass: `test_template_placeholders`, `test_render_and_serve`, `test_build_index`, `test_full_pipeline`. The 5th test (`test_claude_session`) fails due to a pre-existing path mismatch: the test globs `~/Downloads/video-lens/` non-recursively, but reports are saved to `~/Downloads/video-lens/reports/`. This failure predates this change.

### Error output before/after

```
# Before
TRANSCRIPT_ERROR: Could not retrieve a transcript for the video ...

# After
ERROR:VIDEO_UNAVAILABLE: Could not retrieve a transcript for the video ...
```

```
# Before
YTDLP_ERROR: yt-dlp not installed — run: brew install yt-dlp or pip install yt-dlp

# After
ERROR:YTDLP_MISSING: yt-dlp not installed — run: brew install yt-dlp or pip install yt-dlp
```

---

## Open Issues

- **`test_claude_session` glob mismatch**: The test searches `~/Downloads/video-lens/*.html` but reports live in `~/Downloads/video-lens/reports/*.html`. Fix: change test glob to `reports/????-??-??-??????-video-lens_*.html` or use `**/*.html`.
- **`IpBlocked`/`RequestBlocked` guidance**: Currently says "try a different network or configure a proxy" — no proxy mechanism exists. If QW3 is ever implemented, update this message to reference the specific env var.
