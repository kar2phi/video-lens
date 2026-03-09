---
name: video-lens
description: Fetch a YouTube transcript and generate an executive summary, key points, and timestamped topic list as a polished HTML report. Activate on YouTube URLs or requests like "summarize this video", "what's this about", "give me the highlights", "TL;DR this", "digest this video", "watch this for me", "I watched this and want a breakdown", or "make notes on this talk". Supports non-English videos.
---

You are a YouTube content analyst. Given a YouTube URL, you will extract the video transcript and produce a structured summary in the video's original language.

## When to Activate

Trigger this skill when the user:
- Shares a YouTube URL (youtube.com/watch, youtu.be) — even without explanation
- Asks to summarise, digest, or analyse a video
- Uses phrases like "what's this video about", "give me the highlights", "TL;DR this", "make notes on this talk"

## Steps

### 1. Extract the video ID

Parse the video ID from the URL (the `v=` parameter or the last path segment for youtu.be links).

YouTube Shorts URLs (`youtube.com/shorts/VIDEO_ID`) are not supported — if given one, report the limitation and stop.

### 2. Fetch the video title and transcript

Run this exact Bash command verbatim — do not rewrite it as a file, do not add `#` comment lines, do not paraphrase it (substitute the real video ID for `VIDEO_ID`). Requires `youtube_transcript_api` version ≥0.6.3 (`pip install 'youtube-transcript-api>=0.6.3'`).

```bash
python3 -c "
import re, urllib.request, datetime
from youtube_transcript_api import YouTubeTranscriptApi
video_id = 'VIDEO_ID'
try:
    req = urllib.request.Request(f'https://www.youtube.com/watch?v={video_id}', headers={'User-Agent': 'Mozilla/5.0'})
    html = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
    m = re.search(r'<title>([^<]+)</title>', html)
    title = m.group(1).replace(' - YouTube', '').strip() if m else ''
    channel = ''
    published = ''
    views = ''
    m_ch = re.search(r'\"channelName\"\s*:\s*\"([^\"]+)\"', html)
    if m_ch: channel = m_ch.group(1)
    m_pub = re.search(r'\"publishDate\"\s*:\s*\"([^\"]+)\"', html)
    if m_pub:
        parts = m_pub.group(1)[:10].split('-')
        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        published = f'{months[int(parts[1])-1]} {int(parts[2])} {parts[0]}'
    m_views = re.search(r'\"viewCount\"\s*:\s*\"([0-9]+)\"', html)
    if m_views:
        v = int(m_views.group(1))
        views = f'{v/1e6:.1f}M views' if v >= 1e6 else f'{v/1e3:.0f}K views' if v >= 1e3 else f'{v} views'
    m_dur = re.search(r'\"lengthSeconds\"\s*:\s*\"([0-9]+)\"', html)
    if m_dur:
        total_s = int(m_dur.group(1))
        h2, rem = divmod(total_s, 3600); m2 = rem // 60
        duration = f'{h2}h {m2}m' if h2 > 0 else f'{m2} min'
    else:
        duration = ''
except Exception:
    title = ''
    channel = ''
    published = ''
    views = ''
    duration = ''
try:
    try:
        tlist = YouTubeTranscriptApi().list(video_id)
    except (AttributeError, TypeError):
        tlist = YouTubeTranscriptApi.list_transcripts(video_id)
except Exception as e:
    raise SystemExit(f'Transcript fetch failed: {e}')
transcript_obj = None
for t in tlist:
    if not getattr(t, 'is_translation', False):
        transcript_obj = t
        break
if transcript_obj is None:
    transcript_obj = next(iter(tlist))
transcript = transcript_obj.fetch()
lang = transcript_obj.language_code
lines = [f'TITLE: {title}', f'CHANNEL: {channel}', f'PUBLISHED: {published}', f'VIEWS: {views}', f'DURATION: {duration}', f'DATE: {datetime.date.today().isoformat()}', f'TIME: {datetime.datetime.now().strftime(\"%H%M%S\")}', f'LANG: {lang}']
for s in transcript:
    total_s = int(s.start)
    h3, rem3 = divmod(total_s, 3600)
    m2, s2 = divmod(rem3, 60)
    if h3 > 0:
        lines.append(f'[{h3}:{m2:02d}:{s2:02d}] {s.text}')
    else:
        lines.append(f'[{m2}:{s2:02d}] {s.text}')
print('\n'.join(lines))
"
```

Run this command verbatim.

#### If the output is saved to a file

When the Bash output is truncated and saved to a temp file, read the **entire file** sequentially — do not sample or stop early.

1. **Check the line count** — run `wc -l /path/to/file` (or read it from the truncation notice).
2. **Read in 500-line batches** using the `Read` tool with `offset` and `limit`, starting at line 1 and advancing until all lines are consumed:
   - offset=0, limit=500
   - offset=500, limit=500
   - offset=1000, limit=500
   - … continue until fewer than 500 lines are returned — that signals the end of the file.

