# video-lens Skill Challenge Report

Date: 2026-05-15

## Scope

This audit challenges the current `video-lens` skill with emphasis on recent uncommitted changes and on reducing complexity without stripping useful capability.

Reviewed areas:

- `skills/video-lens/SKILL.md`
- `skills/video-lens/scripts/*.py`
- `skills/video-lens/scripts/serve_report.sh`
- `skills/video-lens/template.html`
- `tests/test_e2e.py`
- Related install/dev/gallery touchpoints that affect the main skill

Recent uncommitted changes reviewed:

- `Taskfile.yml`
- `scripts/yt_template_dev.py`
- `skills/video-lens/SKILL.md`
- `skills/video-lens/scripts/render_report.py`
- `skills/video-lens/scripts/serve_report.sh`
- `skills/video-lens/template.html`
- `tests/test_e2e.py`
- New `concepts/013-skills-sh-audit-mitigation.md`

Verification performed:

- `python3 -m py_compile skills/video-lens/scripts/render_report.py skills/video-lens/scripts/fetch_transcript.py skills/video-lens/scripts/fetch_metadata.py skills/video-lens-gallery/scripts/build_index.py scripts/yt_template_dev.py` - passed.
- `pytest -q -m 'not slow'` - failed because `pytest` is not installed on the default PATH.
- `python3 -m pytest -q -m 'not slow'` - failed because default Python has no `pytest`.
- `/private/tmp/video-lens-test-venv/bin/python -m pytest tests/test_e2e.py -v -m 'not slow'` inside the sandbox - failed at `serve_report.sh` because binding `127.0.0.1:8765` is sandbox-blocked.
- The same venv command with localhost binding allowed - passed: `13 passed, 2 deselected`.

## Criticality and Complexity Scale

Criticality:

- Critical: can break normal skill operation, create serious security exposure, or invalidate the report.
- High: likely user-visible failure, security issue, or major quality regression.
- Medium: meaningful reliability, maintainability, or quality issue with workaround.
- Low: polish, clarity, test hygiene, or low-probability edge case.

Complexity:

- XS: wording or one-line fix.
- S: small localized edit.
- M: focused change across a few files or tests.
- L: architectural change or new workflow.

## Executive Verdict

The recent direction is mostly correct: security and correctness are being moved into `render_report.py`, typed errors are replacing stringly failures, and the final success marker is now gated on actual serving. Those are the right boundaries.

The main problem is that the prompt absorbed too much implementation detail at the same time. `SKILL.md` now explains renderer internals, model telemetry, timing, success-gating, allowlists, and a long error table. That makes the skill safer, but also more fragile because the agent must hold more mechanical state in working memory.

The best simplification path is not to remove report quality, the HTML template, yt-dlp enrichment, or sanitizer hardening. The best path is to keep those capabilities and move more deterministic work into scripts.

Recommended north star:

- Keep `SKILL.md` focused on user intent, content-quality rules, and fatal/non-fatal decisions.
- Move filename generation, generated timestamps, `VIDEO_LENS_META` construction, metadata validation, and sanitization into scripts.
- Collapse recent prompt additions that duplicate renderer policy into short contracts: "plain text fields are escaped; HTML fields are allowlist-sanitized; renderer errors are fatal."

## Recent Changes Assessment

| Area | Assessment | Criticality | Complexity |
|---|---|---:|---:|
| `SKILL.md` hardening | Good intent, but prompt grew by roughly 125 lines and now duplicates code-level policy. It protects against prompt injection, but it also increases execution burden. | Medium | M |
| `render_report.py` sanitizer | High-value addition. Per-key escaping, URL validation, output path clamping, and JSON meta escaping are the strongest recent improvements. | High | M |
| `serve_report.sh` PID/nohup/bind change | Mostly good: less broad killing, detached server, localhost-only binding. Risk remains around stale servers and low diagnostics. | Medium | S |
| `template.html` info modal/export footer | Useful if provenance matters, but it forced `modelName`, `generatedAt`, and `durationSeconds` into the prompt. That is a bad complexity trade unless the script computes them. | Medium | S |
| `tests/test_e2e.py` sanitizer coverage | Good coverage for new hardening. However, slow tests still have a stale `YTDLP_ERROR` check and some tests bypass the CLI sanitizer path. | Medium | S |
| `Taskfile.yml` serve task | Reintroduces broad `lsof` killing and all-interface binding, diverging from `serve_report.sh` hardening. | Medium | XS |
| `scripts/yt_template_dev.py` | Still duplicates raw template substitution and has stale plain-text/entity assumptions. This is now a parallel renderer. | Medium | S |

