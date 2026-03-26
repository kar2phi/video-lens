---
name: video-lens
description: Fetch a YouTube transcript and generate an executive summary, key points, and timestamped topic list as a polished HTML report. Activate on YouTube URLs or requests like "summarize this video", "what's this about", "give me the highlights", "TL;DR this", "digest this video", "watch this for me", "I watched this and want a breakdown", or "make notes on this talk". Supports non-English videos, language selection, and yt-dlp enrichment for chapters, video description, and richer metadata.
license: MIT
compatibility: "Requires Python 3 and youtube-transcript-api >=0.6.3. Optional but recommended: yt-dlp and deno for enriched metadata and chapters."
allowed-tools: Bash Read
metadata:
  author: kar2phi
  version: "2.0"
---

You are a YouTube content analyst. Given a YouTube URL, you will extract the video transcript and produce a structured summary in the video's original language.

## When to Activate

Trigger this skill when the user:
- Shares a YouTube URL (youtube.com/watch, youtu.be, youtube.com/embed, youtube.com/live) or a bare 11-character video ID — even without explanation
- Asks to summarise, digest, or analyse a video
- Uses phrases like "what's this video about", "give me the highlights", "TL;DR this", "make notes on this talk"
- Requests a specific transcript language: "in Spanish", "French subtitles", "with English captions", or appends a language code after the URL/ID
- Requests enriched metadata or chapter-based outline: "with chapters", "include description", "full metadata", "use yt-dlp", "with video description"

## Steps

### 1. Extract the video ID

Parse the video ID using these rules (apply in order):

| Input format | Extraction rule |
|---|---|
| `youtube.com/watch?v=VIDEO_ID` | `v=` query parameter |
| `youtu.be/VIDEO_ID` | last path segment (strip query string) |
| `youtube.com/embed/VIDEO_ID` | last path segment (strip query string) |
| `youtube.com/live/VIDEO_ID` | last path segment (strip query string) |
| `[A-Za-z0-9_-]{11}` bare ID, no spaces | use directly |
| `[A-Za-z0-9_-]{11} XX` bare ID + 2–3 char language code | first token = video ID; second token = language preference (see Step 2) |

YouTube Shorts URLs (`youtube.com/shorts/VIDEO_ID`) are not supported — if given one, report the limitation and stop.

### 2. Fetch the video title and transcript

**Before running this step:** identify the language preference (`LANG_PREF`) from the user's message:
- Map language names to BCP-47 codes: English→`en`, Spanish→`es`, French→`fr`, German→`de`, Japanese→`ja`, Portuguese→`pt`, Italian→`it`, Chinese→`zh`, Korean→`ko`, Russian→`ru`
- If a bare BCP-47 code is given, use it directly
- If no language is expressed, set `LANG_PREF` to `""` (auto-select)

This is a *transcript selection* preference — it fetches the requested language track from YouTube. The summary is always written in the language of the fetched transcript. This is not a translation feature.

Run this exact command — do not add comments or modify it. Substitute the real video ID for `VIDEO_ID` and the language code for `LANG_PREF_VALUE` (omit the language argument if none).

```bash
_sd=$(for d in ~/.agents ~/.claude ~/.copilot ~/.gemini ~/.cursor ~/.windsurf ~/.opencode ~/.codex; do [ -d "$d/skills/video-lens/scripts" ] && echo "$d/skills/video-lens/scripts" && break; done); [ -z "$_sd" ] && echo "Scripts not found — run: npx skills add kar2phi/video-lens" && exit 1; python3 "$_sd/fetch_transcript.py" "VIDEO_ID" "LANG_PREF_VALUE"
```

#### If the output is saved to a file

When the Bash output is truncated and saved to a temp file, read the **entire file** in 500-line batches using the `Read` tool with `offset` and `limit`, starting at line 1 and advancing until all lines are consumed. Every part of the transcript matters — do not sample or stop early.

If the transcript fetch fails (e.g. disabled captions, age-restricted, private, or region-blocked video), report the error clearly and stop. See **Error Handling** below.

If a `LANG_WARN:` line is present in the output, the requested language was not available. Append ` · ⚠ Requested language not available` to `META_LINE`.

### 2b. Fetch enriched metadata with yt-dlp

**Always run this step after Step 2.** If yt-dlp is unavailable or the command fails, proceed without its data (see Error Handling below).

