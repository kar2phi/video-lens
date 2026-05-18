# 018 — Implementation assessment

Date: 2026-05-17
Predecessors:
- `concepts/018-mechanical-glue-relocation-spec.md` — the spec
- `concepts/018-spec-challenge.md` — the spec challenge (dropped `vl` wrapper, switched to `--output-dir`, dropped bcp47 regex)

## Status

The refactor is **in the working tree but uncommitted**. `git diff --stat`:

```
 skills/video-lens/SKILL.md                 | 163 +++++++++--------------------
 skills/video-lens/scripts/render_report.py |  79 ++++++++++++--
 skills/video-lens/template.html            |   4 +
```

Plus a new `skills/video-lens/scripts/preflight.py` (126 lines) and ~190 lines of new test coverage in `tests/test_e2e.py`.

SKILL.md: 299 → 233 lines (−22%). Test result: **49 pass, 1 fail (unrelated port-collision; see B7 below)**.

The challenge doc was honoured in spirit and letter: no `vl` wrapper, `--output-dir` flag, no bcp47 regex, explicit slug fallback. Net code grows (~+170 LOC); the win is testability + mechanical determinism, not LOC reduction.

## Verdict

Ready to commit **after** fixing items A1, A2, A3 below. Items in B are nice-to-haves; items in C are next-iteration enhancements.

---

## A. Must-fix before commit

### A1. SKILL.md treats per-step shell variables as persistent (HIGH)

**Where:** `skills/video-lens/SKILL.md:46`, `:60`, `:178`, `:189`.

Steps 2, 2b, 4, and 5 reference `$VIDEO_ID`, `$LANG_CODE`, `$START_EPOCH`, `$OUTPUT_PATH` as if they're shell variables set by an earlier step:

```bash
python3 "$_sd/fetch_transcript.py" "$VIDEO_ID" "$LANG_CODE"
```

```bash
bash "$_sd/serve_report.sh" "$OUTPUT_PATH" "$HOME/Downloads/video-lens"
```

**Bash state does not persist across Bash tool calls** — each invocation is a fresh shell (this is the same constraint that 016/P3.7 invoked to reject a wrapper). When the LLM runs Step 5 in a new Bash call, `$OUTPUT_PATH` is empty; `serve_report.sh` is called with a blank first argument and emits `ERROR:SERVE_FILE_NOT_FOUND`.

The original pre-refactor SKILL.md sidestepped this by telling the LLM to substitute literal placeholders (e.g. `VIDEO_ID`) when constructing the command. The new SKILL.md uses `$VAR` syntax, which different models will interpret differently — some inline the captured value, others leave it as a literal shell variable expecting expansion.

**Fix (recommended):** Replace each `"$VAR"` reference with an explicit placeholder convention. Add a one-paragraph note at the top of `## Steps`:

> Each Bash step runs in a fresh shell — values you read from one step (e.g. `VIDEO_ID` from preflight, `OUTPUT_PATH` from render) **must be inlined into the next step's command as literals, not referenced as `$VARS`**.

Then rewrite the bash blocks to use `<VIDEO_ID>` / `<LANG_CODE>` / `<OUTPUT_PATH>` placeholders, matching the convention the original SKILL.md used. Example:

```bash
… python3 "$_sd/fetch_transcript.py" "<VIDEO_ID>" "<LANG_CODE>"
```

**Alternative:** combine adjacent steps into a single Bash call so shell vars survive. Step 1+2 (preflight feeds fetch) and Step 4+5 (render feeds serve) are the natural pairs. Risk: long heredocs are harder for the LLM to read accurately, and Step 1's `DUPLICATE_PATH:` note breaks the chain.

### A2. preflight rejects schemeless URLs (MEDIUM regression)

**Where:** `skills/video-lens/scripts/preflight.py:46–62`.

Pre-refactor SKILL.md's URL table (old lines 31–41) listed `youtube.com/watch?v=…` and `youtu.be/…` without requiring `https://`. The new preflight uses `urlparse(raw)`, which sets `host=""` when no scheme is present, so all four URL forms without a scheme fall through to `ERROR:INVALID_INPUT`.

Users routinely type/paste `youtube.com/watch?v=X` without scheme. The skill used to handle this; now it stops.

**Fix:** at the top of `extract_video_id`, if `raw` doesn't start with `http://` or `https://` and isn't an 11-char bare ID, prepend `https://`:

```python
if not VIDEO_ID_RE.fullmatch(raw) and not raw.startswith(("http://", "https://")):
    raw = "https://" + raw.lstrip("/")
```

Add a test row to `test_preflight_extracts_id_from_each_url_form`:

```python
("youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
("youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
```

### A3. META_LINE override path is invisible to the LLM (MEDIUM)

**Where:** `skills/video-lens/SKILL.md` Step 4 table (lines 141–158) plus the explanatory bullet at line 161.

The table no longer lists `META_LINE` as a key. Line 161 says: "Set `META_LINE` explicitly only when you need a non-default string, e.g. with the `⚠ Requested language not available` suffix." This text sits after the table, in a "the renderer does these things" bullet block.

The Error Handling table at line 230 still tells the LLM to "append `⚠ Requested language not available` to `META_LINE`" on `LANG_WARN:`. But the LLM looking at the Step 4 keys table sees no `META_LINE` field — and the override instruction is easy to miss.

**Fix:** add a row back to the keys table:

```
| `META_LINE` *(optional override)* | Provide only when you need to override the renderer's default composition — e.g. when `LANG_WARN:` was seen, set this to `<channel> · <duration> · <published> · <views> · ⚠ Requested language not available`. Otherwise omit and let the renderer compose. |
```

---

## B. Should-fix soon

### B1. `_derived_filename` doesn't validate `GENERATION_DATE`

**Where:** `render_report.py:493`.

`_derived_filename` uses `payload.get('GENERATION_DATE', '')`. If empty, the result is `-HHMMSS-video-lens_<id>_<slug>.html` — a valid filename but malformed. SKILL.md Step 4 requires `GENERATION_DATE` per the table, so this is defence-in-depth, not a hot path.

**Fix:** in `main()`, when `--output-dir` is set, reject empty `GENERATION_DATE`:

```python
if args.output_dir is not None and not str(data.get("GENERATION_DATE", "")).strip():
    print("ERROR:RENDER_MISSING_KEYS GENERATION_DATE required with --output-dir", file=sys.stderr)
    sys.exit(1)
```

Add a test.

### B2. Stale "YouTube Shorts URL" row in Error Handling table

**Where:** `skills/video-lens/SKILL.md:229`.

Row reads: `YouTube Shorts URL | Report that Shorts are not supported. Stop.` This is now redundant with `ERROR:SHORTS_NOT_SUPPORTED` in line 224 — preflight catches Shorts and emits the structured error.

**Fix:** delete the row.

### B3. `fetch_transcript.py` still emits `TIME:` line (dead output)

**Where:** `skills/video-lens/scripts/fetch_transcript.py:171`.

The renderer now derives `HHMMSS` from its own clock (`render_report.py:497`). The `TIME:` line in `fetch_transcript`'s output is no longer consumed by anything. SKILL.md no longer references it (the old Step 4 — filename derivation — was deleted).

**Fix:** remove the line. Update the test fixtures (none assert on it currently).

### B4. `concepts/` filename inconsistency

`concepts/018-mechanical-glue-rel-robust-pillow.md` — odd suffix. The challenge doc is a sibling of `018-mechanical-glue-relocation-spec.md`; conventional naming would be `018a-…challenge.md` or `019-…challenge.md`.

**Fix:** `git mv concepts/018-mechanical-glue-rel-robust-pillow.md concepts/018-spec-challenge.md` (or whichever scheme is preferred). Update any cross-references — `018-mechanical-glue-relocation-spec.md` doesn't reference it, so the rename is safe.

