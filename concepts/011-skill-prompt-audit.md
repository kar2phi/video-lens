# SKILL.md Prompt Audit — video-lens & video-lens-gallery

## Context

A systematic review of both SKILL.md files, cross-referenced against the 010 optimization report and the actual scripts/template code. The goal was to identify flaws, gaps, ambiguities, and improvements in the skill prompts themselves — the instructions the LLM follows when executing the skill.

---

## 1. video-lens SKILL.md (259 lines)

### 1.1 Error Handling Contradiction (yt-dlp)

**Lines 65 vs 254.** Step 2b says: "If the command fails, report the error and proceed with Step 2 metadata only." The Error Handling table says: "yt-dlp not installed → Print install command and **stop** — yt-dlp is required." These directly contradict each other.

Additionally, `fetch_metadata.py` exits with code 0 on all error paths (lines 67, 70, 76, 82), emitting `YTDLP_ERROR:` as the signal. The script is designed for graceful degradation, yet the error table demands a hard stop.

**Resolution:** Deferred. The current behavior works in practice because the LLM sees the `YTDLP_ERROR:` line and can decide contextually. The contradiction is cosmetic — both paths produce the same outcome (LLM reports the issue). A future pass should align the wording, but it's not causing failures.

---

### 1.2 Step 2 / Step 2b Ordering Ambiguity

**Lines 55–69.** Step 2 instructs: if Bash output is truncated, read the entire file in 500-line batches. Step 2b follows immediately. There is no guidance on sequencing.

**The problem:** For a 2-hour video, reading the full transcript in 500-line batches could take 10+ iterations. Should the LLM finish all batches before running Step 2b? Or run 2b first?

**Analysis:** Step 2b (metadata fetch) is a network call independent of the transcript content. Running it early is strictly better — it lets the LLM have both data sources available before starting Step 3 analysis. The transcript batches can be read afterward.

**Recommendation:** Insert after line 62: explicit guidance to run Step 2b immediately after the Step 2 command completes, without waiting for batched reads. Read remaining transcript batches after Step 2b returns.

---

### 1.3 HTML Escaping Contract Is Inconsistent

**Lines 132, 169, 171, 183.** Multiple conflicting signals about escaping:

| Field | Line 132 (Quote rule) | Step 5 table | VIDEO_LENS_META |
|-------|----------------------|-------------|-----------------|
| SUMMARY | **Not listed** | "Plain text" | "no HTML entities" |
| TAKEAWAY | Listed (use entities) | "plain text" | — |
| KEY_POINTS | Listed (use entities) | HTML content | — |
| OUTLINE | Listed (use entities) | HTML content | — |

**The problem:** SUMMARY and TAKEAWAY are both called "plain text," yet TAKEAWAY must use HTML entities for quotes while SUMMARY apparently should not. SUMMARY's exclusion from line 132 is probably intentional (it feeds into VIDEO_LENS_META.summary which says "no HTML entities") but the omission reads as an oversight.

**Analysis:** The implicit contract is:
- SUMMARY: straight quotes, no entities (because it's reused in VIDEO_LENS_META)
- TAKEAWAY: HTML entity quotes (lives in HTML, not reused elsewhere)
- KEY_POINTS / OUTLINE: HTML entity quotes (HTML content)

This makes sense but needs to be stated explicitly rather than inferred across three separate locations.

**Recommendation:** Add a consolidated "Escaping Rules" block after Quality Guidelines that states the rule for each field in one place.

---

### 1.4 VIDEO_LENS_META summary "~300 characters" Is Vague

**Line 183.** "first ~300 characters of SUMMARY as plain text (no HTML entities)."

- Does "~" mean approximately? Should the LLM aim for 280? 320?
- Should it break at word boundaries or truncate mid-word?
- If the full SUMMARY is under 300 characters, use it entirely or pad?

**Recommendation:** Replace with: "first 300 characters of SUMMARY, truncated at the last word boundary before 300 characters. If the full SUMMARY is under 300 characters, use it entirely. Do not add an ellipsis."

---

### 1.5 VIDEO_LENS_META filename vs build_index.py

**Line 186.** SKILL.md says: "the output filename from Step 4 (basename only)." But `build_index.py` (line 109) overrides the filename with `"reports/" + path.name` for files in the `reports/` subdirectory.

**Analysis:** This is working as designed — `build_index.py` normalizes for the manifest. But the discrepancy is confusing when reading SKILL.md alongside the gallery scripts.

**Recommendation:** Add parenthetical: "(basename only — the gallery index prefixes `reports/` automatically)."

---

### 1.6 Outline Detail Scope for Long Chapters

**Line 117.** "one AI-written sentence summarising the transcript content of that segment." For a 2-hour video with 20 yt-dlp chapters, some chapters span 30+ minutes. A single sentence for 30 minutes of content is extremely compressed, and SKILL.md gives no guidance on what to prioritize.

**Recommendation:** Add: "Focus on the single most important claim, conclusion, or technique from that segment. For long segments (15+ minutes), prioritize the creator's main point — the Key Points section handles depth."

---

### 1.7 No Guidance for Very Long Transcripts

A 4-hour conference talk can produce 50,000+ words. SKILL.md says "do not sample or stop early" (line 57) but provides no strategy for when the transcript exceeds the LLM's context window. The 010 doc (§3.2 S6) identifies this as a significant gap.

**Recommendation:** Add after line 57: "For very long videos (3+ hours), if the full transcript exceeds your context window after reading all batches, focus your analysis on the portions you were able to read. Note in the SUMMARY that the analysis covers the first N hours. Never fabricate content for portions you could not read."

---

### 1.8 Tags Guidance Lacks Concrete Examples

**Line 121.** Rules are stated abstractly ("prefer broader terms," "avoid overlap"). The single Bad/Good example covers only one pattern (narrowing). Different video genres produce very different tag challenges.

**Recommendation:** Add examples by video type:
- Tech review: `["hardware", "laptops", "apple"]` not `["m4 macbook pro review"]`
- AI research paper: `["ai", "machine-learning", "research"]` not `["transformer architecture", "attention mechanism"]`
- Economics lecture: `["economics", "policy", "finance"]` not `["monetary policy", "central banking"]`
- Cooking tutorial: `["cooking", "recipes", "italian"]` not `["pasta carbonara"]`

---

### 1.9 No Mention of Template Interactive Features

The template.html implements extensive features the SKILL.md never mentions:
- Two-column resizable layout with draggable divider
- Layout presets (keyboard 1/2/3)
- Timestamp sync (clicking outline entries seeks the player)
- Playback shortcuts (k/Space, j/l, comma/period, c, f)
- Markdown export button
- Dark mode toggle (persists in localStorage)
- Help modal (? key)

SKILL.md says "This is not a design task. Do not read the template file." — correct, but it also means the LLM has zero knowledge of these features. If a user asks "how do I use the report?" or "what shortcuts are available?" the LLM cannot answer.

**Recommendation:** Add a "Report Features" section before the final line listing the key interactive features. Not design instructions — just awareness for user Q&A.

---

## 2. video-lens-gallery SKILL.md (59 lines)

### 2.1 Severely Underspecified

At 59 lines vs 259 for video-lens, the gallery SKILL.md is a minimal script runner. It tells the LLM *what commands to run* but not *what they do*, *what can go wrong*, or *what the user gets*.

### 2.2 No Error Handling

Zero guidance on failures:
- What if `~/Downloads/video-lens` doesn't exist? (Step 3 checks this, but other steps don't)
- What if `build_index.py` crashes?
- What if `backfill_meta.py` fails on specific files?
- What if port 8765 is already in use?

**Recommendation:** Add an Error Handling section covering these cases.

### 2.3 Backfill Trigger Condition Too Narrow

**Line 35.** "If the user's request mentions 'backfill'." Users might say "update metadata," "fix old reports," "add missing data," or "enrich reports" — none of which trigger backfill.

**Recommendation:** Expand to: "mentions 'backfill', 'update metadata', 'fix old reports', 'add missing data', or 'enrich reports'."

### 2.4 No Explanation of What build_index.py Does

Step 3 says: run the command, tell user the count. The LLM has no understanding of what happened — manifest.json, inlined index.html, metadata extraction. If the user asks "what did that do?" the LLM can only say "it indexed your reports."

**Recommendation:** Expand Step 3 to explain: scans reports/ for HTML files with `<script id="video-lens-meta">` blocks, extracts metadata, writes manifest.json + patched index.html with inlined manifest.

### 2.5 No Gallery Feature Awareness

index.html has search, tag filtering, channel filtering, sortable columns, cards/list views, dark mode, keyboard shortcuts. SKILL.md mentions none of these.

**Recommendation:** Add a "Gallery Features" section listing the key capabilities.

### 2.6 Missing Read Tool

**Line 11.** `allowed-tools: Bash`. If script output is truncated, the LLM can't use Read to see the full output. Should be `Bash Read`.

### 2.7 Cross-Skill Dependency Not Documented

Step 4 uses `serve_report.sh` from the video-lens skill (via `$_sd`). This dependency is invisible — if video-lens skill isn't installed, Step 4 fails with a cryptic error.

**Recommendation:** Add note explaining the dependency and what `$_sd` points to.

---

## 3. backfill_meta.py Script Bug

### 3.1 Scans Wrong Directory

**File:** `skills/video-lens-gallery/scripts/backfill_meta.py` line 179

`scan_dir.glob("*video-lens*.html")` scans the root of `~/Downloads/video-lens/` only. Since video-lens v2.0, all reports are saved to `~/Downloads/video-lens/reports/`. The backfill script misses every report created under the current version.

Meanwhile, `build_index.py` correctly scans both root and `reports/` (lines 99-127).

**Fix:** Change to scan `reports/` subdirectory only. The root-level flat layout is legacy and no longer the save target.

---

## 4. Cross-Reference with 010 Optimization Report

The 010 doc identifies six quick wins. This audit's scope overlaps with:

| 010 Quick Win | This Audit | Status |
|---|---|---|
| QW1 — Shorts support | Not in scope | Deferred |
| QW2 — Caption type detection | Not in scope | Deferred |
| QW3 — Proxy support | Not in scope | Deferred |
| QW4 — Structured error codes | Not in scope | Deferred |
| QW5 — Duplicate detection | Not in scope | Deferred |
| QW6 — Script discovery consolidation | Partially addressed (gallery SKILL.md 3.12) | Partial |

The 010 doc also validates several findings in this audit:
- §2.4 on string-prefix errors supports the observation that error handling is fragile
- §2.5 on language support confirms the "not a translation feature" design is intentional
- §3.2 S2 on brittle script discovery aligns with the repeated 8-agent loop observation
- §3.2 S6 on long transcripts matches finding 1.7

---

## 5. Summary of Changes

| ID | File | Change | Category |
|---|---|---|---|
| 1.2 | `backfill_meta.py` | Scan reports/ only | Bug fix |
| 2.1 | `video-lens/SKILL.md` | Step 2/2b ordering guidance | Ambiguity |
| 2.2 | `video-lens/SKILL.md` | Escaping rules block | Ambiguity |
| 2.3 | `video-lens/SKILL.md` | Summary truncation precision | Ambiguity |
| 2.4 | `video-lens/SKILL.md` | Filename field note | Ambiguity |
| 2.5 | `video-lens/SKILL.md` | Outline detail scope | Ambiguity |
| 3.4 | `video-lens/SKILL.md` | Very long transcript guidance | Gap |
| 3.5 | `video-lens/SKILL.md` | Tags examples | Gap |
| 3.6 | `video-lens/SKILL.md` | Report feature awareness | Gap |
| 3.7 | `gallery/SKILL.md` | Error handling section | Gap |
| 3.8 | `gallery/SKILL.md` | Backfill trigger expansion | Gap |
| 3.9 | `gallery/SKILL.md` | Gallery feature awareness | Gap |
| 3.10 | `gallery/SKILL.md` | build_index.py explanation | Gap |
| 3.11 | `gallery/SKILL.md` | Add Read to allowed-tools | Gap |
| 3.12 | `gallery/SKILL.md` | Cross-skill dependency note | Gap |
