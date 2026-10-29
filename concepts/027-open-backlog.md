# 2026-10-22 — Open backlog after 5.4

**Scope.** Every item still open after 5.4, from `concepts/025` (R1–R5, §7, §10), the 024
carry-overs, and the 5.4 review. One list to pick from in a later session, or to decide
on. Items keep their source ID (`025-R1`, `024-H2`) so the original reasoning stays one
search away. New items from the 5.4 review are `027-B*` and `027-E*`.

**Status legend.**

- **Ready**: decided, with a known shape. Pick it up and build it.
- **Decide**: a real option, but whether, or how, is still open. The question is spelled
  out.
- **Parked**: decided against for now. Reopen only on demand.

**Rules that apply to every item** (from `CLAUDE.md` and 025 §11):

- Tests first for any script change.
- Judge any SKILL.md or payload change with `task eval` on both arms (`REF=HEAD` against
  the working tree) and `task eval-compare`, on Claude *and* qwen.
- Judge every prompt rule by whether a ~30B local model will follow it. Prefer moving
  rules into code or into the payload's shape over adding wording.
- After editing, run `task install-skill-local AGENT=agents`, and `task build-index` for
  gallery changes.

---

## At a glance

| ID | Item | Status | Effort | Depends on |
|---|---|---|---|---|
| **027-B1** | `en` with a filler word sets no language | Done | XS | — |
| **027-B2** | A language name inside a focus request becomes the transcript language | Done (a) | S | — |
| 027-B3 | Two minor edges: `--replace` date format, `zh-Hans` ↔ `zh-Hant` | Done | XS | — |
| **027-E1** | Eval fixtures for a focus request and a revision | Built; baseline not run | S | — |
| **025-R1** | `KEY_POINTS` / `OUTLINE` as JSON arrays | Built; A/B pending | M | E1 |
| **025-R5** | Payload lint with one retry (024-N4) | Built (marker); A/B pending | M | R1; R2 or a marker |
| 025-R3 | One fetch call instead of two | Ready | S–M | — |
| 025-R4 | Index rebuild and serve in one call | Ready | S | — |
| 025-R2 | Run directory: scripts hand data to the renderer | Ready | M | — |
| 024-N1 | Transcript sidecar | Ready | S after R2 | R2 |
| 024-U6 | `<html lang>` and provenance in meta (023-F2/F3) | Ready | S after R2 | R2 |
| 024-U1 | Gallery groups re-runs of one video | Ready | M | U3 (model names) |
| 025-§4.3 | Render errors that carry their own fix | Done, with R1 | S | — |
| 025-S3c | First Step 3 compression pass | Decide | M | E1, R1, R2 |
| 024-H2 | Env vars switch off the output-path clamp | Decide | M | — |
| 024-H3 | Scoped permissions for the Raycast launcher | Decide | M | — |
| 024-T2 | Tests for `backfill_meta.py` and `serve_report.sh`; error streams | Decide | S | — |
| 024-U3 | Normalise `agentModel`; backfill old metadata | Decide | S–M | — |
| 024-U5 | Print stylesheet, `prefers-reduced-motion` | Decide | S | — |
| 024-U7 | Back-link from a report to the gallery | Decide | S | — |
| 024-N3 | `preflight.py --doctor` | Decide | S | — |
| 024-N2 | Whisper progress output, `large-v3-turbo` | Decide | S–M | — |
| 024-U2 | One-off merge of singleton tags | Decide | M | — |
| — | Cross-platform Whisper, Windows CI, Shorts, batch mode, non-YouTube sources | Parked | — | — |
| 026 | `video-lens-recs`, a third skill | Separate track | L | its own spec |

A suggested order is at the end (§6).

**Progress, 2026-10-24.** B1–B3, E1, R1, R5 and §4.3 are built, tests first, on branch
`kar2phi/backlog-027` (CHANGELOG `[Unreleased]`). Choices made on the way:

- **B2:** option (a). A name also counts alone in its clause, so `Spanish, focus on
  pricing` keeps `es`; `explain it in plain English` no longer sets `en`.