### B5. Discovery line still copy-pasted 4× across SKILL.md

**Where:** `skills/video-lens/SKILL.md:34, 46, 60, 178, 189`.

Five copies of an identical ~150-character `_sd=$(for d in …)` one-liner. 016/P3.7 ruled this acceptable given bash-state non-persistence; the spec challenge upheld that ruling. Confirmed unfixable without an install-side `vl` symlink or similar invasive change. Not a fix — just documenting that this remains the cost of the architecture.

### B6. `_render_clean` test paths can leak server processes across runs

**Where:** test failure observed in this session — `test_render_and_serve` failed with `OSError: [Errno 48] Address already in use`.

Not a regression from this refactor — the test cleanup `kill $(lsof -ti:8765 …)` runs in a `finally` only on this test, and a prior local session left port 8765 bound. The test passes once the stale server is killed manually.

**Fix (defensive):** add a `kill_stale_server` fixture that runs before tests using `serve_report.sh`. Not blocking for this refactor.

### B7. `--output-dir` clamp wording in error message

**Where:** `render_report.py:416–417`.

`RENDER_INVALID_OUTPUT_PATH` message reads `must live under {ALLOWED_OUTPUT_ROOT}`. When `--output-dir` is the form used, the user's input was a *directory*; the message references the resolved file path. Slight UX friction during debugging.

**Fix:** make the message reflect which arg form was used (`--output-dir` vs positional path). Low priority.

---

## C. Enhancements / next iteration

### C1. Preflight could output the suggested slug

The challenge doc raised this (Finding C): for CJK titles, the LLM could provide a transliteration that's better than the hard-coded `video` fallback. Preflight (or fetch_transcript) could emit a `SLUG_HINT: …` line; the renderer accepts an optional `SLUG_OVERRIDE` payload field that wins over auto-derivation.

Cost: ~10 LOC across preflight + renderer; one more payload field for the LLM to optionally fill. Benefit: better filenames for the long tail of non-ASCII videos.

### C2. Combine Step 1 (preflight) with Step 2 (fetch) into a single Bash call

This would sidestep A1's bash-state issue for the first hand-off. The challenge: preflight's output needs LLM-side handling (the `DUPLICATE_PATH:` note, error reporting). Possible if we move the duplicate-note rendering into preflight itself (it writes to stderr; the LLM passes it through).

Net: removes one source of "is `$VAR` a literal or an expansion?" ambiguity.

### C3. Allow the renderer to read `GENERATION_DATE` from the system clock

Currently the LLM threads `GENERATION_DATE` from fetch_transcript's `DATE:` line through to render_report. The renderer could fall back to `date.today().isoformat()` if the field is empty, removing one payload field.

Tradeoff: less transparent (LLM no longer "sees" the date in the rendered payload), but tighter glue.

### C4. Test infrastructure: serve_report tests need a port-conflict fixture

See B7. Not blocking, but make this a follow-up to keep the suite stable on dev machines.

### C5. Drop the `Common rejection causes` paragraph from SKILL.md

`skills/video-lens/SKILL.md:168–171` lists three rejection causes that the renderer's error message already explains in-line. The LLM rarely benefits from prefiguring these errors when it's already cued by the structured error code. Candidate for a future compression pass.

### C6. CLAUDE.md / README.md sync

CLAUDE.md and README likely reference the old script list. Spot-check:

```bash
grep -n "fetch_transcript\|fetch_metadata\|render_report\|preflight" CLAUDE.md README.md
```

If neither mentions `preflight.py`, update for consistency. Cosmetic.

---

## How to pick up in another session

1. **Read this doc + the spec + the challenge doc** in order:
   - `concepts/018-mechanical-glue-relocation-spec.md`
   - `concepts/018-spec-challenge.md` (renamed from `018-mechanical-glue-rel-robust-pillow.md`; see B4)
   - `concepts/018-implementation-assessment.md` (this file)