## Findings

### F1 - Manual install path is now broken

Criticality: High

Complexity: S

Evidence:

- `README.md` manual install downloads only `SKILL.md` and `template.html`.
- The current skill requires `scripts/fetch_transcript.py`, `scripts/fetch_metadata.py`, `scripts/render_report.py`, and `scripts/serve_report.sh`.
- `SKILL.md` now says scripts are bundled, and every runtime command fails if `./scripts` is absent.

Impact:

Manual install users get `Scripts not found` even after following the README. This is a direct install regression caused by the earlier script extraction plus recent hardening.

Recommendation:

- Update manual install to download the whole skill directory, not individual files.
- Prefer `npx skills add kar2phi/video-lens` as the only simple manual path.
- If keeping curl install, include all four scripts and `chmod +x serve_report.sh`.

Suggested README fix:

```bash
npx skills add kar2phi/video-lens
pip install youtube-transcript-api yt-dlp
```

Or remove Option B entirely if it cannot reliably install directories.

### F2 - `render()` is still an unsafe public bypass around sanitization

Criticality: Medium

Complexity: M

Evidence:

- CLI path calls `validate_output_path()`, `sanitise_payload()`, then `render()`.
- Imported callers can call `render()` directly with unsanitized values.
- Tests and `scripts/yt_template_dev.py` still use raw or direct rendering patterns.

Impact:

The security boundary is correct only for CLI usage. Future developer tooling or tests may accidentally reintroduce raw substitution. This is exactly the kind of drift the new sanitizer is meant to prevent.

Recommendation:

- Rename raw substitution to `_render_clean_payload()`.
- Make public `render()` validate and sanitize by default.
- Add a separate explicit helper for tests if needed, e.g. `render_prevalidated()`, with a docstring saying it expects already-sanitized data.
- Update `yt_template_dev.py` to call the same renderer path as production.

### F3 - Dev renderer duplicates production rendering and is now stale

Criticality: Medium

Complexity: S

Evidence:

- `scripts/yt_template_dev.py` manually reads `template.html`, loops over `CONTENT`, and replaces placeholders.
- Production now has escaping, allowlists, output path policy, unreplaced placeholder errors, and metadata JSON escaping.
- The sample data includes HTML entities in fields now documented as plain text, e.g. `SUMMARY` and `TAKEAWAY`.

Impact:

The dev preview can pass while production render fails, or production can escape differently than the preview. That weakens template iteration and can hide regressions.

Recommendation:

- Replace raw substitution in `yt_template_dev.py` with `render_report.sanitise_payload()` plus `render_report.render_prevalidated()`.
- Better: make the dev script invoke `render_report.py` through the same CLI interface used by the skill.
- Update sample plain-text fields to use normal quotes and dashes, not HTML entities.

### F4 - `README.md` and docs are stale after reports moved into `reports/`

Criticality: Medium

Complexity: XS

Evidence:

- README says Raycast reports are saved to `~/Downloads/`.
- Current skill saves to `~/Downloads/video-lens/reports/`.
- Repo layout omits `skills/video-lens/scripts/`.

Impact:

Install and usage docs no longer match the actual source of truth. This matters because the skill is delivered as files; missing a directory breaks runtime.

Recommendation:

- Update all save-path references to `~/Downloads/video-lens/reports/`.
- Add `skills/video-lens/scripts/` to the repo layout.
- Remove or rewrite any install path that does not include scripts.

### F5 - `test_full_pipeline` still checks old yt-dlp error prefix

Criticality: Medium

Complexity: XS

Evidence:

- `fetch_metadata.py` now emits `ERROR:YTDLP_*`.
- `tests/test_e2e.py` slow test still uses `metadata_ok = "YTDLP_ERROR" not in r.stdout`.

Impact:

If yt-dlp is missing or fails, the slow test incorrectly treats the output as successful and then asserts for `YTDLP_CHANNEL`. This is a hidden slow-test failure.

Recommendation:

Change the check to:

```python
metadata_ok = not any(line.startswith("ERROR:YTDLP_") for line in r.stdout.splitlines())
```

Also assert that non-fatal yt-dlp errors are handled intentionally.

### F6 - Fetch-time transcript failures are not fully typed

Criticality: Medium

Complexity: S

Evidence:

- `fetch_transcript.py` maps exceptions around `YouTubeTranscriptApi().list(video_id)`.
- It does not wrap `transcript_obj.fetch()`.

Impact:

Network errors, API changes, or transcript retrieval failures after selection can produce raw tracebacks instead of `ERROR:*` codes. That bypasses the error table and creates poor user-facing behavior.

Recommendation:

- Wrap `transcript_obj.fetch()` in the same typed mapping style.
- Add a fallback `ERROR:TRANSCRIPT_FETCH_FAILED`.
- Add a test with a mocked transcript object whose `fetch()` raises.

### F7 - Metadata failure policy conflicts with `VIDEO_TITLE` requiredness

Criticality: Medium

Complexity: S

Evidence:

- Error handling says metadata extraction failure should proceed with whatever metadata is available.
- `render_report.py` requires non-empty `VIDEO_TITLE`.
- `fetch_transcript.py` returns empty title on HTML metadata failure.

Impact:

In the intended degraded path, a missing title can still make rendering fatal. The agent may be told to proceed, only to hit `ERROR:RENDER_EMPTY_CONTENT`.

Recommendation:

- Either make `VIDEO_TITLE` optional with a fallback like `YouTube video <VIDEO_ID>`, or make metadata title failure explicitly fatal.
- Prefer fallback title. It preserves graceful degradation and reduces prompt branching.

### F8 - Generation duration is inaccurate and prompt-heavy

Criticality: Medium

Complexity: S

Evidence:

- `START_EPOCH` is captured after transcript fetch.
- The prompt says this makes duration cover "the full workflow", but it excludes transcript fetching.
- The agent must remember `START_EPOCH`, run another time command, compute subtraction, and fill `durationSeconds`.

Impact:

This adds execution complexity for a low-value metric and is easy for agents to forget or calculate incorrectly.

Recommendation:

Choose one:

- Drop `durationSeconds` entirely. Keep only `generatedAt`.
- Or capture `START_EPOCH` before Step 2 and pass it to the renderer as `START_EPOCH`, letting the script compute duration.

Best simplification: drop `durationSeconds`. It is not worth the prompt complexity.

### F9 - `modelName` is Claude-specific in a multi-agent skill

Criticality: Medium

Complexity: XS

Evidence:

- `SKILL.md` asks for "your current Claude model ID".
- The skill advertises support for multiple agents: Claude, Codex, Gemini, Cursor, Windsurf, Opencode, Copilot, and generic `.agents`.

Impact:

Non-Claude agents are instructed to invent or mislabel a Claude model ID. This creates inaccurate provenance.

Recommendation:

- Rename to `agentModel` and make it optional.
- Wording: "current model identifier if the runtime exposes one; otherwise empty string."
- Or remove the field from the required path and omit it from the modal if absent.

### F10 - Prompt-level allowlist duplicates renderer policy

Criticality: Medium

Complexity: S

Evidence:

- `SKILL.md` has a detailed tag/attribute allowlist.
- `render_report.py` has the real allowlist.

Impact:

Two sources of truth can drift. The agent does not need to understand every accepted attribute if the renderer enforces the actual boundary.

Recommendation:

Replace the detailed allowlist table in `SKILL.md` with a short contract:

```markdown
Plain-text fields must contain no HTML. HTML-bearing fields may only use the structures shown in the examples below. `render_report.py` validates and sanitizes them; if it returns `ERROR:RENDER_DISALLOWED_HTML`, simplify the field to the documented example structure and retry once.
```

Keep examples for `KEY_POINTS`, `OUTLINE`, and `DESCRIPTION_SECTION`. Remove exhaustive tag policy from the prompt.

### F11 - `VIDEO_LENS_META` construction should not be agent-owned

Criticality: Medium

Complexity: M

Evidence:

- The agent manually builds a nested JSON string with video ID, title, channel, dates, tags, keywords, filename, model, timestamp, and duration.
- Renderer only validates that the metadata is JSON object, not that it matches the report.

Impact:

The index can contain inconsistent or fabricated metadata even when the visible report is correct. This is especially likely for `channel`, `filename`, `generatedAt`, `durationSeconds`, and `keywords`.

Recommendation:

Move metadata construction into `render_report.py`.

Possible payload shape:

```json
{
  "VIDEO_ID": "...",
  "VIDEO_TITLE": "...",
  "VIDEO_URL": "...",
  "META_LINE": "...",
  "SUMMARY": "...",
  "TAKEAWAY": "...",
  "KEY_POINTS": "...",
  "OUTLINE": "...",
  "DESCRIPTION_SECTION": "",
  "TAGS": ["ai", "hardware"],
  "MODEL_NAME": ""
}
```

Then renderer computes:

- `filename`
- `generatedAt`
- `generationDate`
- `keywords` extracted from `KEY_POINTS`
- `summary` truncation
- `videoId`, `title`, `duration`, `channel`, `publishDate`

This removes the most error-prone Step 5 instructions.

### F12 - Script discovery is repeated and obscures the core workflow

Criticality: Low

Complexity: M

Evidence:

- The same 8-agent discovery loop appears in every major command.
- Prior analysis correctly noted that runtime overhead is negligible.
- The issue is not runtime speed; it is prompt readability and command brittleness.

Impact:

Each long one-liner competes with the actual content task. It also creates more surface area for the agent to mis-edit commands.

Recommendation:

Do not add a separate "Step 0" variable for the agent to remember. Instead, move discovery into a tiny stable runner script or into each script via paths relative to `__file__`.

Lower-complexity option:

- Keep command discovery as-is for now.
- Simplify `render_report.py.find_template()` to first use `Path(__file__).parent.parent / "template.html"`.
- Only fall back to multi-agent search for backwards compatibility.

### F13 - `render_report.py.find_template()` should prefer the adjacent template

Criticality: Low

Complexity: XS

Evidence:

- The script lives in `skills/video-lens/scripts/`.
- `template.html` lives one directory up.
- Current `find_template()` searches home agent directories.

Impact:

This is unnecessary indirection and can pick a different installed template than the script being executed if multiple agent installations differ.

Recommendation:

Prefer:

```python
local_template = pathlib.Path(__file__).resolve().parent.parent / "template.html"
if local_template.exists():
    return local_template
```

Then keep the existing search as fallback.

### F14 - `serve_report.sh` can fail on stale or foreign port ownership with weak diagnostics

Criticality: Medium

Complexity: S

Evidence:

- The script only kills a previous server if its PID file exists and `ps -p "$OLD_PID" -o comm=` matches lowercase `python`.
- If an older video-lens server exists without the PID file, or if the command name is `Python`, the new server fails with `ERROR:SERVE_PORT_FAILED`.
- Server stderr is redirected to `/dev/null`.

Impact:

Users can get a generic port failure with no direct remediation. The recent PID change is safer than broad `lsof`, but it lost a useful recovery path.

Recommendation:

- Write server output to `$PID_DIR/server.log`.
- On failure, print the log tail.
- Check `ps -p "$OLD_PID" -o args=` for `http.server 8765` rather than case-sensitive `comm`.
- Optionally, if port 8765 is occupied and no PID file exists, print the owning process via `lsof` without killing it.