- **B3 `zh-Hans`:** neither of the two options. Excluding the script match would fall
  back to the original track, often English, which is worse than the other script. A
  same-script or script-less track wins; another script is used with a `LANG_WARN:`.
- **R1:** the renderer builds the HTML string from the items and sends it through the
  existing sanitiser, so security stays in one place and the output is byte-identical.
  Lenient where a retry would be wasted: `t` as `"12:34"`, a list of `<li>` strings,
  `<strong>`/`<em>` typed inside item text. Strict, with the fix in the message, on unknown
  item keys such as `paragraph`.
- **R5:** a marker file (`.render-lint`) in the per-run payload directory, not R2. Any
  rejection sets it, not just the lint's, because SKILL.md allows one retry: a run
  rejected for bad JSON must not then be stopped again by the lint. A successful render
  clears it, so a revision gets its own single stop.
- **E1:** `focus` reuses the `lang-request` video and transcript, which makes
  `lang-request` its no-focus control (`focus_kp_share` on both). `revision` resumes the
  same agent session for the second turn.

Not yet done: the E1 baseline and the R1 + R5 A/B on Claude and qwen. YouTube blocked
this IP's transcript requests all session, and the eval cannot fetch its inputs.

---

## 1. Bugs found in the 5.4 review

### 027-B1. `en` next to a filler word sets no language — Ready, XS

`parse_request` in `preflight.py` drops `en` as filler, because it means "in" in Spanish
and French (`resumen en español`). As a result, English, the most likely request, fails
whenever it comes with any other word:

| Request | Result | Expected |
|---|---|---|
| `en` | `en` | `en` |
| `en subtitles` | *(empty)* | `en` |
| `in en` | *(empty)* | `en` |
| `with en captions` | *(empty)* | `en` |

The existing tests cover `in es` and `de subtitles`, but no English case.

**Fix.** When the request holds only filler words and one of them is `en`, use `en`.
Other code-shaped filler words (`in`, `an`, `im`) must not count. A request with any
other word keeps today's behaviour, so `resumen en video` stays an `EXTRA_REQUEST`. Add
the three rows above to
`test_preflight_parses_language_requests`, and keep `resumen en español` → `es`.

### 027-B2. A language name inside a focus request becomes the transcript language — Ready, S

A language name counts anywhere in the request, so:

- `focus on the German economy` → `LANG_CODE: de`
- `explain the thai food part` → `LANG_CODE: th`

`EXTRA_REQUEST:` carries the request correctly, but the language request is wrong. The
damage depends on the video:

- **The video has an auto-dub in that language.** The fetcher ranks dubs last but still
  matches them when asked for. The summary is then written in that language from a
  machine-translated dub.
- **It has no such track.** The report gets a false `⚠ Requested language not available`.

SKILL.md covers only the opposite case: a language that `LANG_CODE` missed.

**Options.**

- (a) Count a name only next to a language cue (`in`, `auf`, `en`, `subtitles`,
  `captions`, `transcript`), or when the request holds nothing else. *Recommended*: it is
  deterministic and needs no prompt change.
- (b) Keep the parsing, and tell the agent to clear `LANG_CODE` when the name is part of
  the focus. That is a prose rule, which is weak on qwen.

**Tests.** Add `focus on the German economy` → `("", <verbatim>)`, and keep the existing
`in Spanish, focus on pricing` → `("es", <verbatim>)`.

### 027-B3. Two minor edges — Ready, XS

- `render_report.py --replace` does not check the format of a `GENERATION_DATE` the
  payload supplies; only `--output-dir` does. Apply the same `YYYY-MM-DD` check.
- `pick_transcript` falls back to the primary subtag, so a `zh-Hans` request can match a
  `zh-Hant` track: the same language, but another script. Either exclude script subtags
  (`Hans`, `Hant`, `Latn`, `Cyrl`) from the subtag fallback, or accept the match and
  document it.

---

## 2. Measurement first

### 027-E1. Eval fixtures for a focus request and a revision — Ready, S