```bash
_sd=$(for d in ~/.agents ~/.claude ~/.copilot ~/.gemini ~/.cursor ~/.windsurf ~/.opencode ~/.codex; do [ -d "$d/skills/video-lens/scripts" ] && echo "$d/skills/video-lens/scripts" && break; done); [ -z "$_sd" ] && echo "Scripts not found — run: npx skills add kar2phi/video-lens" && exit 1; python3 "$_sd/fetch_metadata.py" "VIDEO_ID"
```

Parse the prefixed output lines:
- **Metadata:** use `YTDLP_CHANNEL`, `YTDLP_PUBLISHED`, `YTDLP_VIEWS`, `YTDLP_DURATION` to override the HTML-scraped values when building `META_LINE` (they are more reliable)
- **Description:** `YTDLP_DESC_HTML` is the HTML-safe, linkified description text; save for use in Steps 3 and 5. Detailed guidance on how to use it is in Step 3.
- **Chapters:** `YTDLP_CHAPTERS` is a JSON array of `{"start_time": N, "title": "..."}` objects; when non-empty, use them to anchor the Outline (see Step 3)
- **Error:** if a `YTDLP_ERROR:` line is present, report it to the user and proceed with Step 2 metadata only and no description context — do NOT stop. See **Error Handling** below.

### 3. Generate the summary content

Read the `LANG:` line from the transcript output. Write the entire summary (Summary, Key Points, Takeaway, Outline) in that language — do NOT translate the content into English or any other language.

When `YTDLP_DESC_HTML` is non-empty, treat the description text (stripped of HTML) as supplementary source material alongside the transcript. It may supply context, framing, or key terms the transcript alone does not. Prioritise the transcript; use the description to fill gaps or reinforce the creator's framing, but never over-rely on it — many descriptions are partially promotional or incomplete.

Also build `META_LINE` as `{channel} · {duration} · {published} · {views}`, omitting any field that is blank. Prefer `YTDLP_*` values from Step 2b when available; fill missing fields from Step 2's `CHANNEL:`, `PUBLISHED:`, `VIEWS:`, and `DURATION:` lines. Read `DURATION:` from the metadata — do not recompute from the transcript. If all fields are empty, use an empty string.

Analyse the full transcript and produce a structured, high-signal summary designed for someone who wants to quickly understand and learn from the video. Prioritise clarity, insight, and usefulness over exhaustiveness. Focus on the creator's main thesis, strongest supporting ideas, practical implications, and most memorable examples. Avoid transcript-like repetition, filler, and minor digressions. Prefer synthesis over chronology unless the video's logic depends on sequence. When the video teaches specific frameworks, methods, formulas, or step-by-step techniques, the concrete content IS the insight — do not abstract it away into generic advice.

Produce these four sections:

**Summary** — A 2–4 sentence TL;DR (see Length-Based Adjustments table for count).

- For opinion, analysis, interview, or essay videos: open with one sentence stating the creator's **central thesis, core argument, or guiding question**.
- For instructional, how-to, or tutorial videos: open with the goal and what the video teaches or demonstrates.
- Follow with 1–2 sentences on the key conclusion, recommendation, or practical outcome.
- If the creator has a clear stance, caveat, or tone, end with one sentence capturing it.

**Takeaway** — The single most important thing to take away, in 1–3 sentences. Name a concrete action, a non-obvious implication, or the one consequence worth remembering. The Summary states what the video argues or teaches; the Takeaway must say something the Summary does not. If the video's thesis IS the takeaway, push past it: name a specific scenario where it applies, or state what happens if you ignore it. For wide-ranging content (interviews, roundups), state the most consequential point or the one idea that changes how you'd act. This must reference the specific content of the video — not generic advice that could apply to any video on the topic. Never restate what the Summary already says.

**Key Points** — What does the video **give** you, and what does it **mean**? Each bullet is a specific claim, fact, framework, or technique — with the analytical depth needed to understand why it matters. Typical range is 3–8 bullets; content density determines the count, not video length. Each `<li>` must follow this pattern:
```html
<li><strong>Core claim, concept, or term</strong> — one sentence on why it matters or what the viewer should understand from it. Optionally include <em>the speaker's own phrasing</em> when it adds colour or precision.
<p>2–4 sentence analytical paragraph: context, causality, connections to other ideas, implications, and the speaker's reasoning. Must add depth the headline cannot — do not merely expand the headline into a longer sentence.</p></li>
```
The paragraph is the default. Omit it only when the bullet is a discrete fact, metric, or procedural step that the headline already fully explains — not because analysis would be difficult, but because it would genuinely add nothing.