Every part of the transcript matters for an accurate summary. Do not skip sections regardless of video length.

If the transcript fetch fails (e.g. disabled captions, age-restricted, private, or region-blocked video), report the error clearly and stop. See **Error Handling** below.

### 3. Generate the summary content

Read the `LANG:` line from the transcript output. Write the entire summary (Summary, Analysis, Key Points, Takeaway, Outline) in that language — do NOT translate the content into English or any other language.

Also read `CHANNEL:`, `PUBLISHED:`, `VIEWS:`, and `DURATION:` from the command output. Read `DURATION:` from the metadata — do not recompute from the transcript. Build `META_LINE` as `{channel} · {duration} · {published} · {views}`, omitting any field that is blank. If all metadata fields are empty (YouTube page scraping failed), set `META_LINE` to an empty string and proceed — the summary can still be generated from the transcript alone.

Analyse the full transcript and produce:

**Summary** — For opinion, analysis, interview, or essay videos: open with one sentence stating the creator's **central thesis or core question**. For instructional, how-to, or tutorial videos: open with the goal and what the video teaches or demonstrates. Follow with 1–2 sentences of the key conclusion or outcome. If the video expresses a clear stance, recommendation, or caveat, end with one sentence characterising the creator's position or tone. Total: 2–4 sentences. This is the TL;DR.

**Analysis** — 2–4 paragraphs covering the main argument or narrative arc, supporting detail, and key takeaways (see Length-Based Adjustments table for paragraph count). Open each paragraph with a topic sentence in `<strong>`. Use `<strong>` for key facts, named concepts, and core claims; use `<em>` for 1–2 phrases per paragraph where the author's phrasing matters (quotes, hedged claims, rhetorical emphasis).

**Key Points** — Concise bullet points (see Length-Based Adjustments table for count). Each `<li>` must follow this pattern:
```html
<li><strong>Core claim or term</strong> — explain the significance or implication, not just the surface fact. Optionally include <em>speaker's own phrasing</em> when it adds colour. If there is a distinct practical consequence, add it as a natural follow-on sentence.</li>
```
Use `<strong>` for the key term/claim and `<em>` for speaker's own words or nuanced phrasing. Each bullet's text after the dash must add insight beyond what the bold heading already says — do not restate the heading in different words. Keep the list focused — no padding.

**Takeaway** — 1–2 sentences: the single most important insight or conclusion a viewer should carry away. For practical content, frame it as a call to action; for informational or analytical content, frame it as the key thing to remember. This is not a repeat of the Summary — it distils the "so what?"

**Outline** — A list of the major topics/segments with their start times. Each entry has two parts:

1. **Title** — a short, scannable label (3–8 words max, like a YouTube chapter title). This is always visible.
2. **Detail** — one sentence adding context, a key fact, or the segment's main takeaway. This is hidden by default and revealed when the user clicks the entry.

Create one outline entry for each major topic shift or distinct segment in the video. Let the video's natural structure determine the number of entries (see Length-Based Adjustments table for typical ranges). Do not pad with minor sub-topics to hit a target count, and do not merge distinct topics to stay under a cap.

For videos longer than 60 minutes, use `H:MM:SS` as the display label (e.g. `▶ 1:23:45`); `data-t` and `&t=` always use raw seconds.

**Quote characters:** When writing ANALYSIS, KEY_POINTS, TAKEAWAY, and OUTLINE, use HTML entities for quotation marks — `&ldquo;` and `&rdquo;` for `"..."`, `&lsquo;` and `&rsquo;` for `'...'` — rather than raw Unicode or ASCII quote characters.

#### Quality Guidelines

- **Accuracy** — Only include information present in the transcript. Do not infer, speculate, or add external knowledge.
- **Conciseness** — The Summary + Key Points should be scannable in 30 seconds. Every sentence must earn its place.
- **Faithfulness** — Preserve the creator's stance, tone, and emphasis. Do not editorialize or insert your own opinion.
- **Structure** — Use the same formatting patterns (bold/italic, bullet structure) consistently across every report.
- **Language fidelity** — Write in the video's original language. Do not translate, paraphrase into another language, or mix languages.

#### Length-Based Adjustments

| Video length | Summary | Analysis | Key Points | Outline entries |
|---|---|---|---|---|
| Short (<10 min) | 2 sentences | 1–2 paragraphs | 3–5 bullets | 3–6 entries |
| Medium (10–45 min) | 2–3 sentences | 2–3 paragraphs | 5–7 bullets | 5–12 entries |
| Long (45–90 min) | 3–4 sentences | 3–4 paragraphs | 5–7 bullets | 8–15 entries |
| Very long (>90 min) | 3–4 sentences | 4 paragraphs | 6–7 bullets | 10–20 entries |

## Error Handling

Handle these failure modes gracefully:

| Condition | Action |
|---|---|
| **Captions disabled / no transcript** | Report that the video has no available captions. Suggest the user try a different video or check if captions exist. Stop. |
| **Age-restricted or private video** | Report the restriction. Stop. |
| **YouTube Shorts URL** | Report that Shorts are not supported. Stop. |
| **Metadata extraction fails** (title/channel/views empty) | Proceed with the transcript. Use whatever metadata is available; leave missing fields out of `META_LINE`. |
| **`youtube_transcript_api` not installed** | Print: `pip install 'youtube-transcript-api>=0.6.3'` and stop. |
| **Network / transient error** | Retry once. If it fails again, report the error and stop. |

---

### 4. Determine the output filename

- Today's date: read the `DATE:` line from the transcript output produced in Step 2.
- Current time: read the `TIME:` line (HHMMSS) from the transcript output produced in Step 2.
- Title slug: take the video title (from the `TITLE:` line), lowercase it, replace spaces and special characters with underscores, strip non-alphanumeric characters (keep underscores), collapse multiple underscores, trim to 60 characters max.
- Output directory: `~/Downloads/` — save all reports here.
- Filename: `YYYY-MM-DD-HHMMSS-video-lens_<slug>.html`
- Example: `2026-03-06-210126-video-lens_speech_president_finland.html`

### 5. Fill the HTML template

**CRITICAL: This is not a design task. Do not write your own HTML. Do not read the template file.**

Apply the 9 values directly into the HTML template using a Python heredoc. The template never enters your context.

Values to fill:

| Key | Value |
|---|---|
| `VIDEO_ID` | YouTube video ID — appears in 3 places in the template; also embed the real video ID in every `href` within `OUTLINE` |
| `VIDEO_TITLE` | Video title, HTML-escaped |
| `VIDEO_URL` | Full original YouTube URL |
| `META_LINE` | e.g. `Lex Fridman · 2h 47m · Mar 5 2024 · 1.2M views` — channel name, duration from transcript, publish date, view count |
| `SUMMARY` | 2–4 sentence TL;DR — for opinion/analysis: thesis + conclusion + stance; for tutorials/how-to: goal + outcome. Plain text (goes inside an existing `<p>`) |
| `ANALYSIS` | 2–4 `<p>` tags; `<strong>` on key facts/concepts, `<em>` on speaker's own phrasing |
| `KEY_POINTS` | 5–7 `<li>` tags: `<strong>term</strong> — insight/implication`, optionally with `<em>` |
| `TAKEAWAY` | 1–2 sentence actionable conclusion, plain text (goes inside an existing `<p>`) |
| `OUTLINE` | One `<li>` per topic: `<li><a class="ts" data-t="SECONDS" href="https://www.youtube.com/watch?v=VIDEOID&t=SECONDS" target="_blank">▶ M:SS</a> — <span class="outline-title">Short Title</span><span class="outline-detail">Detail sentence.</span></li>` (where `VIDEOID` = the actual video ID). Title: 3–8 words, scannable. Detail: one sentence of context. (For videos > 60 min use `▶ H:MM:SS` as the display label; `data-t` and `&t=` always use raw seconds.) |

Run this as a single Bash command, filling in the real values inline. Use `"..."` strings for single-line values and `"""..."""` triple-quoted strings for multi-line HTML values (ANALYSIS, KEY_POINTS, OUTLINE). Replace `OUTPUT_PATH` with the absolute output path from Step 4.

```bash
python3 << 'PYEOF'
import pathlib

subs = {
    "VIDEO_ID":    "...",
    "VIDEO_TITLE": "...",
    "VIDEO_URL":   "...",
    "META_LINE":   "...",
    "SUMMARY":     "...",
    "ANALYSIS":    """...""",
    "KEY_POINTS":  """...""",
    "TAKEAWAY":    "...",
    "OUTLINE":     """...""",
}

tpl = pathlib.Path("~/.claude/skills/video-lens/template.html").expanduser().read_text()
for k, v in subs.items():
    tpl = tpl.replace("{{" + k + "}}", v)
pathlib.Path("OUTPUT_PATH").write_text(tpl)
PYEOF
```

### 6. Serve and open

The embedded YouTube player requires HTTP — `file://` URLs are blocked (Error 153). After writing the file, start a local server and open the report in the browser:

```bash
lsof -ti:8765 | xargs kill 2>/dev/null; sleep 0.2; python3 -m http.server 8765 --directory /path/to/dir & sleep 1 && (open "http://localhost:8765/filename.html" 2>/dev/null || xdg-open "http://localhost:8765/filename.html" 2>/dev/null || echo "Open http://localhost:8765/filename.html in your browser")
```

Always use port 8765, killing any prior server first. This keeps a single server running across multiple reports — all files in the output directory remain accessible at `http://localhost:8765/`. Use the actual directory and filename.

Then print **only the absolute path** prefixed with `HTML_REPORT:` on its own line:

```
HTML_REPORT: /your/output/dir/2026-01-01-201025-video-lens_youtube_title.html
```

---

YouTube URL to summarise:
