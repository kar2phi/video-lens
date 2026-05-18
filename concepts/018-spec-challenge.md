# Challenge of concepts/018 — mechanical-glue relocation

## Context

Concept 018 proposes moving deterministic logic (URL parsing, language mapping, duplicate
check, start-epoch, filename slugging, META_LINE composition, duration math) out of
`skills/video-lens/SKILL.md` into:
- a new `preflight.py` (~90 LOC)
- a new `vl` shell wrapper (~40 LOC)
- extensions to `render_report.py` (~60 LOC)

Claimed outcome: SKILL.md 299 → ~227 lines (−24%), mechanical paths become unit-testable.

This document **challenges** 018 before implementation. The direction is mostly right; the
critique below targets where 018 either re-litigates a prior ruling without acknowledging
it, smuggles in interface choices that will be hard to unwind, or under-specifies a
sequencing/security detail.

Reference points verified during this review:
- Current SKILL.md: 299 lines; 4 instances of the 8-agent discovery one-liner (lines 78,
  98, 221, 254).
- `render_report.py:404` — current `validate_output_path` signature is `(path: str)`; test
  bypass at `:406` short-circuits both `.html` suffix and clamp.
- `_build_meta_dict` at `:326` consumes `output_path` to set `meta["filename"]`.
- 016/P3.7 (lines 515–530) explicitly rejects wrapper-script options as either failing
  (bash state non-persistence) or adding install complexity.
- 016/P2.1 (lines 264–355) established the renderer as the owner of derived metadata.

## Bottom line up front

1. **Land the renderer extensions and `preflight.py`** — these deliver ~80–90% of the
   SKILL.md reduction and are cleanly testable. Strong endorse.
2. **Drop the `vl` wrapper** (or defer it). Its marginal benefit is replacing
   `python3 "$_sd/X.py"` with `$VL X` per step. Each SKILL.md Bash step still needs its
   own discovery one-liner — bash state is fresh per call (016/P3.7). 40 LOC + install
   fragility (exec bit, rsync) + an untested 8-agent fallback in `vl index` is poor ROI.
   Lean recommendation: skip the wrapper; let SKILL.md call `preflight.py`,
   `fetch_transcript.py`, etc. directly through the existing discovery line.
3. **Replace the directory-arg polymorphism on the renderer with an explicit flag.** A
   path that's "either a file or a directory depending on trailing slash / is_dir()" is a
   subtle API. Prefer `--output-dir DIR` (mutually exclusive with positional file path).
4. **Make the renderer's filename-derivation sequencing explicit in the spec.** 018's open
   issues 2 and 3 hand-wave the raw-title-before-sanitise constraint; spell out the call
   order before implementation, not after.

## Findings (ranked by severity)

### A. The wrapper re-litigates 016/P3.7 without acknowledging it

018 lists 016/P3.7 under "Constraints carried" but treats it as a neutral fact ("bash
state is not persistent"). 016/P3.7 was a *rejection* of the wrapper-script pattern, not
a neutral observation. 018 should either:
- explicitly argue why 016/P3.7's reasoning no longer applies (the case is plausible —
  with 6 callable scripts including preflight, a wrapper centralises dispatch — but the
  argument is not made), or
- drop the wrapper.

Concrete numbers: with the wrapper, each Bash step in SKILL.md is:
```bash
VL=$(for d in ~/.agents …; do [ -x "$d/skills/video-lens/scripts/vl" ] && echo "$d/skills/video-lens/scripts/vl" && break; done); [ -z "$VL" ] && echo "…" && exit 1; $VL preflight "$USER_INPUT"
```
Without the wrapper, it is:
```bash
_sd=$(for d in ~/.agents …; do [ -d "$d/skills/video-lens/scripts" ] && echo "$d/skills/video-lens/scripts" && break; done); [ -z "$_sd" ] && echo "…" && exit 1; python3 "$_sd/preflight.py" "$USER_INPUT"
```
The savings are ~15 characters per step. Six steps × 15 chars ≠ a meaningful SKILL.md
reduction. The real ~70 lines saved come from `preflight.py` absorbing 1 + 2-preamble +
2b + 4, not from `vl`.

**Recommended revision:** delete Step 3 of 018 (the `vl` wrapper). Keep the existing
`_sd=…` discovery one-liner. Re-tally SKILL.md target line count (still ~225 since the
boilerplate length is unchanged).

### B. Directory-arg polymorphism is the wrong shape

`validate_output_path` is being changed from `(path: str)` to "path that may be a file or
a dir, detected by `is_dir() or endswith('/')`". This is a polymorphic interface with two
subtle traps:
- A directory path that doesn't yet exist on disk has `is_dir() == False`; behaviour
  depends on trailing slash. Users will hit this once and ask "why does `reports` fail
  but `reports/` work?".
- The test bypass (`VIDEO_LENS_ALLOW_ANY_PATH=1`) currently short-circuits both the
  `.html` suffix check AND the clamp. The new dir-detection must happen *before* the
  bypass, or test-mode behaviour for the file-path case changes. 018 doesn't say which.

**Recommended revision:** keep the positional arg as a strict file path. Add
`--output-dir DIR` (mutually exclusive). SKILL.md uses `--output-dir
~/Downloads/video-lens/reports/`. Detection is unambiguous; the test bypass is unchanged
for the legacy path.

### C. Slug regression is asymmetric, not symmetric

018 locks in `re.sub(r"[^a-z0-9]+", "_", title.lower())[:60] or "video"`. For CJK titles
that produces empty → fallback `video`. Today the LLM at Step 4 could (and sometimes
does) transliterate or summarise the title to ASCII. The plan's test
`test_renderer_slug_falls_back_for_non_ascii_title` codifies the worse outcome.

This is acceptable if we declare it acceptable. It is **not** "no behavioural change for
clean runs" as the "Expected outcome" section claims — clean runs on CJK content get a
generic filename. Either:
- soften the "Expected outcome" claim and document the slug regression as a known
  trade-off, OR
- have `preflight.py` produce a `SLUG:` line that the LLM may override (one extra payload
  field, but preserves LLM judgement for non-ASCII titles).

### D. Sequencing of slug / sanitise / clamp is fragile

018's open issues 2 and 3 acknowledge that:
- the slug must be computed from the *raw* `VIDEO_TITLE` (before `sanitise_payload`'s
  `html.escape` at `render_report.py:387`)
- the directory→filename derivation must happen *before* `_build_meta_dict` (which sets
  `meta["filename"] = pathlib.Path(output_path).name` at `:350`)