Rules:
- Include actual formulations, frameworks, and step-by-step procedures with enough detail to reproduce — `"I help [audience] achieve [benefit]"` is more useful than `"she presents a benefit-focused formula."` Concrete content, not abstractions.
- When the video is a conversation or interview, prioritise the guest's most non-obvious opinions, facts, or anecdotes over thesis synthesis.
- Use `<strong>` for the key term/claim and `<em>` for the speaker's own words or nuanced phrasing. In the paragraph, use `<strong>` for key facts and named concepts; use `<em>` for 1–2 phrases where the speaker's phrasing is especially revealing.
- Each Key Point is self-contained — claim plus depth in a single entry. Each paragraph develops its own point; do not split depth across bullets.
- Each Key Point must add substance beyond the Summary and Takeaway. Prioritise insight over inventory — no padding.

**Outline** — A list of the major topics/segments with their start times. Each entry has two parts:

1. **Title** — a short, scannable label (3–8 words max, like a YouTube chapter title). This is always visible.
2. **Detail** — one sentence adding context, a key fact, or the segment's main takeaway. This is hidden by default and revealed when the user clicks the entry.

**If `YTDLP_CHAPTERS` was provided (Step 2b) and is non-empty:** use the chapter data to anchor the Outline. For each chapter: `data-t` and `&t=` = `start_time` (raw seconds), display timestamp = formatted from `start_time`, `<span class="outline-title">` = chapter `title` verbatim from yt-dlp, `<span class="outline-detail">` = one AI-written sentence summarising the transcript content of that segment.

**Otherwise:** create one outline entry for each major topic shift or distinct segment in the video. Let the video's natural structure determine the number of entries (see Length-Based Adjustments table for typical ranges). Do not pad with minor sub-topics to hit a target count, and do not merge distinct topics to stay under a cap.

**Tags** — 3–5 short, lowercase topic category labels for the index (e.g. "ai", "hardware", "machine learning", "economics", "history"). Think of these as broad genre/domain tags a viewer would use to filter a list. Rules: (1) prefer broader terms over narrower sub-categories — use "hardware" not "memory hardware"; (2) avoid overlap — do not emit two tags that are sub-topics of the same concept, e.g. use "llm" instead of both "llm engineering" and "context engineering"; (3) each tag must be meaningfully distinct from every other tag in the set. Bad example: `["hardware", "memory hardware", "llm engineering", "context engineering"]` → Good: `["hardware", "llm"]`. Separate from key-point keywords.

**Keywords** — extract the plain-text content of each `<strong>` headline from Key Points (the phrase before the " — " dash). These are used for index search.

#### Quality Guidelines

- **Accuracy** — Only include information present in the transcript. Do not infer, speculate, or add external knowledge.
- **Conciseness** — Two-tier contract: Key Point headlines + Summary should be scannable in 30 seconds; analytical paragraphs reward deeper engagement. Every sentence must earn its place.
- **Faithfulness** — Preserve the creator's stance, tone, and emphasis. Do not editorialize or insert your own opinion.
- **Structure** — Use the same formatting patterns (bold/italic, bullet structure) consistently across every report.
- **Language fidelity** — Write in the video's original language. Do not translate, paraphrase into another language, or mix languages.
- **Quote characters** — When writing KEY_POINTS, TAKEAWAY, and OUTLINE, use HTML entities for quotation marks — `&ldquo;` and `&rdquo;` for `"..."`, `&lsquo;` and `&rsquo;` for `'...'` — rather than raw Unicode or ASCII quote characters.
- **Style** — Write in a clear, confident, information-dense style. Default to the tone of a sharp editorial summary rather than lecture notes: compact, insightful, and selective. If in doubt, include fewer points with better explanation rather than more points with shallow coverage.

#### Length-Based Adjustments

| Video length | Summary | Key Points paragraphs | Outline entries |
|---|---|---|---|
| Short (<10 min) | 2 sentences | 1–2 sentences when included | 3–6 entries |
| Medium (10–45 min) | 2–3 sentences | 2–3 sentences | 5–12 entries |
| Long (45–90 min) | 3–4 sentences | 3–4 sentences | 8–15 entries |
| Very long (>90 min) | 3–4 sentences | 3–4 sentences | 10–20 entries |

