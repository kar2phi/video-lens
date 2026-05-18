# 018 — `Write` missing-`content` glitch: analysis and options

> **Status:** working document for iteration in another session. Two observed occurrences so far. No code changes recommended yet.

## The error

During Step 4 of the video-lens skill, the model invokes the `Write` tool to drop the JSON payload at `PAYLOAD_PATH`. On at least two separate sessions the harness has returned:

```
InputValidationError: Write failed due to the required parameter content is missing.
```

In both cases the model's *next* attempt (same approach, possibly same content) succeeded. The recovery loop works; the symptom is annoyance and a wasted turn, not a stuck flow.

## What the in-session model proposed

After the second occurrence, the in-session model attributed the glitch to a transient parsing failure on a ~8 KB JSON payload with nested escaped quotes from `<em>"…"</em>` patterns in `KEY_POINTS`, and proposed three changes:

1. **Retry on Write failure** — add an `ERROR:WRITE_FAILED` row to the skill's error-handling table instructing a single retry before falling back to a heredoc.
2. **Escape embedded quotes more carefully** — replace literal `"` inside `<em>"…"</em>` with HTML entities (`&ldquo;`/`&rdquo;` or `&#8220;`/`&#8221;`) to avoid JSON-parsing ambiguity.
3. **Add a catch-all for tool-level transient errors** — extend the error-handling table to cover Write/tool failures, not just `ERROR:RENDER_*` / `ERROR:SERVE_*`.

## Critique of the in-session proposal

### #1 and #3 are the same anti-pattern

The skill's error-handling table covers **domain-specific script errors** that the bundled Python scripts emit (`ERROR:RENDER_*`, `ERROR:SERVE_*`). A failed `Write` is a **harness-level** `InputValidationError`, not a script error. The model sees that error in its tool result and already retries by default — adding a skill-level row teaches the model to look up tool semantics in skill docs instead of from the actual tool result. Same anti-pattern as the rejected "Write requires content" reminder analyzed in plan v1 of this thread. It bloats the skill without changing model behavior.

### #2 has a wrong technical premise

The hypothesis: nested escaped quotes overwhelmed the harness's JSON parser.

The reality: a literal `"` inside a JSON string is encoded as `\"` on the wire. JSON parsers handle that fine, regardless of payload size — there is no second-level parsing where unescaped quotes would matter. If payload size contributed at all, the more plausible mechanism is **token generation**, not parsing — the model's output stream gets clipped mid-tool-call when content is long. HTML entities don't fix truncation; they just change the tokens before the clip.

The cost of #2 is also real: `&ldquo;`/`&rdquo;` render as **curly quotes** in the report. Switching globally changes report typography. That's a content design decision (do reports look "editorial" with curly quotes, or "code-y" with straight?), not an escaping fix.

### What the actual mechanism probably is

Best-guess hypothesis (unverified): the model is mid-generating a long tool-call when its output stream is interrupted, truncated, or otherwise loses the `content` field. The harness sees a tool call missing a required parameter and rejects it. The model retries (with normal-length output), it works.

This is consistent with:
- Both observed failures involved ~8 KB payloads (not tiny, not enormous).
- Retry "with the same approach" succeeds — meaning the *content* was always valid; the *first call* was malformed.
- It's the same failure class as the very first session this thread analyzed (also "missing content," also recovered on retry).

## Options

Ranked from "do nothing" to "structural change."

### Option A — Do nothing (current recommendation)

Two observations across an unknown time window is below the threshold for action. Both fumbles self-recovered. The proposed fixes either solve nothing real or impose typographic cost.

**When this becomes wrong:** if the error rate crosses ~3+ occurrences in a tight window (a week, say) or if a single session ever fails to self-recover.

### Option B — Reduce payload size by splitting the description out

The single biggest field in the payload is usually `DESCRIPTION_SECTION` — yt-dlp's full HTML-escaped, linkified description, inlined as a multi-KB HTML string. For descriptive videos that field alone can be 4–6 KB.