Both are correct constraints but the suggested resolution ("simplest: derive in main()
before render_from_payload") leaves the function ordering implicit. Prescribe it
explicitly in the spec:

```
main(argv):
    raw_payload = json.load(stdin)
    out_path = derive_output_path(argv[1], raw_payload)   # raw title used here
    clean = sanitise_payload(raw_payload, out_path)       # meta["filename"] correct
    write(template.substitute(clean), out_path)
```

This stops the implementer from threading the slug through `sanitise_payload`'s internals
and creating a double-derive.

### E. `vl index` 8-agent fallback is dead code

The wrapper lives under one of the 8 agent dirs by construction. `$dir/../../video-lens-gallery/scripts/build_index.py`
will resolve in every supported install. The 8-agent fallback loop adds 6 lines of
untested code path. If you keep the wrapper at all, delete the fallback and let the
relative path fail loudly when broken.

### F. Test coverage gaps

The proposed test set misses:
- **Path clamp on derived filename.** When input is `--output-dir /tmp/` (outside the
  clamp), the renderer must reject — verify with `VIDEO_LENS_ALLOW_ANY_PATH` unset.
- **Preflight's argv-with-space splitting.** `preflight.main()` splits "id LANG" into two
  fields when only one positional is given. Cover the both-as-one-arg branch.
- **Renderer's bypass-vs-derivation ordering** (per finding B): test that
  test-mode bypass still works for the legacy positional .html path.
- **Negative `GENERATION_START_EPOCH` rejection** is covered, but the success-path
  computed `durationSeconds` test uses `>= 7`, which is fragile if the test runs slowly.
  Use `== max(0, now - start)` against a fixed-clock seed instead.

### G. Net code grows; framing should acknowledge it

018 sells "~24% smaller SKILL.md". Net repo LOC: −72 (SKILL.md) +90 (preflight) +40 (vl)
+60 (renderer) +~50 (tests) = roughly **+170 LOC net**. The win is *testability* and
moving guidance out of prompt context — not code reduction. Re-state the value in those
terms; otherwise reviewers will challenge it on the LOC delta.

### H. Bcp47 validation is decorative

`^[a-z]{2,3}(-[A-Za-z0-9]+)?$` accepts `xy-Z`, `abc-DEF123`, etc. — none of which
`youtube-transcript-api` will accept. Either tighten to a real allowlist (LANGUAGE_MAP
plus a small set of known BCP-47) or drop the regex and pass anything through; the
fetcher already returns `LANG_WARN:` on unknown codes.

### I. Rollback plan is too rosy

018 says: "git revert the SKILL.md commit alone — scripts are backward-compatible". True
in one direction: old SKILL.md works against new scripts. But the **new** SKILL.md hard
depends on the new renderer behaviour (META_LINE compose, directory-arg, OUTPUT_PATH:
stdout). The rollback note buries this in a parenthetical. Promote it: "If renderer
regresses, you must revert both the renderer commit AND the SKILL.md commit."

## Recommended revisions to 018 (concrete edit list)

Apply to `concepts/018-mechanical-glue-relocation-spec.md`:

1. **Add a "Why the wrapper is/isn't in scope" section** before "Files" that engages
   016/P3.7 directly. Either justify the wrapper or — preferred — drop it.
2. **If wrapper dropped:** remove Step 3 ("Create vl wrapper") and Step 6
   (yt_template_dev parity for `vl`-only stdout); rewrite Step 4's discovery template to
   keep the current `_sd=…` form; remove `vl_wrapper_*` tests; remove open issue 1
   (rsync exec bit).
3. **Replace directory-arg with `--output-dir`** in Step 1d. Update Step 4's "New Step 5"
   sample (the heredoc → renderer call) to use the flag.
4. **Add an explicit "Renderer call ordering" subsection** under Step 1 that pins the
   sequence: parse argv → derive output path from raw payload → sanitise → render →
   write → print OUTPUT_PATH.
5. **Soften "Expected outcome"** to acknowledge:
   (a) net code grows; the win is testability and prompt-context reduction,
   (b) CJK titles fall back to `video` slug (or implement the preflight `SLUG:`
   workaround).
6. **Tighten the rollback paragraph** to surface the SKILL.md↔renderer coupling.
7. **Add the four missing tests** from Finding F.
8. **Decide on bcp47** — either drop the regex or add a known-code allowlist.

## Files to modify (if user approves)

- `/Users/philka/repos/video-lens/concepts/018-mechanical-glue-relocation-spec.md`
  (rewrite per above)

No code changes in this plan — this is a spec-level critique. If the revised 018 is
approved, a separate execution plan will cover the implementation.

## Verification

After editing 018:
- Re-read the doc end-to-end; confirm no internal contradiction (e.g. wrapper dropped but
  still referenced in step counts).
- Confirm the new SKILL.md target line count is recomputed with the wrapper-less
  discovery template (length ≈ unchanged from the current `_sd=` line).
- Skim 016/P3.7 once more to confirm the "Why wrapper isn't in scope" section
  *quotes* the prior rejection rather than paraphrasing.

## Chosen scope (confirmed with user)

**Heavy** — drop the `vl` wrapper entirely. Revise 018 to a leaner plan covering
`preflight.py` + renderer extensions + SKILL.md sweep, and address all findings above.

Specifically, the rewrite of 018 will:
- Remove Step 3 (`vl` wrapper) and its tests.
- Restore the existing `_sd=…` discovery one-liner in the SKILL.md template.
- Drop Step 6 (yt_template_dev edit for `vl`-only stdout parity) — keep only the
  `OUTPUT_PATH:` line change needed for `scripts/yt_template_dev.py`.
- Drop open issue 1 (rsync exec-bit concern).
- Replace renderer directory-arg polymorphism with `--output-dir DIR`.
- Add an explicit "Renderer call ordering" subsection.
- Soften "Expected outcome" to acknowledge net +LOC and CJK-slug fallback.
- Tighten rollback paragraph re: SKILL.md ↔ renderer coupling.
- Add the four missing tests.
- Decide bcp47: drop the regex; lean on `LANGUAGE_MAP` + pass-through, and let
  `fetch_transcript.py`'s `LANG_WARN:` handle unknown codes.
