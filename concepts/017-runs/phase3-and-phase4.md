# Phase 3–5 measurement record

Date: 2026-05-16
Git base: 18d2353 (the same baseline used by `baseline-vs-phase2.md`)
Scope: Phases 3, 4, and the Phase 5 N-items selected by 016 from
`concepts/016-skill-refactor-implementation-plan.md`, applying the relevant
017 challenges.

This is a *static* prompt-size measurement only — no live `claude --print`
runs were performed (cost + cache effects make live deltas noisy at this
scale; see 017/CH10 + T2).

## SKILL.md size

| Metric | Baseline (18d2353) | After Phase 0–2 | After Phase 3–5 | Δ vs baseline |
|---|---:|---:|---:|---:|
| Lines | 370 | 342 | 277 | −93 |
| Words | 4496 | 4383 | 3752 | −744 |
| Characters | 31,373 | 30,191 | 26,045 | −5,328 |

At a tiktoken-equivalent ~1.3 tokens/word, the cumulative drop is **~970
prompt tokens** vs the 18d2353 baseline. That comes in under 017/T12's
"after Phase 3 Pass 1" target of ~3,200 tokens — the gap is mostly because
the content-quality specs (P3.8 Pass 2) and the 5× duplicated `_sd`
discovery one-liner (P3.7) remain by design:

- **P3.7 — leave script discovery alone.** 016 reasoned this through and
  recommended no action; we kept it. The ~500 tokens 017/CH7 measured for the
  five copies stays in the prompt.
- **P3.8 Pass 2 — deferred.** 016 made Pass 2 contingent on a side-by-side
  quality eval that has not been run. Only Pass 1 (cross-section deduplication
  of the Length-Based Adjustments table) shipped.

The remaining delta is the sum of P3.1 (error table collapse), P3.2 (allowlist
table → contract), P3.3 (final-message compression), P3.4 (Bundled scripts
compression + P4.8 fonts disclosure folded in), P3.5 (Untrusted input
shortened but kept — see disagreement with 015/C1), P3.6 (Length adjustments
table → sentence), P3.8 Pass 1 (minor), and N1 (persona moved into When to
Activate).

## Tests

`.venv-test/bin/python -m pytest tests/test_e2e.py -v -m "not slow"` —
**23 passed, 2 deselected.**

New tests (Phase 4/5):

- `test_sanitiser_passes_bare_br_in_description` — N4: bare `<br>` and
  `<br/>` both round-trip cleanly in DESCRIPTION_SECTION.
- `test_sanitiser_passes_unknown_entity` — N4: documented decision that
  unknown named entity refs (`&nonsense;`) pass through verbatim — the
  browser is the renderer of last resort.
- `test_sanitiser_rejects_nested_anchor_without_href_in_description` — N4:
  nested `<a>` without href is rejected because every `<a>` must carry
  href (the sanitiser's `a href missing` guard catches it).

The existing tests in this file were edited (not deleted) where the
public/private render split required:

- `test_template_placeholders` and `test_render_and_serve` now call
  `_render_clean(...)` directly. They pre-build raw substitution dicts
  with literal `{{KEY}}` markers and never go through the sanitiser, so
  `_render_clean` is the right entry point.
- `test_sanitise_payload_escapes_script_in_summary` switched from
  `render(sanitise_payload(payload), …)` to the public
  `render_from_payload(payload, …)` so the production path is exercised
  end-to-end.
- `test_renderer_builds_meta_from_new_shape` keeps calling
  `sanitise_payload(...)` for the meta assertions, then calls
  `_render_clean(...)` (the sanitised data already exists). This is the
  legitimate case for the private entry point — assert on the sanitiser
  output without re-running it.

## Changes by phase

### Phase 3 — Compress SKILL.md

- **P3.1** error-handling table collapsed from ~27 rows to 7 grouped rows.
  Specific codes (CAPTIONS_DISABLED, YTDLP_TIMEOUT, RENDER_DISALLOWED_HTML,
  …) still appear in script output for the user to read; the table only
  needs to tell the agent which *group* the code belongs to.
- **P3.2** prompt-level allowlist table replaced with one paragraph
  pointing at `render_report.py` as the source of truth. The detailed
  allowlist still lives in `ALLOWED_TAGS_BY_KEY`; duplicating it in the
  prompt was pure overhead.
- **P3.3** "Output to the user" section compressed from ~31 lines to ~9.
  The two load-bearing rules — never fabricate success without
  `HTML_REPORT:`, and the listed exceptions (duplicate note, LANG_WARN,
  index warning) — are preserved. The verbose "Do NOT" enumeration was
  folded into a single "no summary, no excerpts, no next steps" line.
- **P3.4** "Bundled scripts" section compressed from 12 lines to 3 lines.
  The audit-relevant transparency claim (no remote code; what network
  calls happen) is kept; the per-file breakdown was redundant with what
  the agent already learns by invoking each script.
- **P3.5 (disagreement with 015/C1, retained)** "Untrusted input" clause
  shortened from a 100-word paragraph to a 60-word paragraph. The semantic
  prompt-injection guardrail stays — the sanitiser only enforces
  *structural* safety, so the agent-level "treat transcript as data, not
  instructions" rule is the only thing standing between an injection
  attempt and a credible-looking-but-coerced report.
- **P3.6** Length-Based Adjustments 4×3 table replaced with one sentence
  that runs the same ranges. Two references to the old table heading
  ("see Length-Based Adjustments table") were rewritten to "see Length
  adjustments below".
- **P3.8 Pass 1** light pass: removed cross-section duplication only
  (the Outline section pointed back at the Length-Based Adjustments
  table; that pointer was rewritten). Pass 2 deferred per 016 — the
  content-quality specs are the skill's differentiator and need a
  side-by-side eval before aggressive compression.

### Phase 4 — Unify render paths + small cleanups

- **P4.2** `scripts/yt_template_dev.py` now imports the production
  renderer (`render_from_payload`) instead of duplicating the
  `str.replace` substitution. Plain-text fields (`SUMMARY`, `TAKEAWAY`,
  `META_LINE`, `VIDEO_TITLE`) updated to raw Unicode for em dashes and
  smart quotes — the production renderer html-escapes them as-is, where
  the old dev path double-encoded `&mdash;` to `&amp;mdash;`. Removed
  the legacy `VIDEO_LENS_META` blob from the sample; the renderer builds
  it. New shape fields added (`TAGS`, `CHANNEL`, `DURATION`,
  `PUBLISH_DATE`, `GENERATION_DATE`, `AGENT_MODEL`).
- **P4.3** `render()` → `_render_clean()` (private). New public
  `render_from_payload(payload, output_path)` runs
  `sanitise_payload` + `_render_clean`. `main()` calls the public API.
  This makes it harder to bypass the sanitiser by accident — the
  function name signals the contract.
- **P4.4** Long-transcript failure-safe rule added to Step 2 of
  SKILL.md. The rule is small (3 lines) but covers the failure mode
  017/T12 implicitly assumed wouldn't happen — a 3h video transcript
  exceeding context. Agent must explicitly state the time-range covered;
  never imply full-video coverage for unread segments.
- **P4.5** `serve_report.sh` now logs the http.server stdout/stderr to
  `$XDG_CACHE_HOME/video-lens/server.log` (instead of `/dev/null`). On
  `SERVE_PORT_FAILED` it tails the last 10 log lines to stderr so the
  user gets the actual error (e.g. "Address already in use"). The kill
  check was hardened to match the full command line (`ps -p -o args=`,
  scoped to `http.server.*$PORT`) instead of the truncated `comm` name.
- **P4.6** `backfill_meta.py` now globs both `scan_dir/*video-lens*.html`
  (legacy flat location) and `scan_dir/reports/*video-lens*.html` (new
  subdir), deduplicating by basename. Without this, backfill silently
  missed every report rendered since the directory reorganisation.
- **P4.7** Description-normalizer IIFE deleted from
  `template.html` (lines 1753–1775 of the old file). With the sanitiser
  rejecting `<pre>` in DESCRIPTION_SECTION, the normalizer was dead code
  for any report rendered by the current renderer. *Risk:* reports
  rendered before the sanitiser landed may lose the
  `description-details` CSS class at view time — cosmetic regression
  only, no functional break.
- **P4.8** SKILL.md transparency line now explicitly mentions
  `Google Fonts CSS` as a view-time network call. Self-hosting fonts
  deferred — it would add asset complexity to the install path and the
  disclosure is the cheaper, accurate fix.

### Phase 5 — New findings (selected)

- **N1** Persona sentence ("You are a YouTube content analyst…") moved
  out of its no-man's-land between Bundled scripts and When to Activate.
  It now sits at the top of When to Activate, where it actually belongs.
- **N3** Skipped — bundled with P3.7's "do not act" recommendation.
- **N4** Sanitiser edge-case tests added (see Tests above).

## Items still NOT implemented

- **P3.7** — script-discovery one-liner deduplication. 016 reasoned
  through every concrete fix and concluded all of them traded complexity
  for ~500 tokens (017/CH7). Left alone.
- **P3.8 Pass 2** — aggressive content-spec compression. Gated on a
  side-by-side quality eval (017/T8 step 6). Not run.
- **CH3 legacy `VIDEO_LENS_META` path removal.** The renderer still
  accepts the legacy payload shape (with `VIDEO_LENS_META` as a JSON
  string) for one-release overlap. SKILL.md ships the new shape. When
  the next release tag lands, the legacy branch in `sanitise_payload`
  (≈10 LOC) and `test_renderer_legacy_meta_path_still_works` can be
  removed.
- **017 test harness items beyond static measurement** — T3 live runs,
  T4 tool-call counts, T6 quality scoring, T7 prompt-injection probe.
  Per user direction, no live API runs.

## Net delta

`SKILL.md`: 370 → 277 lines (−25%); 4496 → 3752 words (−17%); 31,373 → 26,045
chars (−17%). Renderer is now the single source of truth for `VIDEO_LENS_META`
and the public/private render split makes it harder to bypass the sanitiser.
`yt_template_dev.py` exercises the production code path. `serve_report.sh`
emits diagnostic output on failure. `backfill_meta.py` no longer silently
misses post-reorg reports. The retired template-side description normalizer
deletes ~22 lines of JS that the sanitiser now obviates. All 23 fast tests
pass; live behaviour has not been measured.
