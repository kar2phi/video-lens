# Phase 0–2 measurement record

Date: 2026-05-16
Git base: 18d2353 (before edits)
Scope: Phases 0, 1, 2 of `concepts/016-skill-refactor-implementation-plan.md`,
applying CH1/CH2/CH3 from `concepts/017-skill-refactor-test-harness-and-challenge.md`.
Per 017/T2 + CH10, this is a *static* prompt-size measurement only — no live
`claude --print` runs were performed (cost + cache effects make live deltas
noisy at this scale).

## SKILL.md size

| Metric | Baseline | After Phase 0–2 | Δ |
|---|---:|---:|---:|
| Lines | 370 | 342 | −28 |
| Words | 4496 | 4383 | −113 |
| Characters | 31,108 | 30,191 | −917 |

Estimate at ~1.3 tokens/word for a Claude tokenizer-equivalent: ~147 prompt
tokens dropped. This is *below* the ~1750 tokens 017/T12 predicted "After P2"
because Phase 3 compression (error table, allowlist table, final-message
section) has not been applied yet. The Phase 2-attributable removals match
expectation: `START_EPOCH` capture (10 lines) + the `Building VIDEO_LENS_META`
spec (~25 lines) + a smaller key table net delta.

## Tests

`pytest tests/test_e2e.py -v -m "not slow"` — 20 passed, 2 deselected.

New tests:

- `test_renderer_builds_meta_from_new_shape` — end-to-end new shape, structural
  assertions on every meta field, generatedAt format.
- `test_renderer_keywords_are_li_aware` — CH1: inline `<strong>` inside
  analytical paragraphs must NOT become keywords. Only the first `<strong>` of
  each `<li>`.
- `test_renderer_summary_truncates_on_word_boundary` — CH2: ≤300 chars +
  ellipsis, breaks on whitespace, no torn final word.
- `test_renderer_unescapes_entities_in_summary` — CH2: `&mdash;` → `—` in the
  meta summary.
- `test_renderer_new_shape_optional_fields_default_empty` — TAGS/CHANNEL/
  DURATION/etc. all optional, defaults are sensible.
- `test_renderer_rejects_non_list_tags` — TAGS must be a JSON array;
  `RENDER_INVALID_META_JSON` if not.
- `test_renderer_legacy_meta_path_still_works` — CH3: existing
  `VIDEO_LENS_META`-bearing payloads still render unchanged. Required for the
  one-release overlap before the legacy path is removed.

## Changes by phase

### Phase 0 (regressions and stale docs)

- P0.1 README: save-path corrected to `~/Downloads/video-lens/reports/`;
  Option B rewritten to clone + `task install-skill-local` (the curl-individual-
  files path was broken — it never pulled `scripts/`); Deno reframed as
  edge-case-only for yt-dlp.
- P0.2 `tests/test_e2e.py:298` — YTDLP error check uses the real prefix
  (`startswith("ERROR:YTDLP_")`) instead of a string that never appears.
- P0.3 `fetch_transcript.py:_fetch_html_metadata` — `urlopen(..., timeout=10)`.
- P0.4 `fetch_transcript.py` — wrapped `transcript_obj.fetch()` in a typed
  except → `ERROR:TRANSCRIPT_FETCH_FAILED`.
- P0.5 `fetch_transcript.py` — title fallback to `YouTube video <id>` when
  HTML scrape returns empty. Documented in SKILL.md Step 2.
- P0.6 `Taskfile.yml serve` — replaced the parallel kill+http.server
  implementation with a call into `serve_report.sh`. Single source of truth
  for the server.

### Phase 1 (strip prompt-owned telemetry)

- P1.1 dropped `START_EPOCH` capture in SKILL.md Step 2 and `durationSeconds`
  from the meta block. Removed `date +%s` ceremony.
- P1.2 renamed `modelName` → `agentModel`, made optional. `template.html`
  reads `VL_META.agentModel || VL_META.modelName` so existing reports keep
  working.

### Phase 2 (renderer owns VIDEO_LENS_META)

- P2.1 `render_report.py`:
  - Added `_LIFirstStrongCollector` (CH1) — LI-aware keyword extraction.
  - Added `_truncate_summary` (CH2) — word-boundary truncation, ellipsis
    suffix, entity decoding.
  - Added `_build_meta_dict` — constructs the meta block from agent-authored
    payload. `generatedAt` is computed by the renderer.
  - Added optional fields (`TAGS`, `CHANNEL`, `DURATION`, `PUBLISH_DATE`,
    `GENERATION_DATE`, `AGENT_MODEL`). Renderer fills sensible defaults if
    absent.
  - **CH3 two-step migration:** if a payload still includes a
    `VIDEO_LENS_META` JSON string, the renderer parses and uses it (legacy
    path). Otherwise the renderer builds it. Both paths are tested.
  - `EXPECTED_KEYS` reduced to 9 (the agent-authored payload fields).
  - `REQUIRED_NONEMPTY` no longer requires `VIDEO_LENS_META`.
  - `find_template()` prefers the copy adjacent to the script over a home-dir
    scan (P4.1 — folded in because the dead `prefix=...` variable was already
    on the changed surface).
- P2.2 tests updated as listed above. `sample_render_payload()` kept on the
  legacy shape; new `new_shape_payload()` helper for new-shape tests.

## Migration notes

- `SKILL.md` ships the new shape only. `render_report.py` accepts both shapes.
  Plan: after one published release, delete the legacy path in
  `sanitise_payload` (≈10 LOC) and the
  `test_renderer_legacy_meta_path_still_works` /
  `test_sanitise_payload_rejects_invalid_meta_json` tests.
- The dev sample (`scripts/yt_template_dev.py`) still emits the legacy
  `VIDEO_LENS_META` JSON because it does its own `str.replace`-based
  rendering rather than going through the production renderer. P4.2 in 016
  proposes routing the dev sample through `render_report.py`; deferred.

## Items NOT yet implemented (Phase 3+ deferred to a later pass)

- Phase 3 prompt compression (error table, allowlist table, final-message
  section, length adjustments table, persona placement) — the larger token
  savings live here, but they need their own review since some touch the
  Untrusted Input clause and content-quality specs.
- Phase 4 cleanups (P4.2 dev sample uses production renderer, P4.3 public/
  private render split, P4.4 long-transcript guidance, P4.5 serve_report
  diagnostics, P4.6 gallery backfill scan path, P4.7 description normalizer
  removal, P4.8 Google Fonts disclosure).
- Phase 5 new findings (N1 persona placement, N3 _sd marker, N4 sanitiser
  edge-case tests).
- 017 test harness items beyond static measurement: T3 live runs, T4 tool-
  call counts, T6 quality scoring, T7 prompt-injection probe — skipped per
  user direction (no live API runs).
