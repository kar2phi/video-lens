# 020 — Session findings: render contract bug, JSON heredoc fragility, parallelization

Captured from a live `/video-lens` run on `https://www.youtube.com/watch?v=SVOrURyOu_U`
(Pragmatic Engineer × Martin Kleppmann, 1h 25m, English transcript, 109 KB).

The run succeeded but hit two avoidable render failures and confirmed one
inefficiency that another session had flagged. This doc captures the diagnosis
and the recommended fixes so the next session can act on them without re-deriving.

---

## Findings, highest ROI first

### 1. `META_LINE` docs / code drift — REAL BUG

`skills/video-lens/SKILL.md:153` says:

> `META_LINE` *(optional override)* | Provide only when overriding the renderer's
> default `CHANNEL · DURATION · PUBLISH_DATE · VIEWS` composition — … Otherwise
> omit and let the renderer compose.

But `skills/video-lens/scripts/render_report.py:34-37` defines:

```python
EXPECTED_KEYS = {
    "VIDEO_ID", "VIDEO_TITLE", "VIDEO_URL", "META_LINE", "SUMMARY",
    "KEY_POINTS", "TAKEAWAY", "OUTLINE", "DESCRIPTION_SECTION",
}
```

and at line 523:

```python
missing = EXPECTED_KEYS - set(data.keys())
if missing:
    print(f"ERROR:RENDER_MISSING_KEYS {sorted(missing)}", file=sys.stderr)
```

So omitting `META_LINE` (as the docs invite) trips `RENDER_MISSING_KEYS`.
The compose helper `_maybe_compose_meta_line` at line 315 already handles
auto-composition from `CHANNEL/DURATION/PUBLISH_DATE/VIEWS` — but only after
the existence check has gated the request.

**Observed cost in this session:** one failed render attempt costing roughly
30 s of agent time plus context-window pollution (the full payload was echoed
back as a tool error and consumed for the retry).

**Recommended fix (code, ~5 lines in `render_report.py`):**

Remove `META_LINE` from `EXPECTED_KEYS`. The compose logic at line 315 already
returns `""` when neither META_LINE nor any of the four component fields are
present, so downstream code is safe. If we want to be conservative, keep the
key in `EXPECTED_KEYS` *but* compose into `data` before the existence check.

Cleanest patch:

```python
EXPECTED_KEYS = {
    "VIDEO_ID", "VIDEO_TITLE", "VIDEO_URL", "SUMMARY",
    "KEY_POINTS", "TAKEAWAY", "OUTLINE", "DESCRIPTION_SECTION",
}
```

(Drop `META_LINE`. The `_maybe_compose_meta_line` call inside
`sanitise_payload` at line 418 already supplies a default.)

Verify the existing test suite still passes (`tests/test_e2e.py`).

### 2. JSON heredoc is fragile when content contains double quotes — DOCS/UX

Step 4 of `SKILL.md` instructs the agent to build the payload inside a
`cat <<'JSON' … JSON` heredoc and pipe it to `render_report.py`. This works
for plain prose but breaks the moment the content includes a double quote
that is not escaped — exactly what happens when KEY_POINTS or OUTLINE use
`<em>"…"</em>` to quote the speaker, which the skill prompt *actively
encourages* ("use `<em>` for the speaker's own words").

**Observed cost in this session:** first render attempt failed with
`ERROR:RENDER_INVALID_JSON Expecting ',' delimiter`. The recovery was to
construct the payload in Python via `json.dumps` and pipe it into the
renderer via stdin — that worked first try.

**Recommended fix (docs only; or small code surface):**

Option A — docs-only callout in Step 4:
> The heredoc is *raw text*, not JSON-aware. Every `"` inside a value must
> be escaped as `\"`. If KEY_POINTS or OUTLINE quote a speaker via
> `<em>"…"</em>`, prefer building the payload in a Python one-liner using
> `json.dumps` and piping its stdout into the renderer.

Option B — extend `render_report.py` with `--payload-file PATH` so the agent
can `Write` a `.json` file (where the editor handles quoting) and then
invoke `render_report.py --payload-file path.json --output-dir …`. This
sidesteps the shell entirely. ~10 lines of argparse + open().

Both have similar ROI. Option B is more robust but requires a code change
and a small SKILL.md update. Option A is zero-code but relies on the agent
following the callout. Recommend B.

### 3. Sequential Steps 2 / 2b — confirmed parallelizable

This matches the other session's diagnosis. Verified by reading
`fetch_metadata.py` (takes only `VIDEO_ID`) and `fetch_transcript.py`
(takes `VIDEO_ID` + optional `LANG_CODE`). Neither reads the other's output.

Dependency graph:

```
Step 1 (preflight) ──┬─→ Step 2  (transcript) ─┐
                     └─→ Step 2b (yt-dlp)      ├─→ Step 3 (LLM summary) → 4 → 5 → 6
                                               ┘
```

**Savings math correction:** The other session claimed "2–4 s saved per run."
The actual saving is `min(t2, t2b)`, not `t2 + t2b` — i.e. the *shorter* of
the two hides behind the longer. If transcript fetch is 3 s and yt-dlp is
5 s, savings is 3 s. Still real, still worth doing, but the framing in the
other session implied a larger absolute win.

**Recommended fix (docs only):**

Renumber `SKILL.md` Steps 2 and 2b under a single header that explicitly
instructs the agent to issue both Bash calls in **one assistant message**
so the harness runs them concurrently. Add one line noting "both depend
only on `VIDEO_ID`; neither depends on the other." Keep the error-handling
table unchanged.

### 4. Transcript Read-in-batches overhead — MINOR

For this 1h 25m video, the transcript fetch script saved 109 KB of output to
a temp file. SKILL.md Step 2 says to read "the entire file in 500-line batches."
For this run that meant **5 separate Read calls** (lines 1–500, 501–1000,
1001–1500, 1501–2000, 2001–2420). Each Read is a round-trip and burns context.

**Recommended fix (docs only):**

Bump the recommended batch limit from 500 to ~1500 lines. The Read tool
accepts up to 2000 lines by default. For typical 1-hour videos this cuts
reads from 4–5 to 1–2. The "every part matters" instruction is preserved —
this is only changing the chunk size, not whether the agent reads the whole
thing.

---

## Critical assessment of the other session's proposal

The other session proposed parallelizing Step 2 and 2b and dismissed four
other candidate optimizations. Verdict:

**Correct:**
- ✅ Steps 2 and 2b are independent — verified by reading the scripts.
- ✅ Dismissing internal threading inside `fetch_transcript.py` (low payoff,
  real debug complexity).
- ✅ Not unifying the two scripts (debuggability matters more than elegance).
- ✅ Not feeding Step 3 less context (fidelity is explicitly user-prioritised
  in `SKILL.md` — "Every part of the transcript matters").

**Slightly off:**
- ⚠️ The "2–4 s saved" estimate frames it as additive when it's actually
  `min(t2, t2b)`. Still positive ROI, smaller absolute number.

**Missed entirely — these are larger wins than the proposed change:**
- ❌ The META_LINE docs/code drift. One failed render in a session costs
  ~30 s + context pollution — an order of magnitude more than the 3 s
  parallelization save, and triggers more often than people realize because
  the docs invite the failure mode.
- ❌ The JSON-heredoc fragility. Trips whenever speaker quotes appear in
  KEY_POINTS, which the prompt actively encourages.
- ❌ The Read batch-size overhead. Free wins on long videos.

The other session's analysis was correct about its narrow target but missed
the more impactful failure modes that this run actually surfaced.

---

## Suggested next-session work order

If picking this up cold, I recommend addressing in this order:

1. **#1 META_LINE contract** — code change, ~5 lines, has tests. Most
   impactful per LoC.
2. **#2 `--payload-file` argument** — code change to `render_report.py`,
   small SKILL.md update in Step 4. Eliminates the most common render
   failure mode for quote-rich content.
3. **#3 Parallelize Steps 2/2b** — docs only, low risk. Combine with
   the dependency-graph diagram above for clarity.
4. **#4 Bump Read batch size** — one-line docs change.

All four are independent — no ordering dependencies. They could ship as
one PR or four, agent's choice.

---

## Evidence trail

- Run timestamp: 2026-05-17 around 22:36 local.
- Output: `~/Downloads/video-lens/reports/2026-05-17-223608-video-lens_SVOrURyOu_U_designing_data_intensive_applications_with_martin_kleppmann.html`
- Failed render attempts:
  - Attempt 1: `ERROR:RENDER_INVALID_JSON Expecting ',' delimiter: line 15 column 2905`
    — caused by embedded `"…"` in KEY_POINTS via `<em>"failures are rare, don't worry"</em>`.
  - Attempt 2: `ERROR:RENDER_MISSING_KEYS ['META_LINE']`
    — payload omitted META_LINE per SKILL.md guidance.
  - Attempt 3: successful (META_LINE explicitly composed; JSON built via
    `json.dumps`).
- Both fetch scripts confirmed independent: `fetch_metadata.py` signature is
  `python3 fetch_metadata.py VIDEO_ID`; `fetch_transcript.py` is
  `python3 fetch_transcript.py VIDEO_ID LANG_CODE`. Neither reads the other.