2. **Reproduce the current state:**
   ```bash
   git diff --stat HEAD
   .venv-test/bin/pytest tests/test_e2e.py -v -k "not slow"
   ```
   Expected: 49 passed, 1 failed (port 8765 collision — kill stale server with `kill $(lsof -ti:8765) 2>/dev/null` and rerun).

3. **Apply fixes in order:**
   - A1 (bash-var persistence) — biggest behavioural fix; touch SKILL.md only
   - A2 (schemeless URLs) — preflight.py + one test row
   - A3 (META_LINE override row) — SKILL.md only
   - B1 (GENERATION_DATE validation) — render_report.py + test
   - B2 (stale Shorts row) — SKILL.md only
   - B3 (drop TIME: from fetch_transcript) — fetch_transcript.py only
   - B4 (rename challenge doc) — git mv

4. **Verify:**
   ```bash
   .venv-test/bin/pytest tests/test_e2e.py -v -k "not slow"
   ```
   Should be 50/50 (or 49/50 if port 8765 is dirty — kill stale server).

5. **Deploy and smoke:**
   ```bash
   task install-skill-local AGENT=claude
   ```
   Then in a fresh Claude session, summarise:
   - a normal YouTube URL with chapters
   - a schemeless URL (`youtube.com/watch?v=…`) — should work after A2
   - a non-English video with `LANG_WARN:` — confirm META_LINE override appears
   - a YouTube Shorts URL — confirms preflight emits the structured error

6. **Commit:**
   Suggested commit boundaries (each independently revertible):
   1. `fix(skill): inline step outputs as literals, not shell vars` (A1)
   2. `fix(preflight): accept schemeless youtube URLs` (A2)
   3. `fix(skill): re-add META_LINE override row to render keys table` (A3)
   4. `fix(renderer): require GENERATION_DATE with --output-dir` (B1)
   5. `chore(skill): drop redundant Shorts row from error table` (B2)
   6. `chore(fetch): drop unused TIME: line` (B3)
   7. `chore(concepts): rename 018 challenge doc` (B4)

   (Or squash into one `feat(skill): push mechanical glue into preflight + renderer` commit if you prefer the whole refactor as a single unit. The current working-tree diff is already a coherent unit if you do this.)

---

## Open questions for the user

1. **Bash-state ambiguity (A1) — which fix?** Inline-literals convention (status quo, but spelled out), or fold adjacent steps into single Bash calls. The first is safer; the second is leaner.

2. **CJK slug fallback (C1) — worth the extra payload field?** Status quo (always `video` for non-Latin titles) is fine if it's rare; the `SLUG_HINT:` path adds LLM judgement back into the slug, which has both upside (better filenames) and downside (variance).

3. **Squash commits or keep granular?** Current working tree is one logical refactor. Splitting per A/B item gives revertibility; squashing matches the "one PR per refactor" pattern of 016/017.

---

## What changed since the spec

Beyond what's documented in the challenge doc, the implementer made these non-spec'd improvements (all positive):

- `_maybe_compose_meta_line` is a clean top-level helper instead of inlined in `sanitise_payload`. Easier to test in isolation.
- `_slug_from_title` is a top-level helper, callable from tests without subprocess. Future hooks for C1 are simpler.
- `argparse` mutually-exclusive group with `nargs='?'` positional works correctly here; the test `test_renderer_positional_path_still_works` confirms the legacy file-path form still functions.
- Test `test_renderer_computes_duration_from_start_epoch` uses `monkeypatch` to pin `time.time()`, getting an exact assertion (`== 7`) instead of the fragile `>= 7` the spec suggested.
- Test `test_renderer_output_dir_outside_clamp_rejected` was added (matches challenge doc Finding F).
- Test `test_renderer_positional_path_still_works` was added (matches challenge doc Finding F).
- Test `test_preflight_main_splits_argv_on_space` was added (matches challenge doc Finding F).

These improvements close the four test-coverage gaps the challenge doc flagged.