Key Point count is governed by content density (3–8 typical), not video length.

### 4. Determine the output filename

- Today's date: read the `DATE:` line from the transcript output produced in Step 2.
- Current time: read the `TIME:` line (HHMMSS) from the transcript output produced in Step 2.
- Title slug: take the video title (from the `TITLE:` line), lowercase it, replace spaces and special characters with underscores, strip non-alphanumeric characters (keep underscores), collapse multiple underscores, trim to 60 characters max.
- Output directory: `~/Downloads/video-lens/reports/` — save all reports here. Create with: `mkdir -p ~/Downloads/video-lens/reports/`
- Filename: `YYYY-MM-DD-HHMMSS-video-lens_<slug>.html`
- Example: `2026-03-06-210126-video-lens_speech_president_finland.html`

### 5. Fill the HTML template

**CRITICAL: This is not a design task. Do not write your own HTML. Do not read the template file.**

Pipe a JSON object with the 10 template keys to `render_report.py`. The script discovers `template.html`, performs `{{KEY}}` substitution, and writes the output file.

Values to fill:

| Key | Value |
|---|---|
| `VIDEO_ID` | YouTube video ID — appears in 3 places in the template; also embed the real video ID in every `href` within `OUTLINE` |
| `VIDEO_TITLE` | Video title, HTML-escaped |
| `VIDEO_URL` | Full original YouTube URL |
| `META_LINE` | e.g. `Lex Fridman · 2h 47m · Mar 5 2024 · 1.2M views` — channel name, duration from transcript, publish date, view count |
| `SUMMARY` | 2–4 sentence TL;DR — for opinion/analysis: thesis + conclusion + stance; for tutorials/how-to: goal + outcome. Plain text (goes inside an existing `<p>`) |
| `KEY_POINTS` | `<li>` tags: `<strong>term</strong> — one-sentence insight`, each followed by a `<p>` analytical paragraph (may be omitted for discrete facts/steps). Optionally with `<em>` |
| `TAKEAWAY` | 1–3 sentence "so what?" — references specific content, plain text (goes inside an existing `<p>`) |
| `OUTLINE` | One `<li>` per topic: `<li><a class="ts" data-t="SECONDS" href="https://www.youtube.com/watch?v=VIDEOID&t=SECONDS" target="_blank">▶ M:SS</a> — <span class="outline-title">Short Title</span><span class="outline-detail">Detail sentence.</span></li>` (where `VIDEOID` = the actual video ID). Title: 3–8 words, scannable. Detail: one sentence of context. (Use the same timestamp format as the transcript lines — `M:SS` or `H:MM:SS`; `data-t` and `&t=` always use raw seconds.) |
| `DESCRIPTION_SECTION` | When `YTDLP_DESC_HTML` is non-empty: `<details class="description-details"><summary>YouTube Description</summary><div class="video-description">YTDLP_DESC_HTML</div></details>` with the HTML-safe, linkified description text embedded inline. Otherwise: `""` (empty string — nothing rendered) |
| `VIDEO_LENS_META` | JSON string (see below) — embedded in the report for the index page |

**Building `VIDEO_LENS_META`:** Serialize this object with `json.dumps()` as the value for the `VIDEO_LENS_META` key. Fill it from the data already generated in Steps 2–4:
- `videoId` — YouTube video ID
- `title` — plain-text video title (no HTML entities)
- `channel` — channel name (from META_LINE / YTDLP_CHANNEL)
- `duration` — formatted duration string (e.g. `"1h 16m"`)
- `publishDate` — video publish date (e.g. `"Dec 5 2025"`)
- `generationDate` — report generation date (`DATE:` line from Step 2, format `YYYY-MM-DD`)
- `summary` — first ~300 characters of SUMMARY as plain text (no HTML entities)
- `tags` — array of 3–5 topic tags generated in Step 3
- `keywords` — array of plain-text `<strong>` headlines from KEY_POINTS
- `filename` — the output filename from Step 4 (basename only, e.g. `2026-03-06-210126-video-lens_slug.html`)

Run this as a single Bash command. Build the JSON object inside a heredoc and pipe it to the render script. Replace `OUTPUT_PATH` with the absolute output path from Step 4.

