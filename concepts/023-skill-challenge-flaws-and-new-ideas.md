# 2026-06-11 — Challenge review: video-lens + gallery — flaws, improvements, new ideas

**Scope:** both SKILL.md files, all eight bundled scripts, `template.html`, gallery
`index.html`, Taskfile, Raycast script, tests (fast suite: 83 passed, 1 skipped),
and the live library at `~/Downloads/video-lens` (145 reports, manifest.json).
Cross-checked against concepts 005 (brainstorm), 008 (UX polish), 010 (transcript
landscape), 021 (skill review), and 022 (whisper plan) so nothing below re-litigates
a decision those docs already made (quick-reference block, gallery rebuild
fast-path, SKILL.md compression pending eval — all left alone).

**Verdict up front:** the pipeline is in good shape — structured errors, the
sanitiser, payload-file rendering, and the preflight/renderer glue relocation all
hold up under scrutiny. The real weaknesses now live at the *library* level: the
collection of 145 reports is becoming a knowledge base, but the skills still treat
every run as a one-off. Most findings below follow from that shift.

---

## 1. Flaws (defects with evidence)

### F1. Payload temp dirs are never cleaned

`preflight.py:123-125` creates a fresh `payload-XXXX/` dir under
`~/Downloads/video-lens/.tmp/` every run; nothing ever deletes them. The live
machine has **30 leftover dirs**, each holding a `payload.json` with the full
report content (disk clutter and a mild privacy smear — summaries persist outside
the reports dir indefinitely).

**Fix:** preflight sweeps `payload-*` dirs older than ~7 days before creating the
new one (`st_mtime` check, `shutil.rmtree`, ignore errors). ~6 lines, no SKILL.md
change, no behaviour change for the current run.

### F2. `<html lang="en">` is hardcoded while reports are written in the video's language

`template.html:2`. A German or Japanese report declares itself English: screen
readers pick the wrong voice, browsers offer to "translate this page" on content
that is intentionally non-English, and CSS hyphenation/quotes are wrong.

**Fix:** new optional payload key `LANG` (the agent already holds the `LANG:` line
from Step 2a/fallback). Renderer validates `^[a-z]{2,3}(-[A-Za-z0-9]+)?$`,
substitutes into the `lang` attribute, defaults to `en`. One template placeholder,
one table row in SKILL.md Step 4.

### F3. Language and transcript provenance are missing from `VIDEO_LENS_META`

`render_report.py:_build_meta_dict` stores neither the report language nor whether
the transcript came from captions or local Whisper — provenance exists only as the
`🎙 transcribed locally` suffix inside the display-only `META_LINE` string. Live
manifest confirms: `language` is absent from every entry. Consequences: the
gallery can never filter by language, and the index loses the
ASR-has-different-error-modes caveat that 022 considered important enough to
disclose.

**Fix:** add `language` (from F2's `LANG` key) and `transcriptSource`
(`"captions"` / `"whisper-medium-local"`, default `"captions"`) to the meta dict;
gallery shows a small 🎙 badge and a language chip row when >1 language exists.
Backfill is unnecessary — old entries just lack the fields.

### F4. Tag vocabulary fragmentation — the tag system doesn't scale past ~50 reports

Live numbers: **281 distinct tags across 145 reports; 190 tags (68%) used exactly
once**; near-duplicates abound (`agents` / `ai agents` / `agentic`, `ai coding` /
`ai-coding`, `engineering` / `software engineering`). Root cause: SKILL.md Step 3's
tag rules enforce consistency *within* one report, but every run invents tags
blind — there is no cross-report feedback, so the filter chips the tags exist for
degrade into noise.

**Fix (cheap, high leverage):** preflight already runs before everything; let it
read `manifest.json` and emit one more line, e.g.
`EXISTING_TAGS: ai, productivity, llm, developer tools, hardware, …` (top ~40 by
count). Step 3's Tags rule gains one sentence: *"Prefer a tag from
`EXISTING_TAGS` when one fits; invent a new tag only when nothing existing
matches."* Optionally, `build_index.py` adds a normalisation pass
(lowercase, hyphen→space) to fold trivial variants. No new scripts, no new steps.

### F5. `GENERATION_DATE` is mechanical glue still riding on the agent

The agent must copy the `DATE:` line from Step 2a into the payload, and a missing
value is a documented "common rejection cause" (`RENDER_PAYLOAD_INVALID`). But the
renderer already computes the filename's `HHMMSS` from `datetime.now()` itself —
it can equally default the date part to today, which is also *more* correct when a
run crosses midnight (date and time then come from the same clock).

**Fix:** renderer defaults `GENERATION_DATE` to `date.today().isoformat()` when
absent; keeps accepting an explicit value. Removes a required field, a rejection
class, and a row of prompt surface. (Same spirit as concepts/019/020 — this one
just got missed.)

### F6–F8. Minor defects

- **F6 — error-stream inconsistency:** `fetch_transcript.py` prints list-stage
  errors to stdout (line 121) but fetch-stage errors to stderr (line 157);
  preflight uses stderr, `fetch_metadata.py` stdout. Harmless to the agent (it
  sees both) but worth one normalisation pass for tests/pipelines: structured
  `ERROR:` lines → always stdout (they are *output*, not diagnostics), exit code
  carries the failure.
- **F7 — error-table drift:** SKILL.md says `ERROR:INVALID_INPUT` is "emitted by
  preflight", but `transcribe_local.py:34` also emits it for an unknown model
  size. One-word doc fix ("emitted by preflight and transcribe_local").
- **F8 — gallery `file://` stale hrefs:** card/list anchors compute their `href`
  at build time, before the async localhost probe sets `window.__vlServerUp`
  (`index.html:1042`, `1275`). Plain clicks recompute via the click handler, but
  middle-click/cmd-click on the title link can open the dead `file://` URL.
  Fix: recompute `href` on `mousedown`, or re-render links when the probe
  succeeds. Edge case (file:// viewing only).

### F9. Raycast/Taskfile model-ID pinning is a standing maintenance tax

`raycast-video-lens.sh` hardcodes `claude-sonnet-4-6` / `claude-opus-4-6` /
`claude-haiku-4-5-20251001`, and `Taskfile.yml:install-raycast` carries a
`MODEL_MAPS` table just to rewrite those IDs per agent. The Claude CLI (and most
others) accept the aliases `haiku|sonnet|opus` directly — using aliases in the
source script deletes the mapping table for every agent except copilot (which
genuinely needs dotted IDs). The pinned IDs are already one generation behind.

### F10. The 8-agent discovery list lives in ≥5 places

Both SKILL.md files (three loop copies), `render_report.py:AGENT_DIRS`,
`Taskfile.yml:install-skill-local`, README. Adding a ninth agent dir requires a
sweep with no checklist. Not fixable by sharing code across prompt/python/yaml —
but CLAUDE.md should carry the canonical list and the sweep locations so the next
edit doesn't miss one. (A grep-based test asserting the lists agree would also be
~10 lines.)

### Observation (accepted risk, noting for the record)

The HTTP server roots at `~/Downloads/video-lens`, so *any* file dropped there is
browsable at `localhost:8765` — today that includes a stray
`session-debug-log.md`. Local-only and low risk, but worth knowing the serve root
is "whatever lands in that folder", not just reports.

---

## 2. Improvements to existing flows

### I1. Persist the transcript as a sidecar (one artifact, four features)

Today the transcript is fetched, read into context, and discarded. Having
`fetch_transcript.py` / `transcribe_local.py` *also* write
`~/Downloads/video-lens/.cache/transcripts/<video_id>.<lang>.txt` (tiny change —
they already build the full text) unlocks:

1. **Duplicate re-runs without re-fetch** — preflight's `DUPLICATE_PATH:` note
   could add `CACHED_TRANSCRIPT:`, skipping the YouTube round-trip and its
   rate-limit risk.
2. **Re-summarise with a different focus** ("again, but for a non-technical
   audience") without refetching — 005's A7, finally cheap.
3. **Ask-the-library** (see N2).
4. A future transcript panel (005's A1) gets its data source for free.

Expire with the same TTL sweep as F1. This is the single highest-leverage small
change in this review.

### I2. Coalesce transcript segments — cut 15–25% of transcript tokens

Auto-captions arrive as ~8-word fragments, each costing a `[M:SS] ` prefix and a
newline (~3–4 tokens of overhead per ~10 tokens of content). `fetch_transcript.py`
could merge segments into ~45–60-second paragraph blocks (one timestamp per
block) by default, with `--raw` as the escape hatch. Effects: materially fewer
tokens into context per video, fewer 1500-line `Read` batches on long videos, and
more readable prose for the summarisation step. The Outline is unaffected —
its entries are minutes apart, far coarser than 60-second anchors. (Concept 010's
S6 flagged the missing long-content strategy; this is the concrete mechanism.)

### I3. Whisper fallback: emit progress

`transcribe_local.py` is silent until done — a 2-hour video means ~10 minutes of
background polling against an empty log, and the agent can't distinguish "model
downloading", "transcribing", and "hung". Print periodic progress to **stderr**
(model-download start/end; then `PROGRESS: [MM:SS reached]` every ~30 decoded
segments — Whisper's `verbose` machinery already surfaces segments as they
decode). Stdout stays byte-compatible with the `fetch_transcript.py` contract.

### I4. Gallery search: tokenise the query

`index.html:803-807` does a single-substring match, so `agent hardware` finds
nothing unless those words are contiguous in one field. Split the query on
whitespace and AND the tokens across the haystack (~5 lines). With 145 reports
this is the difference between search working and not.

### I5. Gallery: group re-runs of the same video

Nothing groups multiple reports for one `videoId` (re-runs are an explicitly
supported flow — preflight just notes the duplicate and proceeds). With 145
reports the library certainly contains versions. Minimal version: when N>1 reports
share a `videoId`, show a small `×N` badge and keep only the newest in the default
view, expanding on click. All data is already in the manifest.

### I6. Gallery stats strip

The manifest already holds durations, dates, channels, tags. A one-line strip
above the grid — *"145 reports · ≈ 80 h of video · top: ai (58), productivity
(27)"* — plus a reports-per-month sparkline makes the library feel like a library.
Pure client-side, no pipeline changes.

### I7. Back-to-gallery link in the report nav

Proposed in 008, still absent: `template.html`'s nav-actions has export / info /
help / theme but no way to get to `localhost:8765/index.html` from a report. One
icon-button (shown only when served over http, hidden on file://). Three lines.

### I8. SKILL.md gap: what to do when the user asks for revisions

Neither skill says what happens *after* Step 6 when the user replies "tighten the
takeaway" or "key point 3 is wrong". The correct flow (re-`Write` the full payload
to a fresh preflight path, re-render, re-serve — do **not** restart from Step 1 or
hand-edit the HTML) is non-obvious; an agent could plausibly edit the rendered
file and bypass the sanitiser. Three sentences in SKILL.md close a real
correctness hole, not just a UX one.

### I9. `preflight.py --doctor`

The dominant cross-agent failure mode is missing dependencies (the error table has
five `*_MISSING` codes). A `--doctor` flag printing presence/version of python3,
youtube-transcript-api, yt-dlp, deno, ffmpeg, mlx-whisper, the template path, and
port-8765 status gives users and agents one command to diagnose an install — and
gives bug reports a standard preamble.

### I10. Reconsider `~/Downloads` as the library home (decision needed, not a patch)

`~/Downloads` is the most purge-prone directory on macOS — auto-cleanup tools and
"clean your Downloads" habits now threaten a 145-report knowledge base. A
`VIDEO_LENS_HOME` env override (default unchanged) touches preflight,
`render_report.py:ALLOWED_OUTPUT_ROOT`, both SKILL.mds, the gallery scripts, and
the Taskfile — a real sweep, so it should be a deliberate decision rather than a
drive-by change. Flagging it now because the migration only gets bigger.

### I11. Previous-roadmap status check (005 Tier 1/2 quick wins)

| 005 item | Status |
|---|---|
| F4 player error recovery | ✅ done (`onPlayerError` embed-disabled fallback) |
| B7 report index page | ✅ done (became the gallery skill) |
| E2 transcript caching | ⬜ open → folded into I1 here |
| B1 copy-section buttons · B2 print stylesheet · B3 expand/collapse-all outline · B4 `#t=` deep links · B8 reading time · F3 lazy iframe · A2 pull-quotes | ⬜ all still open, all still cheap |
| G1 animated README demo | ⬜ open (README has static PNGs only) — still the cheapest growth lever per 003 |

---

## 3. Out-of-the-box ideas

### N1. `video-lens-digest` — make the library more than the sum of its reports

The manifest is a corpus: 145 titles, summaries, tags, channels, dates. A third
skill (or a mode of the gallery skill) could generate cross-report syntheses:
*"what did I learn in May?"*, *"summarise everything I've saved about agents"*,
*"where do my saved creators disagree?"*. Pure prompt work over existing data —
no new fetching, no new infra — rendered as an HTML report reusing the existing
template. This is the natural next step of the gallery: from browsing to
synthesis.

### N2. Ask-the-library

With transcript sidecars (I1) plus the manifest, *"which saved video explained
KV-cache pricing?"* becomes grep over `.cache/transcripts/` + a manifest lookup —
answerable in two tool calls with a deep link (`report.html` + B4's `#t=`) as the
answer. Could start as a documented pattern in the gallery SKILL.md ("when the
user asks a content question about saved videos…") before becoming a feature.

### N3. Channel subscriptions — "watch my subscriptions for me"

The skill's pitch is "watch this for me"; the scheduled-agent ecosystem
(`/schedule`, cron routines) extends it to *standing* coverage: a routine that
checks chosen channels' RSS feeds (`https://www.youtube.com/feeds/videos.xml?channel_id=…`,
no API key needed) for new uploads, runs video-lens on each, and delivers a
morning digest linking the new reports. All building blocks exist; the new work is
a subscriptions file, a feed-check script, and a routine definition. Flagship
candidate for the next cycle — it changes the product category from "tool I
invoke" to "service that briefs me".

### N4. Payload lint — deterministic quality checks before render

The agent is currently the only QA on its own content. The renderer (or a tiny
`lint` pass inside it) can cheaply verify things prompts can't enforce reliably,
emitting non-fatal `WARN:` lines the agent fixes in one re-`Write`:

- Outline timestamps non-monotonic or exceeding the video duration (it has
  `DURATION`);
- duplicated Key-Point headlines;
- `TAKEAWAY` ≈ `SUMMARY` (high token overlap — the rule "never restate the
  Summary" is currently unenforced);
- tag-rule violations (one tag a substring of another, >5 tags).

This extends the repo's structured-error philosophy from *format* to *content
shape* — still deterministic, still no LLM in the loop.

### N5. Obsidian vault export

The user keeps an Obsidian vault (this very `concepts/` folder is one). The
in-browser Markdown export already produces good MD; a renderer flag (or tiny
script) writing `report.md` with YAML frontmatter (title, channel, URL, tags,
date) into a configurable vault folder turns every summary into a linked,
backlinkable note — tags become Obsidian tags, the library joins the second
brain. (005's C2, sharpened by knowing the actual target is Obsidian.)

### N6. Spaced resurfacing

A "Revisit" button in the gallery: open a random report older than 30 days,
weighted toward never-reopened ones. Trivially cheap (manifest has dates), and it
addresses the honest failure mode of all summarisation tools — write-only
archives.

### N7. Standalone share file (005 C4, still the right call)

`render_report.py --standalone`: same report with the player replaced by a
thumbnail + YouTube link, no localhost dependency — the answer to "send this to a
colleague". Worth doing before any thought of hosted/public galleries.

### Considered and rejected

- **Summarise in a subagent to spare main-session context** — tempting (a 3-hour
  transcript is most of a context window), but SKILL.md targets eight agent CLIs
  and subagent semantics are Claude-specific. Revisit as a Claude-only
  optimisation note, not a pipeline change.
- **Custom HTTP server** (delete-report endpoints, headers) — the dumb stdlib
  server is a feature; management actions belong in the gallery *skill*, not in a
  long-running process.
- **Sharing CSS between template and gallery** — self-containment of each HTML
  artifact is deliberate; keep the duplication.
- **Tag-cleanup migration of existing reports** — F4's feedback loop fixes the
  future; rewriting 145 historical reports' meta blocks is not worth the churn
  (the gallery copes with messy old tags once new ones converge).

---

## Status (updated 2026-06-11)

**Done** (committed with tests, full suite green at 87 passed):
- **F4** — `preflight.py` reads `manifest.json` and emits an `EXISTING_TAGS:` line
  (top ~40 by count, variants folded) consumed by SKILL.md Step 3's tag rule
  ("prefer an existing tag when one fits; invent only when nothing matches");
  degrades to silence on a fresh install with no manifest. `build_index.py` adds a
  `_normalize_tags` pass (lowercase, hyphen→space, dedupe) that folds trivial
  variants in the derived manifest only — report HTML is untouched, so the bulk
  rewrite the doc rejected is avoided. Live fold: 281→268 distinct tags. Unit tests
  cover ranking/folding, limit, missing/malformed manifest, main() emit/omit, and
  the build_index normalisation (direct + end-to-end).
  *Review follow-up:* unified the three call sites on one `_normalize_tags(list)`
  helper; `read_existing_tags` now guards `isinstance(tags, list)` (a string tag
  field no longer char-splits) and dedupes variants per report before counting;
  `render_report._build_meta_dict` normalises new reports' TAGS at the write point
  so the embedded meta is clean without a rebuild; and the argv-split preflight
  test was routed through the hermetic helper (no more live `~/Downloads` reads).
- **F1** — `preflight.py` sweeps `payload-*` dirs older than 7 days before creating
  a new one (`sweep_stale_payloads`); unit test added.
- **F5** — `render_report.py` defaults `GENERATION_DATE` to `date.today()` with
  `--output-dir` instead of rejecting; SKILL.md + schema-help updated; the old
  "requires" test flipped to "defaults to today".
- **F7** — error-table doc notes `INVALID_INPUT` is also emitted by
  `transcribe_local.py` for an unknown model size.
- **I4** — gallery search tokenises the query and ANDs tokens across the haystack.

**Still open in the quick-win row:** F2 `lang` attribute · I7 gallery backlink ·
I8 revision-flow paragraph.

## 4. Priorities

**Quick wins (each ≤ ~1 h, no design risk):**
F1 tmp TTL · F2 `lang` attribute · F4 `EXISTING_TAGS` feedback loop ·
F5 `GENERATION_DATE` default · F7 doc fix · I4 search tokenisation ·
I7 gallery backlink · I8 revision-flow paragraph in SKILL.md.

**Medium (half-day each, high value):**
I1 transcript sidecars · I2 segment coalescing · I3 whisper progress ·
F3 language/source in meta + gallery filter · I9 `--doctor` · N4 payload lint ·
I5 videoId grouping · I6 stats strip.

**Strategic (separate specs before building):**
N1 digest skill · N3 channel subscriptions · N5 Obsidian export ·
N7 standalone export · I10 `VIDEO_LENS_HOME`.

The quick-win row is deliberately front-loaded with library-level fixes (F4, F5,
I4): they compound — every report generated before the tag loop lands makes the
vocabulary problem worse, while template polish can wait indefinitely without
getting more expensive.