Add to `render_report.py` a `--description-file <path>` flag that reads the description HTML from a file instead of from the `DESCRIPTION_SECTION` field. Have `preflight.py` emit a `DESCRIPTION_PATH` for the run, mirroring how it already emits `PAYLOAD_PATH`. The model writes the description with one Write call, the (much smaller) payload with another.

**Effect:** halves the `content` field length on the largest payloads, which directly addresses the output-token-truncation hypothesis.

**Cost:** one new flag, one new preflight line, one new instruction in Step 4 of SKILL.md ("Write description, then write payload"). Test coverage in `test_e2e.py` needs a new fixture path.

**Risk:** if the truncation hypothesis is wrong, this is renderer churn for no gain.

### Option C — Move the payload off the `Write` tool entirely

Have `render_report.py` accept a base64-encoded payload via `--payload-b64 <base64>`. The model `Bash`-encodes the JSON in a single shell call: `python3 render_report.py --payload-b64 "$(python3 -c 'import json,base64; print(base64.b64encode(json.dumps({...}).encode()).decode())')"`. No file write, no Write tool invocation, no truncation risk on a specific tool.

**Effect:** sidesteps the Write tool failure mode entirely.

**Cost:** SKILL.md Step 4 rewritten (the central instruction switches from "Write the payload" to a Bash one-liner). Harder to debug — JSON is no longer inspectable on disk. Bash escaping rules around the `$()` substitution might create their own quote-related issues. Loses the heredoc-vs-Write rationale at SKILL.md:201 (which only argued *against* heredoc, not against `Write`).

**Risk:** trades a known one-off glitch for an unknown set of Bash-quoting glitches.

### Option D — Switch to typographic quotes via HTML entities

Take the in-session model's suggestion #2 *as a typography change* (not as an escaping fix). Update SKILL.md's "Key Points" examples at line 119/125 to use `&ldquo;…&rdquo;` for speaker quotes. Reports get curly quotes; the model generates entity references instead of literal `"` inside tool calls.

**Effect:** removes one specific class of in-string escapes from the typical payload. Marginal; doesn't address payload size or truncation.

**Cost:** typographic style change applies to *all* reports going forward, including non-quoted text where it doesn't matter. Old reports use straight quotes; visual consistency across the gallery degrades unless you backfill.

**Risk:** changes the visual brand of the reports for an unproven escaping benefit.

### Option E — Codify a "retry on InputValidationError" rule in SKILL.md

Add one sentence to Step 4: "If `Write` fails with a harness-level error (e.g. `InputValidationError`), retry the same call once before considering the run failed."

**Effect:** documents the recovery the model already performs by default.

**Cost:** one-line skill addition. But — and this is the same critique that killed the v1 plan — it teaches the model to look up tool-error handling in skill docs, expanding skill scope into tool semantics.

**Risk:** anti-pattern accumulates over time. Other tool errors get table rows for similar reasons. Skill bloats with redundant tool-API documentation.

## Open questions to resolve in the next session

1. **How many occurrences total?** Plan v1 was decided at N=1; the current state is N=2 across this thread, but I don't have visibility into other sessions. If the user has logs (e.g. agent transcripts), counting actual occurrences in the last 30 days would either justify or kill structural change.
2. **Are all failures correlated with payload size?** If yes, Option B (description split) is the surgical fix. If no — e.g. some failures on small payloads — Option B doesn't help and Option C or A are the choices.
3. **Does the in-session model always recover on retry, or has it ever stalled?** A single non-recovery would push toward Option C (eliminate the Write tool entirely). Recovery so far has been 2/2.
4. **Is the typographic question (Option D) worth deciding independently?** Even if it doesn't fix the glitch, curly vs straight quotes is a separate design choice. If the user wants curly, it's a one-line skill change.

## Recommended path

For now: **Option A**. Document this analysis, watch for recurrence.

If recurrence justifies action and there's a size correlation: **Option B**. It's the smallest structural change that targets the most plausible mechanism, and the description split has independent benefits (cleaner separation of agent-authored summary content from passthrough yt-dlp text).

Avoid Options #1/#3 from the in-session proposal — they look helpful and aren't.