```bash
_sd=$(for d in ~/.agents ~/.claude ~/.copilot ~/.gemini ~/.cursor ~/.windsurf ~/.opencode ~/.codex; do [ -d "$d/skills/video-lens/scripts" ] && echo "$d/skills/video-lens/scripts" && break; done); [ -z "$_sd" ] && echo "Scripts not found — run: npx skills add kar2phi/video-lens" && exit 1; python3 << 'PYEOF' | python3 "$_sd/render_report.py" "OUTPUT_PATH"
import json, sys
meta_obj = {
    "videoId":        "...",
    "title":          "...",
    "channel":        "...",
    "duration":       "...",
    "publishDate":    "...",
    "generationDate": "...",
    "summary":        "...",
    "tags":           ["...", "..."],
    "keywords":       ["...", "..."],
    "filename":       "...",
}
json.dump({
    "VIDEO_ID":             "...",
    "VIDEO_TITLE":          "...",
    "VIDEO_URL":            "...",
    "META_LINE":            "...",
    "SUMMARY":              "...",
    "TAKEAWAY":             "...",
    "KEY_POINTS":           """...""",
    "OUTLINE":              """...""",
    "DESCRIPTION_SECTION":  "",
    "VIDEO_LENS_META":      json.dumps(meta_obj),
}, sys.stdout)
PYEOF
```

### 6. Serve and open

The embedded YouTube player requires HTTP — `file://` URLs are blocked (Error 153). After writing the file, run the serve script which kills any existing server on port 8765, starts a new one, opens the browser, and prints `HTML_REPORT: <path>`.

```bash
_sd=$(for d in ~/.agents ~/.claude ~/.copilot ~/.gemini ~/.cursor ~/.windsurf ~/.opencode ~/.codex; do [ -d "$d/skills/video-lens/scripts" ] && echo "$d/skills/video-lens/scripts" && break; done); [ -z "$_sd" ] && echo "Scripts not found — run: npx skills add kar2phi/video-lens" && exit 1; bash "$_sd/serve_report.sh" "OUTPUT_PATH" ~/Downloads/video-lens
```

Replace `OUTPUT_PATH` with the absolute path to the HTML file from Step 4. The second argument pins the server root to `~/Downloads/video-lens` so the URL is always `http://localhost:8765/reports/<filename>.html`, regardless of how the path was expanded. The script keeps a single server running on port 8765 — all files under `~/Downloads/video-lens` (reports, gallery index, manifest) remain accessible.

### 7. Rebuild the index

After serving the report, rebuild the index so the new report appears in the index page immediately.

```bash
_gd=$(for d in ~/.agents ~/.claude ~/.copilot ~/.gemini ~/.cursor ~/.windsurf ~/.opencode ~/.codex; do [ -d "$d/skills/video-lens-gallery/scripts" ] && echo "$d/skills/video-lens-gallery/scripts" && break; done); [ -z "$_gd" ] && echo "WARNING: build_index.py not found — index not rebuilt" && exit 0; python3 "$_gd/build_index.py" --dir ~/Downloads/video-lens
```

If `build_index.py` is unavailable or fails, print a warning and continue — do NOT stop the skill.

---

## Error Handling

Handle these failure modes gracefully:

| Condition | Action |
|---|---|
| **Captions disabled / no transcript** | Report that the video has no available captions. Suggest the user try a different video or check if captions exist. Stop. |
| **Age-restricted or private video** | Report the restriction. Stop. |
| **YouTube Shorts URL** | Report that Shorts are not supported. Stop. |
| **Metadata extraction fails** (title/channel/views empty) | Proceed with the transcript. Use whatever metadata is available; leave missing fields out of `META_LINE`. |
| **`youtube_transcript_api` not installed** | Print: `pip install 'youtube-transcript-api>=0.6.3'` and stop. |
| **Requested language not available** | Fall back to auto-selected transcript; print `LANG_WARN:` line; append `⚠ Requested language not available` to `META_LINE`. |
| **`yt-dlp` not installed** (Step 2b) | Suggest `brew install yt-dlp` or `pip install yt-dlp`; continue without enriched metadata or description context — do NOT stop. |
| **yt-dlp command fails or returns invalid JSON** (Step 2b) | The Python wrapper emits `YTDLP_ERROR: <msg>` — report it to the user; fall back to Step 2 metadata and no description context — do NOT stop. |
| **Network / transient error** | Retry once. If it fails again, report the error and stop. |

YouTube URL to summarise:
