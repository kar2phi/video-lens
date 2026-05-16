# video-lens Skill Challenge & Simplification Audit

Date: 2026-05-15

## Scope

Challenge the current `video-lens` skill for unnecessary complexity, token bloat, and redundancy — both in the prompt (SKILL.md) and in the recent uncommitted changes. Cross-reference with the prior audit in `concepts/014-skill-simplification-and-recent-changes-audit.md` (28 findings) to avoid duplication.

Reviewed files:
- `skills/video-lens/SKILL.md` (371 lines)
- `skills/video-lens/scripts/render_report.py` (357 lines)
- `skills/video-lens/scripts/serve_report.sh` (87 lines)
- `skills/video-lens/template.html` (1996 lines)
- `scripts/yt_template_dev.py` (161 lines)
- `Taskfile.yml` (146 lines)
- `tests/test_e2e.py` (364 lines)
- `concepts/014-skill-simplification-and-recent-changes-audit.md` (28 findings)

## Criticality and Complexity Scale

Same as 014.

**Criticality:** Critical / High / Medium / Low

**Complexity:** XS / S / M / L

## Executive Verdict

The existing audit (014) is thorough and its 28 findings are accurate. This challenge goes further: it asks whether the *entire approach* can be simpler.

Three structural problems remain:

1. **SKILL.md is a spec document, not a skill prompt.** At 371 lines it forces the agent to hold renderer internals, error codes, tag allowlists, and telemetry protocols in working memory. Every one of those is already enforced by `render_report.py`. The prompt should only say what, not how.

2. **The recent hardening added safety but also added 125+ lines of prompt-level implementation detail.** The Bundled scripts section, the Untrusted input guardrail, the tag allowlist table, and the expanded error table are all correct but redundant with renderer-enforced policy.

3. **Some recent additions solve problems that don't exist for the primary use case.** `durationSeconds` (agent computes it manually), `modelName` (Claude-specific in a multi-agent skill), and the detailed per-key allowlist are the main offenders.

The single highest-leverage move: **stop asking the agent to build `VIDEO_LENS_META`**. Move it into `render_report.py` where it can be computed deterministically from fields the agent actually writes. This alone saves ~30 lines of prompt instructions and eliminates an entire class of inconsistency bugs.

## Findings Not in 014

### C1 - The "Untrusted input" guardrail is redundant with the renderer

**Criticality:** Low
**Complexity:** XS

The `Untrusted input` section (SKILL.md lines 118–120) tells the agent not to let transcript content alter output filenames, JSON keys, tag allowlists, or workflow steps. This is correct advice, but `render_report.py` already enforces every one of those constraints:

- Output path is clamped to `~/Downloads/video-lens/reports/`
- JSON keys are validated against `EXPECTED_KEYS`
- HTML tags are allowlist-sanitized
- Placeholder names are fixed by the template

The agent does not need to know about these safeguards. In fact, telling it about them adds cognitive load without changing behavior — the renderer would reject the same bad output regardless.

**Recommendation:** Delete the entire `Untrusted input` subsection. The renderer is the real guardrail.

**Token saving:** ~12 lines / ~300 tokens.

### C2 - The tag/attribute allowlist table in SKILL.md is dead weight

**Criticality:** Medium
**Complexity:** XS

SKILL.md lines 216–223 document a per-key allowlist table. This is the exact same policy already implemented in `render_report.py` lines 34–63. The agent does not need to understand the allowlist to produce correct output — it just needs to produce the expected HTML structure. The renderer will reject anything else.

**Recommendation:** Replace the allowlist table with one sentence:

> `render_report.py` validates and sanitizes HTML-bearing fields. If it returns `ERROR:RENDER_DISALLOWED_HTML`, simplify the field to match the example structure below and retry once.

Keep the examples for KEY_POINTS, OUTLINE, and DESCRIPTION_SECTION — they show the expected structure. Remove the exhaustive tag/attribute table.

**Token saving:** ~8 lines / ~250 tokens.

### C3 - The Error Handling table is 3× larger than necessary

**Criticality:** Medium
**Complexity:** S

The error table has 27 rows. Many map to identical behavior:

| Group | Rows | Behavior |
|---|---|---|
| `ERROR:RENDER_*` | 11 | Report and stop |
| `ERROR:SERVE_*` | 4 | Report and stop |
| `ERROR:YTDLP_*` | 4 | Warn and continue |
| Transcript errors | 8 | Varying behavior |

The agent does not need to memorize 27 error codes. It needs to know:

1. Transcript errors → report (some retry, most stop)
2. yt-dlp errors → warn and continue
3. Render/serve errors → report and stop

**Recommendation:** Collapse to grouped rows:

```markdown
| Error prefix | Action |
|---|---|
| `ERROR:CAPTIONS_*`, `ERROR:VIDEO_UNAVAILABLE`, `ERROR:AGE_RESTRICTED`, `ERROR:INVALID_VIDEO_ID`, `ERROR:IP_BLOCKED`, `ERROR:NO_TRANSCRIPT` | Report and stop |
| `ERROR:REQUEST_BLOCKED`, `ERROR:NETWORK_ERROR` | Retry once; if it fails again, report and stop |
| `ERROR:PO_TOKEN_REQUIRED` | Report and stop |
| `ERROR:TRANSCRIPT_FETCH_FAILED` | Report and stop |
| `ERROR:YTDLP_*` | Warn and continue without enriched metadata |
| `ERROR:RENDER_*` | Report and stop |
| `ERROR:SERVE_*` | Report and stop |
```

**Token saving:** ~20 lines / ~400 tokens. The grouped table is shorter because it removes the per-code detail rows.

### C4 - The Bundled scripts section duplicates what the renderer already does

**Criticality:** Low
**Complexity:** XS

The Bundled scripts section (SKILL.md lines 12–21) describes each script's purpose and states "No remote code is fetched at runtime." This was added in response to the skills.sh audit (concepts/013). It is useful for transparency but adds ~10 lines to every skill invocation.

The key claim — "no remote code is fetched" — is already enforced by the renderer's allowlist and output-path clamp. The agent doesn't need to know the script inventory to be safe.

**Recommendation:** Keep a one-line version:

> This skill uses four local scripts (fetch_transcript, fetch_metadata, render_report, serve_report) that ship with the skill. No remote code is executed.

**Token saving:** ~7 lines / ~200 tokens.

### C5 - The final-message gate is correctly gated but over-specified

**Criticality:** Low
**Complexity:** XS

SKILL.md lines 305–328 specify the success-gated final response in great detail: what to emit, what not to emit, when to skip it, exceptions. The core rule is simple: "only say 'Report ready' if you saw `HTML_REPORT:` in the serve output."

**Recommendation:** Compress to:

> Only emit "Report ready." if `serve_report.sh` printed `HTML_REPORT: <path>` in this run. Otherwise report the error and stop. The final response must be: one success line, the local URL, the file path. Nothing else.

**Token saving:** ~15 lines / ~350 tokens.

### C6 - Step 5 VIDEO_LENS_META instructions are the largest single source of prompt bloat

**Criticality:** High
**Complexity:** M

SKILL.md lines 225–273 describe how the agent must manually build a 12-field JSON object, compute `durationSeconds` via bash arithmetic, get `generatedAt` via another bash command, extract `keywords` from KEY_POINTS `<strong>` tags, and truncate `summary` to 300 characters. This is 49 lines of deterministic work that the agent must get right every time.

**Recommendation:** Move metadata assembly into `render_report.py`. The agent passes a simplified payload:

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
  "MODEL_NAME": "claude-opus-4-7"
}
```

The renderer computes: `filename`, `generatedAt`, `generationDate`, `keywords` (from KEY_POINTS `<strong>` tags), `summary` (truncated to 300 chars), and assembles `VIDEO_LENS_META`.

This is the single highest-impact simplification. It removes ~50 lines of prompt instructions and eliminates an entire class of agent errors (wrong duration arithmetic, missing fields, inconsistent date formats).

**Token saving:** ~49 lines / ~1200 tokens.

### C7 - The "Output to the user" section is over-specified

**Criticality:** Low
**Complexity:** XS

SKILL.md lines 299–329 describe chat output behavior in 31 lines. The core rule: emit minimal status during Steps 1–7, and a short success message at the end.

**Recommendation:** Compress to:

> During Steps 1–7: emit short status lines only (one sentence per step).
> Final message: only if `serve_report.sh` printed `HTML_REPORT:`. Then: one success line, the local URL, the file path. Nothing else — no summary restatement, no content excerpts, no next steps.

**Token saving:** ~20 lines / ~400 tokens.

### C8 - Length-Based Adjustments table can be collapsed

**Criticality:** Low
**Complexity:** XS

SKILL.md lines 176–183 have a 9-line table for summary length, key point paragraphs, and outline entries by video length. Most rows are nearly identical (3–4 sentences for long and very long).

**Recommendation:** Replace with prose:

> Summary: 2–4 sentences (short videos get 2, very long get 4). Key Points: 3–8 bullets, governed by content density not video length. Outline: 3–20 entries based on natural topic shifts.

**Token saving:** ~8 lines / ~150 tokens.

### C9 - The Key Points format specification is 3× longer than needed

**Criticality:** Medium
**Complexity:** S

SKILL.md lines 137–160 describe the Key Points format in 24 lines: HTML structure, bullet rules, formatting conventions, paragraph rules, content rules. Much of this is quality guidance that can be expressed more concisely.

**Recommendation:** Compress to:

```markdown
**Key Points** — 3–8 bullets (content density, not video length). Each:
<li><strong>Core claim or term</strong> — one sentence on why it matters.<p>2–4 sentence paragraph: context, causality, connections. Omit only when the headline is a discrete fact that needs no expansion.</p></li>

Rules: include concrete formulations and procedures with enough detail to reproduce; use <strong> for key terms and <em> for speaker's own words; each bullet must add substance beyond Summary and Takeaway.
```

**Token saving:** ~15 lines / ~400 tokens.

### C10 - The Summary/Takeaway/Outline specifications are over-detailed

**Criticality:** Low
**Complexity:** XS

SKILL.md lines 128–156 describe Summary (7 lines), Takeaway (8 lines), Outline (7 lines) in excessive detail for a skill prompt. The agent knows how to write these; the prompt is adding style constraints that can be implied.

**Recommendation:**

Summary: "2–4 sentence TL;DR. For opinion/analysis: thesis + conclusion + stance. For tutorials: goal + outcome."

Takeaway: "1–3 sentences. The one thing the Summary doesn't say. Reference specific content, not generic advice."

Outline: "One entry per topic shift. Title: 3–8 words. Detail: one sentence of context."

**Token saving:** ~15 lines / ~350 tokens.

### C11 - The Steps 2/2b transcript fetch command is duplicated verbatim

**Criticality:** Low
**Complexity:** XS

The `_sd=$(for d in ...)` discovery one-liner appears 5 times in SKILL.md (steps 2, 2b, 5, 6, 7). Each occurrence is ~140 characters. The agent must copy-paste this exactly.

**Recommendation:** Define it once in a "Setup" subsection at the top of Steps, or move discovery into a shared runner script. The 014 audit already covers this (F12, F13).

**Token saving:** ~50 characters × 4 duplicates = ~200 tokens (XS).

### C12 - The DESCRIPTION_SECTION wrapper is agent-built but renderer-enforced

**Criticality:** Low
**Complexity:** XS

SKILL.md line 212 tells the agent to build the `<details>` wrapper for DESCRIPTION_SECTION. The renderer only validates the structure. The agent could just emit the raw description and the renderer could wrap it.

**Recommendation:** Have the renderer auto-wrap non-empty descriptions in the `<details>` structure. The agent just passes the raw description text.

**Token saving:** ~3 lines / ~80 tokens.

## Cross-Reference with 014

| 014 Finding | Addressed by this challenge? | Notes |
|---|---|---|
| F1 - Manual install broken | No (implementation fix, not prompt) | 014 is correct |
| F2 - `render()` bypass | No (implementation fix) | 014 is correct |
| F3 - Dev renderer stale | No (implementation fix) | 014 is correct |
| F4 - Docs stale | No (implementation fix) | 014 is correct |
| F5 - Stale YTDLP_ERROR check | No (test fix) | 014 is correct |
| F6 - Fetch-time errors | No (implementation fix) | 014 is correct |
| F7 - Metadata/title conflict | No (implementation fix) | 014 is correct |
| F8 - Duration inaccurate | **C6** | Subsumed by renderer metadata assembly |
| F9 - modelName Claude-specific | **C6** | Subsumed by renderer metadata assembly |
| F10 - Allowlist duplicates | **C2** | Subsumed by this challenge |
| F11 - VIDEO_LENS_META agent-owned | **C6** | Subsumed by this challenge |
| F12 - Script discovery repeated | **C11** | Subsumed by this challenge |
| F13 - Adjacent template path | No (implementation fix) | 014 is correct |
| F14 - Serve port diagnostics | No (implementation fix) | 014 is correct |
| F15 - Taskfile contradiction | No (implementation fix) | 014 is correct |
| F16 - Fonts transparency | No (implementation fix) | 014 is correct |
| F17 - Long transcript handling | No (implementation gap) | 014 is correct |
| F18 - Description normalizer dead | No (template cleanup) | 014 is correct |
| F19 - Error table too large | **C3** | Subsumed by this challenge |
| F20 - Metadata timeout | No (implementation fix) | 014 is correct |
| F21 - URL linkification | No (implementation fix) | 014 is correct |
| F22 - Gallery backfill path | No (gallery fix) | 014 is correct |
| F23 - Gallery skill gaps | No (gallery fix) | 014 is correct |
| F24 - Markdown export | No (quality, not safety) | 014 is correct |
| F25 - Deno stale | No (docs) | 014 is correct |
| F26 - URL protocol mismatch | No (implementation fix) | 014 is correct |
| F27 - Success gate good | **C5** | Subsumed by this challenge |
| F28 - Sanitizer correct | **C1** | Subsumed — renderer is the real guardrail |

## Simplification Summary

| # | Change | Criticality | Complexity | Est. Token Saving |
|---|---|---:|---:|---:|
| C6 | Move VIDEO_LENS_META into renderer | High | M | ~1200 |
| C3 | Collapse error table to grouped rows | Medium | S | ~400 |
| C5 | Compress final-message gate | Low | XS | ~350 |
| C7 | Compress "Output to user" section | Low | XS | ~400 |
| C9 | Compress Key Points spec | Medium | S | ~400 |
| C10 | Compress Summary/Takeaway/Outline specs | Low | XS | ~350 |
| C2 | Remove prompt-level allowlist table | Medium | XS | ~250 |
| C1 | Remove Untrusted input guardrail | Low | XS | ~300 |
| C4 | Compress Bundled scripts section | Low | XS | ~200 |
| C8 | Collapse Length-Based Adjustments | Low | XS | ~150 |
| C11 | Deduplicate script discovery command | Low | XS | ~200 |
| C12 | Auto-wrap DESCRIPTION_SECTION | Low | XS | ~80 |
| | | | **Total:** | **~4300 tokens** |

## Target SKILL.md Structure (after simplification)

```
--- frontmatter (9 lines) ---
## Bundled scripts (1 line)
## When to Activate (5 lines)
## Steps
  1. Extract video ID + duplicate check (10 lines)
  2. Fetch transcript (8 lines)
  2b. Fetch metadata (6 lines)
  3. Generate summary content
     - Summary (3 lines)
     - Takeaway (2 lines)
     - Key Points (4 lines)
     - Outline (3 lines)
     - Tags (3 lines)
     - Keywords (1 line)
     - Length adjustments (1 line)
  4. Output filename (4 lines)
  5. Fill template (10 lines — no VIDEO_LENS_META instructions)
  6. Serve (4 lines)
  7. Rebuild index (4 lines)
## Output to user (4 lines)
## Error Handling (8 grouped rows)
```

**Estimated target: ~120–140 lines vs. current 371 lines (~60–65% reduction, ~4300 tokens saved).**

## What Not To Simplify

| Area | Reason to keep as-is |
|---|---|
| Content quality guidance (thesis, takeaway, synthesis) | This is the skill's core value — the agent's judgment is the differentiator |
| Activation rules | Necessary for correct trigger behavior |
| Video ID extraction rules | Necessary for robust URL parsing |
| Renderer sanitizer | Already in scripts, not in prompt; the real security boundary |
| Success-gated final response | Correct behavior, just needs wording compression |
| Template HTML (1996 lines) | Functional, portable, local. Only remove dead code (F18) |

## Recommended Execution Order

1. **C6** (move VIDEO_LENS_META to renderer) — highest token savings + eliminates agent error surface
2. **C9 + C10** (compress content specs) — preserves quality guidance in half the space
3. **C3** (collapse error table) — reduces prompt bloat without losing behavior
4. **C2** (remove prompt allowlist) — renderer already enforces it
5. **C5 + C7** (compress final message + output to user) — straightforward compression
6. **C1** (remove Untrusted input) — renderer is the real guardrail
7. **C4 + C8 + C11 + C12** (minor compressions) — small wins

After these changes, the skill should be ~130 lines, ~4300 tokens lighter, and functionally identical. The agent has the same content-quality guidance, the same error handling behavior, and the same security guarantees — just expressed more concisely because the renderer handles the deterministic parts.