5.4 added `EXTRA_REQUEST:` (Step 3 weights it) and `--replace` (the Revisions section).
No fixture in `evals/fixtures.json` exercises either, so the eval cannot see whether a
model follows them. Add:

- **A focus fixture.** A video plus `focus on <a section that exists>`. Check that the
  focus shows up in the Summary or the Key Points, and that the other sections are still
  covered.
- **A revision fixture.** A second turn, such as "tighten the takeaway". Check that the
  report's file count stays the same, `generationDate` is unchanged, the Takeaway differs,
  and the HTML was never edited directly (the trace has no `Edit` of the report).

This is the baseline that R1, R5 and any Step 3 compression are measured against.

---

## 3. Decided, ready to build

The order follows 025 §11: R1 and R5 first, because they are the levers for qwen's output
quality.

### 025-R1. `KEY_POINTS` and `OUTLINE` as JSON arrays — Ready, M

**Why.** In the library, 51 % of qwen reports have no Key Point paragraphs, against 4 %
for Claude, and all 7 outline timestamp mismatches come from qwen. Both are structural:
the model writes HTML by hand, and writes each timestamp three times in two formats.

**Shape.** As in 025 §5 R1:

```json
"KEY_POINTS": [{"point": "…", "why": "…", "detail": "2–4 sentences, **bold**, *italic*"}],
"OUTLINE":    [{"t": 754, "title": "…", "detail": "One sentence."}]
```

The renderer escapes the text, converts `**`, `*` and `` ` ``, and builds `data-t`, `&t=`,
`▶ M:SS` and the `href` from `t` and `VIDEO_ID`. The emitted HTML is identical to today's,
so the template, the Markdown export, `build_index` and the gallery do not change. A
string value still goes through the current sanitiser, so old payloads keep working.

**Start with:**

1. Renderer tests: an array payload renders byte-identical HTML to the equivalent string
   payload.
2. The renderer change.
3. The SKILL.md Step 4 table: the two longest rows shrink, and "Common rejection causes"
   mostly goes.
4. `task eval` on Claude and qwen, against E1's baseline.

### 025-R5 / 024-N4. Payload lint with exactly one retry — Ready, M

**What.** On the first render, check these deterministic properties:

- Key Point count is 3–8;
- `detail` is present on most Key Points;
- outline `t` increases and stays within the video's duration;
- there are 3–5 tags;
- `TAKEAWAY` is not a near-copy of `SUMMARY`.

If any fails, stop with `ERROR:RENDER_LINT <list>` and write nothing. A second render
turns the lint into warnings and always succeeds, so a run can never get stuck.

**Depends on.** R1 for the `detail` and `t` fields. It also needs somewhere to record the
first attempt: the R2 run directory, or a marker file in the payload directory, which
already exists per run.

**Why.** It is the only lever that raises qwen's quality without more prompt text.

### 025-R3. One fetch call instead of two — Ready, S–M

Run `fetch_metadata.py` in a thread inside `fetch_transcript.py` (or behind a
`--with-metadata` flag), and print the metadata block before the transcript. This
guarantees concurrency on every agent, since small models often serialise "two calls in
one message". It also removes the "wait for 2b before the fallback" instruction.

It gives the track picker `YTDLP_LANGUAGE` before it chooses, a second signal next to the
`variant=timing-optimized` dub marker 5.4 relies on.

Its precondition, 024-T1 (`tests/test_fetch_transcript.py`), is now done.

### 025-R4. Index rebuild and serve in one call — Ready, S

Preflight prints `GALLERY_SCRIPTS_DIR:`, which retires the second 8-directory discovery
loop. Steps 5 and 6 become one Bash call:
`build_index … || echo WARNING…; bash serve_report.sh …`. The `HTML_REPORT:` success gate
stays as it is. That saves one model round-trip per run, which matters at qwen's 237 s
median.

### 025-R2. A run directory — Ready, M

Preflight's per-run `0700` directory becomes the place where scripts hand data to the
renderer:

- `run.json` comes from preflight;
- `metadata.json` and `transcript.txt` come from the fetch step;
- the agent writes content only;
- `render_report.py --run-dir DIR` merges them, and payload keys win.

About 11 payload fields go, along with the `META_LINE` override logic and the
hand-copied description HTML (median 1.3 KB of output tokens per run). Old payloads keep
working.

### 024-N1. Transcript sidecar — Ready, S after R2

Copy `transcript.txt` next to the report. That one file enables:

- re-summarising with another focus without fetching again;
- quote lookup;
- "ask my library" grounded in real text;
- re-rendering for free when the template changes.

It also keeps an 8-minute Whisper transcription from being thrown away. It needs about
50 KB per report.

**One question to settle first:** the file name, which must be one that `build_index`
and the gallery ignore.

### 024-U6 + 023-F3. `<html lang>` and provenance in the meta block — Ready, S after R2

Both pages hardcode `<html lang="en">`. With `lang` and `source` (captions or Whisper)
coming from the run directory, the renderer can set the attribute and record both in
`VIDEO_LENS_META`. The gallery can then filter by language and mark locally transcribed
reports.

### 024-U1. The gallery groups re-runs of one video — Ready, M

Decided in 025 §11 Q4: re-runs are model comparisons. Group manifest entries by
`videoId`, show the newest as the card, and add a "3 versions" affordance that lists them
by `agentModel`. This is a gallery-only change: `videoId` is in every meta block.

**Before it.** 5.4 strips `[1m]` from new reports, but:

- the 5 older reports still carry it;
- model names differ in other ways too (`qwen3.6` against `qwen3.6:35b-a3b-coding-mxfp8`).

Decide the grouping key under 024-U3.

### 025-§4.3. Render errors that carry their own fix — Ready, S

SKILL.md Step 4 still lists "if the renderer rejects the payload" causes and fixes that
every run pays for. Move each fix into the matching renderer error message instead, for
example `RENDER_DISALLOWED_HTML: "<branch-name>" was parsed as a tag; rephrase without
angle brackets and retry once`. The model then sees the fix only when it needs it. R1
removes most of these cases anyway, so do this after R1, or together with it.

---

## 4. Needs a decision

### 025-S3c. A first Step 3 compression pass — Decide, M

Step 3 is about 8 KB, and 016/P3.8 protects its content guidance until an eval can show
that a cut costs nothing.

**Question.** After R1 and R2 shrink Step 4, is a Step 3 cut still worth an eval cycle on
both models?

**Recommendation:** decide after R1. Run the E1 baseline first.

### 024-H2. Env vars switch off the output-path clamp — Decide, M

`validate_output_path` returns early when `PYTEST_CURRENT_TEST` is set, or when
`VIDEO_LENS_ALLOW_ANY_PATH=1`. Anything that can set an environment variable in the
renderer's process can then write HTML anywhere the user can.

**Fix.** Tests inject the root instead: monkeypatch `ALLOWED_OUTPUT_ROOT` in-process, or
pass a flag in subprocess tests.

The number of tests to touch grew in 5.4: the `--replace` tests use
`VIDEO_LENS_ALLOW_ANY_PATH` through `_render_cli`.

**Question.** Is a narrow bypass that only tests use worth a mechanical refactor?
*Recommended: yes*, because it removes a production branch that exists only for tests.

### 024-H3. Scoped permissions for the Raycast launcher — Decide, M

The Raycast launcher runs the agent with `--dangerously-skip-permissions` and plain
`Bash`, over transcripts that are untrusted by construction. Command-scoped rules could
confine it to the scripts it actually runs:

- `Bash(python3 *preflight.py*)`
- `Bash(python3 *render_report.py*)`
- `Bash(bash *serve_report.sh*)`
- the other scripts the skill calls, in the same form.

The six per-agent flag variants in `install-raycast` make this a half-day experiment.

**Question.** Is the residual risk worth the experiment, given the trade-off is already
accepted in 013?

### 024-T2. Remaining test gaps, and which stream errors go to — Decide, S

Two tests are missing:

- `backfill_meta.py` rewrites reports in place, but only its script-closer escaping is
  tested; `--dry-run` and the rewrite are not.
- The URL prefix strip in `serve_report.sh` has no test.

**Error streams.** 024 proposed moving every error code to stderr. Since 5.4, all of
`fetch_transcript.py`'s codes are on stdout, and the skill reads them there.

**Question.** Keep stdout for the fetch scripts and close that half of T2, or move to
stderr as a contract change? *Recommended:* keep stdout, and document it.

### 024-U3. Normalise `agentModel`, and backfill old metadata — Decide, S–M

About half the library predates `agentModel`, `generatedAt` and `durationSeconds`, and
the model strings vary in form. This decides how U1 groups reports.

**Question.** Group by the full model string, or by a normalised family-plus-size key?

Whichever it is, a `backfill_meta.py` pass can also strip `[1m]` from the 5 older reports.

### 024-U5. Print stylesheet and `prefers-reduced-motion` — Decide, S

Printing a report today includes the video frame and the control bar.

**Question.** Do you print or save reports as PDF? If not, park it.

### 024-U7. Back-link from a report to the gallery — Decide, S

The gallery links out to reports, but nothing links back. A small link in the report
header to `../index.html` would do it. The server's root is `~/Downloads/video-lens`, so
the link resolves when the report is served. Check the `file://` case: the gallery loads
`manifest.json` with a fetch, which browsers may block there.

### 024-N3. `preflight.py --doctor` — Decide, S

5.4's `CAPABILITIES:` already holds the probe. `--doctor` would print it for humans,
adding:

- the Python version and the `youtube-transcript-api` version;
- the reports directory and its report count;
- whether port 8765 is free.

**Question.** Is a paste-able diagnosis worth it for outside users (the Windows
contributor)? It is cheap.

### 024-N2. Whisper progress and `large-v3-turbo` — Decide, S–M

The fallback prints nothing for minutes. A `PROGRESS: 12:34 / 1:28:00` line on stderr
would give the agent's poll something to show. `large-v3-turbo` is about 4–6× faster
than `large-v3` at similar accuracy.

**Question.** Is the fallback used enough to matter? The library has 1 Whisper report in
205.

### 024-U2. One-off merge of singleton tags — Decide, M

206 of 305 tags are used only once. `EXISTING_TAGS` already steers new reports, so the
ratio improves on its own. A human-reviewed merge pass over the manifest is only a
nice-to-have.

---

## 5. Parked

| Item | Why parked | Reopen when |
|---|---|---|
| Cross-platform Whisper backend (`faster-whisper`) | 025 §11 Q3: macOS/Linux supported, Windows best-effort | Linux or Windows users ask for the fallback |
| Windows CI | Same decision | Windows becomes a supported platform |
| Shorts support | 025 §7: the embed and the duplicate logic assume a landscape watch page; no one has asked | Someone asks |
| 024-N5 batch / playlist mode | Needs a spec (concurrency: fetches parallelise, Whisper does not) | A spec is written |
| 024-N6 non-YouTube sources | Architectural: everything assumes an 11-character YouTube ID; a v6 feature | A spec is written |
| 007 incremental indexing | 0.05 s at 180 reports | The library grows by an order of magnitude |
| 025 R1-lite (escape instead of reject) | Superseded by full R1 (§11 Q2) | R1 is abandoned |

---

## 6. Separate track: `video-lens-recs`

`concepts/026-video-lens-recs-concept.md` is the approved spec for a third skill that
recommends YouTube videos by topic. It was built (phases P0–P5) and merged in PR #10 on
2026-10-29; its open owner decisions are in 026 §17. Its P5 video-lens change, a
`channelId` in the meta block plus a backfill, shipped with it, so R2 builds on top of it.

---

## 7. Suggested order

1. **027-B1 and B2** (with B3 alongside): small, tested, and they fix a 5.4 feature.
2. **027-E1:** the baseline everything below is measured against.
3. **025-R1, then R5:** the qwen quality levers, together with §4.3.
4. **025-R3 and R4:** fewer round-trips. They are independent of each other.
5. **025-R2,** then N1 and U6, which fall out of it.
6. **024-U3, then U1:** gallery grouping.
7. **The decide list,** in any order; most items are S.