### F15 - `Taskfile.yml` serve task contradicts the hardened server script

Criticality: Medium

Complexity: XS

Evidence:

- New `task serve` kills anything on `PORT` via `lsof`.
- It starts `python3 -m http.server` without `--bind 127.0.0.1`.
- `serve_report.sh` now avoids broad killing and binds to localhost.

Impact:

The dev path and production path have different security and process-management behavior.

Recommendation:

- Either remove `task serve`, or make it call `serve_report.sh`/a shared helper.
- If kept, bind to `127.0.0.1` and avoid killing arbitrary processes.

### F16 - Network transparency statement omits Google Fonts

Criticality: Low

Complexity: XS

Evidence:

- `SKILL.md` says browser network calls are limited to the YouTube iframe API.
- `template.html` loads CSS from `https://fonts.googleapis.com`.

Impact:

The statement is not accurate. This matters because it was added specifically for trust-chain transparency.

Recommendation:

Either:

- Mention Google Fonts explicitly.
- Or self-host/remove external font loading.

Given the skill is a local report viewer, self-hosting or using local fallback fonts is the cleaner privacy posture.

### F17 - Very long transcript handling remains underspecified

Criticality: High

Complexity: M

Evidence:

- `SKILL.md` says to read the entire transcript and not sample.
- There is no bounded strategy when the transcript exceeds context.

Impact:

For very long videos, the agent may silently omit later content, exceed context, or produce a summary that appears complete but is not.

Recommendation:

Add a short failure-safe rule rather than building a full chunking system:

```markdown
If the full transcript cannot fit in context after reading all available batches, produce a partial report only if the user agrees, and state the covered time range in the Summary. Never imply full-video coverage for unread transcript segments.
```

Medium-term option:

- Add a script that splits transcript into timestamped chunks and asks the agent to summarize chunks iteratively. Do this only if long videos are common.

### F18 - The description normalizer in the template is likely dead code now

Criticality: Low

Complexity: XS

Evidence:

- Template JS normalizes malformed `<details>` blocks and `<pre>` descriptions.
- `render_report.py` now rejects structures outside the allowlist before output is written.

Impact:

Dead compatibility code increases template size and mental load. It can also mask mismatches during manual dev rendering.

Recommendation:

Remove the description normalizer once production rendering always goes through the sanitizer.

### F19 - Error table is becoming too large for agent execution

Criticality: Low

Complexity: S

Evidence:

- Error table now has transcript, yt-dlp, renderer, serve, and semantic error rows.
- Many rows map to "report and stop" with nearly identical behavior.

Impact:

Long tables are easy for agents to ignore or misapply. The detail is useful for maintainers but not all of it belongs in the runtime prompt.

Recommendation:

Group errors by prefix:

- `ERROR:YTDLP_*`: warn and continue without enriched metadata.
- `ERROR:RENDER_*`: report and stop.
- `ERROR:SERVE_*`: report and stop.
- Transcript `ERROR:*`: follow the smaller explicit table because user remediation differs.

This keeps behavior without listing every renderer code in the prompt.

### F20 - `fetch_transcript.py` HTML metadata fetch has no timeout

Criticality: Medium

Complexity: XS

Evidence:

- `_fetch_html_metadata()` calls `urllib.request.urlopen(req)` without a timeout.

Impact:

A metadata fetch can hang before transcript retrieval, even though metadata is non-critical.

Recommendation:

Use a short timeout:

```python
html = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", errors="ignore")
```

This keeps fallback behavior and avoids blocking the skill.

### F21 - `fetch_metadata.py` URL linkification can include trailing punctuation

Criticality: Low

Complexity: S

Evidence:

- Regex is `https?://\S+`.

Impact:

Descriptions with URLs followed by `)`, `.`, or `,` can produce broken links.

Recommendation:

Trim common trailing punctuation after matching, or use a small parser helper.

This is lower priority than prompt simplification.

### F22 - Gallery backfill still scans the old flat directory

Criticality: Medium

Complexity: S

Evidence:

- `backfill_meta.py` scans `scan_dir.glob("*video-lens*.html")`.
- Current reports are under `~/Downloads/video-lens/reports/`.

Impact:

Backfill misses reports created by the current main skill.

Recommendation:

Scan both `reports/` and the legacy root, matching `build_index.py`.

### F23 - Gallery skill still has weaker tooling and error handling

Criticality: Medium

Complexity: S

Evidence:

- `video-lens-gallery/SKILL.md` allows only `Bash`, not `Read`.
- It has minimal error handling.
- It depends on `video-lens/scripts/serve_report.sh` without explaining that dependency.

Impact:

The main skill now has stronger lifecycle behavior than the gallery skill that it triggers in Step 7.

Recommendation:

Apply a small prompt-hardening pass to gallery, but do not expand it to the size of the main skill.

Minimum changes:

- `allowed-tools: Bash Read`
- explain dependency on `video-lens`
- grouped error handling
- expanded backfill trigger words

### F24 - Markdown export is useful but not robust Markdown serialization

Criticality: Low

Complexity: M

Evidence:

- Export builds Markdown from `innerText`.
- Titles, key-point headlines, and descriptions are not escaped for Markdown syntax.

Impact:

Reports with brackets, pipes, underscores, or unusual text can produce malformed Markdown. This is a quality issue, not a safety issue.

Recommendation:

Leave it unless Markdown export becomes a primary deliverable. Do not over-engineer now.

### F25 - `Deno` requirement appears stale or over-broad

Criticality: Low

Complexity: XS

Evidence:

- README says Deno is required by yt-dlp.
- The scripts call `yt-dlp` directly and do not call Deno.

Impact:

Users may install unnecessary tooling. It also makes the skill look heavier than it is.

Recommendation:

Either remove Deno from the normal path or clarify it as an optional yt-dlp runtime dependency for specific extractor scenarios, not a video-lens requirement.

### F26 - `SKILL.md` says "original URL" but renderer only accepts HTTPS canonical-supported URLs

Criticality: Low

Complexity: XS

Evidence:

- Step 5 says `VIDEO_URL` can be full original or canonical URL.
- `_extract_youtube_id()` rejects non-HTTPS URLs.

Impact:

If the user gave `http://youtube.com/...`, using the original URL will fail render validation.

Recommendation:

Tell the agent to always pass canonical `https://www.youtube.com/watch?v=<VIDEO_ID>`.

### F27 - The success-gated final response is good; keep it

Criticality: High

Complexity: XS

Evidence:

- `SKILL.md` now requires the final "Report ready" only after seeing `HTML_REPORT: <path>`.
- `serve_report.sh` now emits typed errors before that marker.

Impact:

This prevents false success after truncated reports, missing files, or server failures.

Recommendation:

Keep this behavior. It is worth the prompt complexity. If simplifying, do not remove the gate; just shorten wording. The only implementation work should be an XS prompt compression, not a behavioral change.

### F28 - The renderer-side sanitizer is the correct security boundary; keep it

Criticality: High

Complexity: XS

Evidence:

- Plain-text fields are escaped.
- HTML-bearing fields are allowlist-sanitized.
- `VIDEO_URL` and outline links are tied to `VIDEO_ID`.
- Metadata JSON is reserialized and `</` is escaped.
- Output paths are clamped.

Impact:

This materially reduces the impact of prompt injection and accidental raw HTML emission.

Recommendation:

Keep the sanitizer. Simplify around it, not through it. The only implementation work should be small cleanup around duplicated render paths and prompt wording.

## Highest-Leverage Simplification Plan

### Phase 0 - Fix regressions and stale docs

Criticality: High

Complexity: S

Do these first:

- Fix README manual install so scripts are installed.
- Fix `test_full_pipeline` old `YTDLP_ERROR` check.
- Add timeout to `_fetch_html_metadata()`.
- Wrap `transcript_obj.fetch()` with typed errors.
- Add fallback for empty `VIDEO_TITLE`.
- Align `Taskfile.yml` serve behavior with `serve_report.sh`.

### Phase 1 - Remove prompt-owned telemetry

Criticality: Medium

Complexity: S

Recommended changes:

- Drop `durationSeconds`, or compute it in a script.
- Make `modelName` optional and agent-neutral.
- Let renderer set `generatedAt` if missing.

This removes extra date commands, arithmetic, and model-ID guessing from the prompt.

### Phase 2 - Move metadata assembly into renderer

Criticality: Medium

Complexity: M

Recommended changes:

- Replace `VIDEO_LENS_META` as an agent-built JSON string with simpler payload fields.
- Renderer builds and validates the metadata block.
- Renderer extracts `keywords` from sanitized `KEY_POINTS`.
- Renderer truncates `summary` deterministically.

This is the single best way to reduce Step 5 complexity without losing gallery features.

### Phase 3 - Shrink `SKILL.md`

Criticality: Medium

Complexity: M

Remove or compress:

- Detailed tag allowlist table.
- Repeated renderer error rows.
- Overly detailed telemetry instructions.
- Any text that explains implementation internals already enforced by scripts.

Keep:

- Activation rules.
- Video ID extraction.
- Transcript language behavior.
- Content quality guidance.
- Examples for HTML-bearing fields.
- Success marker gate.
- Grouped error policy.

### Phase 4 - Unify render paths

Criticality: Medium

Complexity: M

Recommended changes:

- Make production CLI, dev script, and tests use the same rendering path.
- Avoid raw `str.replace` outside one internal function.
- Prefer adjacent `template.html` from `__file__`.

This reduces future drift.

## What Not To Do

These changes would add complexity without enough return right now:

| Proposal | Reason to avoid now | Criticality | Complexity |
|---|---|---:|---:|
| Add proxy support | Adds configuration and support burden for an uncommon primary-user case. Current typed IP-block errors are enough. | Low | M |
| Add caption quality labels | Does not materially improve reports unless used by a real fallback strategy. | Low | S |
| Replace sanitizer with a dependency-heavy HTML sanitizer | Current stdlib sanitizer is small and adequate for the narrow generated HTML contract. | Low | M |
| Build a full transcript database/cache | Useful later, but overkill for the current local-report workflow. | Low | L |
| Split per-agent SKILL.md variants | Reduces command loops but increases release and testing matrix. | Low | L |
| Rewrite template in a JS framework | The current static template is a strength: portable, local, and simple to serve. | Low | L |

## Recommended Priority Order

| Rank | Work item | Criticality | Complexity |
|---:|---|---:|---:|
| 1 | Fix README/manual install to include scripts | High | S |
| 2 | Fix stale slow-test `YTDLP_ERROR` check | Medium | XS |
| 3 | Wrap `transcript_obj.fetch()` and add metadata timeout | Medium | S |
| 4 | Add title fallback or make title failure explicit | Medium | S |
| 5 | Replace dev raw rendering with production renderer | Medium | S |
| 6 | Make `modelName` optional/agent-neutral and drop or script-compute `durationSeconds` | Medium | S |
| 7 | Move `VIDEO_LENS_META` assembly into renderer | Medium | M |
| 8 | Shrink `SKILL.md` allowlist/error details after renderer owns them | Medium | M |
| 9 | Improve `serve_report.sh` stale-port diagnostics | Medium | S |
| 10 | Fix gallery backfill scan path and minimal gallery prompt gaps | Medium | S |

## Target End State

The skill should feel simpler to execute, not less capable.

Ideal runtime flow:

1. Agent extracts `VIDEO_ID` and optional `LANG_PREF`.
2. Script fetches transcript plus metadata and emits structured data.
3. Agent writes only the human judgment fields: Summary, Takeaway, Key Points, Outline, Tags.
4. Renderer validates, sanitizes, computes metadata, writes the report, and returns typed errors.
5. Serve script opens the report and emits `HTML_REPORT`.
6. Agent only reports success if the marker appeared.

This keeps the important complexity where it belongs:

- Content judgment in the agent.
- Deterministic validation and formatting in scripts.
- Interactivity in the template.
- Minimal final communication in the skill.
