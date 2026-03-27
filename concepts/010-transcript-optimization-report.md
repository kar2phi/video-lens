# YouTube Transcription Landscape & video-lens Optimization Report

## Context

video-lens v2.0 is a self-contained Claude Code skill that fetches YouTube transcripts via `youtube-transcript-api`, enriches metadata via `yt-dlp`, and produces polished HTML reports. Since its last competitive analysis (concepts/003, March 2024), the YouTube transcript MCP ecosystem has exploded — 20+ MCP servers, multiple competing skills, and commercial transcript APIs now exist. This report surveys that landscape, critically audits the current implementation against best-in-class competitors, and proposes a prioritised optimisation plan.

---

## 1. Landscape Overview

### 1.1 YouTube Transcript MCP Servers

The MCP ecosystem for YouTube transcripts has matured rapidly. Servers fall into three tiers based on adoption, robustness, and approach.

#### Tier 1: Production-Ready (400+ stars)

| Server | Stars | Language | Approach | Key Feature |
|--------|-------|----------|----------|-------------|
| [anaisbetts/mcp-youtube](https://github.com/anaisbetts/mcp-youtube) | 507 | JS | yt-dlp delegation | Most robust — leverages yt-dlp's active maintenance against YouTube changes |
| [kimtaeyoon83/mcp-server-youtube-transcript](https://github.com/kimtaeyoon83/mcp-server-youtube-transcript) | 503 | TS | Direct protobuf API | Zero dependencies — rolls own fetcher using YouTube's internal transcript endpoint with Android client spoofing |
| [jkawamoto/mcp-youtube-transcript](https://github.com/jkawamoto/mcp-youtube-transcript) | 351 | Python | youtube-transcript-api | Cursor-based pagination for long transcripts; Docker + PyPI distribution |

**Approach analysis:**

- **anaisbetts** delegates entirely to yt-dlp. Most resilient against YouTube API changes since yt-dlp (153K stars) has a massive community maintaining compatibility. Trade-off: requires yt-dlp binary installed locally.
- **kimtaeyoon83** bypasses all libraries — manually constructs protobuf requests to YouTube's internal "engagement-panel-searchable-transcript-search-panel" endpoint with Android client spoofing. Fastest and zero-dependency, but fragile: hardcoded Android client version needs periodic updates as YouTube blocks old versions. Notable feature: uses chapter markers to filter ad/sponsor segments.
- **jkawamoto** uses the same `youtube-transcript-api` library as video-lens but adds cursor-based pagination (critical for token-limited contexts), three separate tools (`get_transcript`, `get_timed_transcript`, `get_video_info`), and `.mcpb` bundles for drag-and-drop Claude Desktop install.

#### Tier 2: Notable Alternatives (30–160 stars)

| Server | Stars | Approach | Differentiator |
|--------|-------|----------|----------------|
| [egoist/fetch-mcp](https://github.com/egoist/fetch-mcp) | 157 | General URL fetcher + YouTube | Supports stdio, SSE, and streamable HTTP transport |
| [ZeroPointRepo/youtube-skills](https://github.com/ZeroPointRepo/youtube-skills) | 82 | Commercial (TranscriptAPI.com) | 12 skills, handles proxy rotation server-side |
| [ShellyDeng08/youtube-connector-mcp](https://github.com/ShellyDeng08/youtube-connector-mcp) | 72 | YouTube Data API v3 | Full YouTube integration: search, channels, playlists, transcripts |
| [destinyfrancis/openclaw-knowledge-distiller](https://github.com/destinyfrancis/openclaw-knowledge-distiller) | 58 | Qwen3-ASR MLX | Fully local ASR on Apple Silicon; no captions needed |
| [mourad-ghafiri/youtube-mcp-server](https://github.com/mourad-ghafiri/youtube-mcp-server) | 52 | Whisper local | Local transcription fallback; Silero VAD; hardware acceleration (MPS/CUDA) |
| [JangHyuckYun/mcp-youtube-intelligence](https://github.com/JangHyuckYun/mcp-youtube-intelligence) | 41 | yt-dlp + server-side summarization | Server-side processing reduces transcript tokens from 2K–30K down to 200–500; SQLite/PostgreSQL caching; batch support |
| [supadata-ai/mcp](https://github.com/supadata-ai/mcp) | 36 | Commercial API | Multi-platform (YouTube, TikTok, Instagram); exponential backoff retries |
| [format37/youtube_mcp](https://github.com/format37/youtube_mcp) | 30 | OpenAI Whisper API | Cloud ASR; Docker deployment; cookie-based YouTube auth |

#### Tier 3: Niche / Experimental

| Server | Stars | Differentiator |
|--------|-------|----------------|
| [ergut/youtube-transcript-mcp](https://github.com/ergut/youtube-transcript-mcp) | 16 | First REMOTE MCP server — deploys to Cloudflare Workers with KV caching; works on mobile Claude |
| [walksoda/crawl-mcp](https://github.com/walksoda/crawl-mcp) | 30 | Crawl4AI-based; 19 tools including YouTube; batch processing (max 3) |

#### Key Patterns Observed Across MCP Servers

1. **Transport**: stdio dominates for local MCP; SSE/streamable HTTP emerging for remote/cloud deployment
2. **Error handling**: Best-in-class use `McpError` with typed error codes (`ErrorCode.InvalidParams`, `ErrorCode.InternalError`), not string-based error detection
3. **Caching**: Most are stateless (fetch-on-demand); only mcp-youtube-intelligence (SQLite/PostgreSQL) and ergut (Cloudflare KV) implement caching
4. **Tool design**: Split tools (separate transcript/metadata/info endpoints) preferred over monolithic single-tool designs
5. **Pagination**: jkawamoto's cursor-based pagination is the only implementation — most MCP servers dump the full transcript in one response, which can exceed token limits for 2+ hour videos
6. **Annotations**: kimtaeyoon83 uses MCP annotations (`readOnlyHint: true`, `openWorldHint: true`, `outputSchema`) — a best practice that most servers skip

---

### 1.2 Competing Claude Code Skills

| Skill | Stars | Approach | vs. video-lens |
|-------|-------|----------|----------------|
| [michalparkola/tapestry-skills](https://github.com/michalparkola/tapestry-skills) | 302 | yt-dlp + Whisper fallback | Has speech-to-text fallback for captionless videos; "Learn This" meta-skill auto-detects content type |
| [yizhiyanhua-ai/youtube-ai-digest](https://github.com/yizhiyanhua-ai/youtube-ai-digest) | 44 | yt-dlp subtitles | Channel-level batch processing; configurable channel list; structured Markdown with thumbnails |
| [JimmySadek/youtube-fetcher-to-markdown](https://github.com/JimmySadek/youtube-fetcher-to-markdown) | 15 | youtube-transcript-api | Obsidian-ready Markdown + YAML frontmatter; tracks `caption_type: "manual"` vs `"auto"`; duplicate detection |
| [AgriciDaniel/claude-youtube](https://github.com/AgriciDaniel/claude-youtube) | 26 | N/A | YouTube CREATOR tool (14 sub-skills for channel audits, SEO, scripts) — different purpose entirely |
| [Koomook/claude-skill-youtube-kr-subtitle](https://github.com/Koomook/claude-skill-youtube-kr-subtitle) | 21 | Claude + FFmpeg | Context-aware translation pipeline; fixes YouTube's "rolling caption" timing overlaps |

**Takeaway:** tapestry-skills is the closest competitor in scope. Its Whisper fallback and content-type auto-detection are features video-lens lacks. youtube-fetcher-to-markdown's `caption_type` tracking and duplicate detection are simple ideas worth adopting.

---

### 1.3 Transcript Libraries & APIs

#### Python

| Library | Stars | Notes |
|---------|-------|-------|
| [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) | 7164 | Dominant library. `is_generated` flag, translation support, proxy support (Webshare), CLI. Known issue: YouTube blocks cloud provider IPs |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | 153K+ | `--write-subs`, `--write-auto-subs`, `--list-subs`, `--sub-format`, `--sub-langs` (regex). Most robust long-term |

#### JavaScript / TypeScript

| Library | Notes |
|---------|-------|
| youtube-transcript (npm, by Kakulukian) | Zero deps; simple API; uses unofficial YouTube API (can break) |
| youtube-caption-extractor (npm) | Supports both manual and auto-generated; deps: `he`, `striptags` |
| youtube-transcript-api (npm, by 0x6a69616e) | JS port of the Python concept |

#### Commercial

| Service | Notes |
|---------|-------|
| [TranscriptAPI.com](https://transcriptapi.com) | 200K+ transcripts/day; remote MCP server; REST API; handles proxy rotation server-side; free tier (100 credits) |
| [Supadata](https://github.com/supadata-ai/mcp) | Multi-platform (YouTube + TikTok + Instagram); AI-powered structured extraction |

---

## 2. Current Implementation Audit

### 2.1 Architecture Assessment

video-lens uses a **self-contained skill architecture**: no MCP servers, no external services. The pipeline is:

```
YouTube URL → fetch_transcript.py (youtube-transcript-api) → fetch_metadata.py (yt-dlp)
           → LLM analysis → render_report.py (template substitution) → serve_report.sh → build_index.py
```

**Strengths of this approach:**
- Zero infrastructure — works offline (transcript fetching aside), no API keys, no server processes
- Complete ownership of the pipeline — every step is visible and debuggable
- Graceful degradation — yt-dlp optional, each enrichment step independent
- Multi-agent support — 8-agent discovery loop means the same skill works across Claude, Cursor, Windsurf, etc.

**Weaknesses vs. MCP-based approaches:**
- Cannot be composed with other tools (an MCP server can be used by any MCP client)
- No shared caching layer (each skill invocation re-fetches)
- Cannot serve multiple agents simultaneously
- Skill prompt must embed the full orchestration logic (259 lines of SKILL.md) vs. a simple tool call

### 2.2 Transcript Fetching

**Current:** `youtube-transcript-api` via `fetch_transcript.py`, with language preference and fallback logic.

| Dimension | video-lens | Best-in-class |
|-----------|-----------|---------------|
| Library | youtube-transcript-api >=0.6.3 | Same library (jkawamoto), or protobuf direct (kimtaeyoon83), or yt-dlp (anaisbetts) |
| Proxy support | None | youtube-transcript-api supports proxies natively; video-lens doesn't expose it |
| IP blocking resilience | Vulnerable | kimtaeyoon83 uses Android client spoofing; commercial services rotate IPs |
| Caption type detection | Not tracked | youtube-fetcher-to-markdown tracks `is_generated` flag |
| Pagination | Full transcript in one response | jkawamoto provides cursor-based pagination |
| Shorts support | Explicitly blocked | kimtaeyoon83 supports Shorts URLs |
| Caching | None | mcp-youtube-intelligence uses SQLite; mourad-ghafiri uses file cache |
| Fallback for no captions | None — hard stop | tapestry-skills: Whisper; mourad-ghafiri: local Whisper + Silero VAD; openclaw: Qwen3-ASR MLX |

### 2.3 Metadata Pipeline

**Current:** HTML regex scraping (fetch_transcript.py Step 2) + yt-dlp JSON (fetch_metadata.py Step 2b).

**Audit findings:**

1. **HTML scraping is redundant.** fetch_transcript.py scrapes title, channel, publish date, view count, and duration from YouTube's HTML page using regex patterns. Then fetch_metadata.py re-fetches all of these (more reliably) via yt-dlp. SKILL.md already instructs the LLM to prefer YTDLP_ values. The HTML scraping exists only as a fallback when yt-dlp is missing — but it's fragile and YouTube changes their HTML structure periodically.

2. **Two subprocess calls where one suffices.** yt-dlp can extract subtitles AND metadata in a single invocation (`--write-subs --dump-json`). Currently the pipeline makes two separate calls: one for the transcript (via youtube-transcript-api) and one for metadata (via yt-dlp). A combined yt-dlp-first approach could reduce this to a single call with youtube-transcript-api as fallback.

3. **Description handling is sound.** The 3000-char limit, HTML linkification, and "supplementary source material" prompt guidance are well-designed. This is an area where video-lens is ahead of most competitors, which either ignore descriptions entirely or dump them raw.

4. **Chapter integration is good but limited.** Chapters anchor the Outline, which is the right use. However, concept doc 004 raises the question of whether chapters are underutilised — they could also inform Key Point grouping or provide section headers. This remains an open design question.

### 2.4 Error Handling

**Current approach:** String-prefixed error lines (`TRANSCRIPT_ERROR:`, `YTDLP_ERROR:`, `LANG_WARN:`) parsed by the LLM.

**Problems:**

1. **No structured error codes.** The LLM must string-match on error prefixes. This is ambiguous — what if a transcript line happens to start with "TRANSCRIPT_ERROR:"? Structured exit codes or JSON error objects would be more reliable.

2. **No retry logic.** fetch_transcript.py retries once on network timeout, but there's no exponential backoff. The supadata MCP server uses 3 attempts with 1s initial delay, 2x backoff, 10s max — a pattern worth adopting.

3. **Error granularity is coarse.** "Captions disabled" and "video not found" produce different error messages but the same TRANSCRIPT_ERROR prefix. The LLM must read the message to decide whether to retry or stop. Typed error codes (e.g. `ERROR_CAPTIONS_DISABLED`, `ERROR_VIDEO_PRIVATE`, `ERROR_NETWORK_TIMEOUT`) would enable the skill prompt to define different recovery strategies per error type.

4. **Silent failures in HTML scraping.** If regex extraction fails (title, channel, date, views), the script silently uses empty strings. This means the LLM may not know that metadata is missing and cannot warn the user.

### 2.5 Language Support

**Current:** 10 explicitly mapped languages (en, es, fr, de, ja, pt, it, zh, ko, ru) + BCP-47 passthrough.

**Assessment:** This is adequate for the 80% case. youtube-transcript-api supports all YouTube languages, and the BCP-47 passthrough handles unlisted languages. However:

- No support for YouTube's auto-translation feature (translating an existing transcript to another language). youtube-transcript-api supports this via `translate()` — it's free and would expand language coverage significantly.
- The "summary in original language" design is intentional and well-reasoned, but some users may want translated summaries. This could be a flag rather than a hard constraint.

### 2.6 Template & Report Quality

**Assessment:** The template is one of video-lens's strongest differentiators. The two-column resizable layout, embedded YouTube player with timestamp sync, dark mode, keyboard shortcuts, and Markdown export are features no competing skill offers. The typography (DM Serif Display / DM Sans / Georgia) and colour scheme are polished.

**Minor issues:**
- Template discovery searches 8 hardcoded agent paths. A new agent means editing the loop in 4 different scripts. This should be a shared config or environment variable.
- The `render_report.py` template substitution uses simple string replacement (`{{KEY}}`). If any template key value contains the literal string `{{ANOTHER_KEY}}`, it would be incorrectly substituted. Low risk in practice but technically a vulnerability.

---

## 3. Identified Flaws & Gaps

### 3.1 Critical

| # | Flaw | Impact | Evidence |
|---|------|--------|----------|
| C1 | **No proxy support** | YouTube blocks cloud provider IPs. Users on VPNs or corporate networks may fail silently. youtube-transcript-api natively supports proxies but fetch_transcript.py doesn't expose it. | youtube-transcript-api docs document `RequestBlocked`/`IpBlocked` exceptions as a known issue |
| C2 | **No fallback for captionless videos** | Videos without captions produce a hard stop. No speech-to-text option. tapestry-skills, mourad-ghafiri, and openclaw all have Whisper/ASR fallbacks. | SKILL.md explicitly stops on "captions disabled" |
| C3 | **YouTube Shorts blocked** | Shorts URLs are rejected despite Shorts having captions. kimtaeyoon83's MCP server handles Shorts. This is a growing content format. | SKILL.md line 38: "YouTube Shorts URLs are not supported" |

### 3.2 Significant

| # | Flaw | Impact | Evidence |
|---|------|--------|----------|
| S1 | **No transcript caching** | Re-fetches the same transcript on every invocation. Wastes bandwidth, increases latency, risks IP throttling. | fetch_transcript.py has no cache layer |
| S2 | **Brittle script discovery** | The 8-agent hardcoded path loop (`~/.agents`, `~/.claude`, `~/.copilot`, ...) must be updated for every new agent. It's duplicated in SKILL.md (2x), fetch_transcript.py discovery isn't needed (it's called from SKILL.md which already found the path), and render_report.py has its own copy. | SKILL.md lines 52, 68; render_report.py lines 15-22 |
| S3 | **HTML metadata scraping is fragile** | Regex patterns against YouTube's HTML break when YouTube changes their page structure. This has happened historically. The scraping is also redundant when yt-dlp succeeds. | fetch_transcript.py relies on patterns like `"title":"..."` which are YouTube-version-dependent |
| S4 | **No structured error codes** | String-prefix errors (`TRANSCRIPT_ERROR:`, `YTDLP_ERROR:`) require LLM string matching. Ambiguous and unreliable. | fetch_transcript.py, fetch_metadata.py error output format |
| S5 | **No caption type detection** | Users don't know if they're reading auto-generated or manual captions. Auto-generated captions have known quality issues (missing punctuation, misrecognised technical terms). | youtube-transcript-api provides `is_generated` flag; video-lens doesn't use it |
| S6 | **No pagination for long transcripts** | A 3-hour lecture produces a massive transcript that may exceed bash output limits (video-lens works around this with temp file reading, but the entire transcript still hits the LLM context). | SKILL.md handles temp file case but no chunking/summarisation strategy for extremely long content |

### 3.3 Minor / Polish

| # | Flaw | Impact |
|---|------|--------|
| M1 | **Template key collision risk** | `render_report.py` string substitution could replace `{{KEY}}` patterns within content values |
| M2 | **No duplicate detection** | Re-summarising the same video creates a new report instead of updating or warning. youtube-fetcher-to-markdown has this. |
| M3 | **Hardcoded port 8765** | serve_report.sh always uses port 8765. If another service occupies it, the kill is aggressive (kills whatever is on that port). |
| M4 | **No progress indication** | Long transcript fetches provide no intermediate feedback. The user sees nothing until the full pipeline completes. |
| M5 | **build_index.py O(n) full-file reads** | Already documented in concepts/007. Recommended solution (mtime cache + tail read) not yet implemented. |

---

## 4. Quick Wins

Low effort, high impact changes that can be implemented in 1-2 sessions each.

### QW1. YouTube Shorts Support

**Current:** Shorts URLs explicitly blocked (SKILL.md line 38).

**Change:** Add `youtube.com/shorts/VIDEO_ID` to the URL parsing table in Step 1. Shorts have captions and the same 11-character video ID format. The transcript-fetching pipeline already works — the only barrier is the URL parser rejecting the format.

**Effort:** ~15 minutes. One line in SKILL.md URL table + remove the Shorts error message.

**Impact:** Unlocks a growing content format (Shorts is YouTube's fastest-growing segment).

---

### QW2. Caption Type Detection

**Current:** No distinction between auto-generated and manual captions.

**Change:** In `fetch_transcript.py`, after selecting the transcript, check `transcript.is_generated` and output a new line: `CAPTION_TYPE: auto-generated` or `CAPTION_TYPE: manual`. In SKILL.md, append to META_LINE: ` · Auto captions` when auto-generated. Optionally add a subtle indicator in the template.

**Effort:** ~30 minutes. 3-line change in fetch_transcript.py + SKILL.md META_LINE instruction + optional template CSS.

**Impact:** Users know when to trust the transcript less. Particularly valuable for technical content where auto-captions mangle terminology.

---

### QW3. Proxy Support

**Current:** No proxy support. Users behind corporate firewalls or with blocked IPs cannot fetch transcripts.

**Change:** In `fetch_transcript.py`, check for `HTTPS_PROXY` or `YT_PROXY` environment variable. If set, pass to `YouTubeTranscriptApi` as the `proxies` parameter (the library already supports this natively). Document in SKILL.md error handling section.

**Effort:** ~30 minutes. 5-line change in fetch_transcript.py + SKILL.md documentation.

**Impact:** Unblocks users on restricted networks. Mitigates IP blocking from YouTube.

---

### QW4. Structured Error Codes

**Current:** String-prefix errors like `TRANSCRIPT_ERROR: Subtitles are disabled for this video`.

**Change:** Prefix errors with a machine-readable code:

```
ERROR:CAPTIONS_DISABLED: Subtitles are disabled for this video
ERROR:VIDEO_PRIVATE: This video is private or does not exist
ERROR:VIDEO_AGE_RESTRICTED: This video is age-restricted
ERROR:NETWORK_TIMEOUT: Request timed out after 30 seconds
ERROR:IP_BLOCKED: YouTube blocked the request (try setting YT_PROXY)
ERROR:YTDLP_MISSING: yt-dlp not installed (pip install yt-dlp)
ERROR:YTDLP_TIMEOUT: yt-dlp timed out after 60 seconds
```

Update SKILL.md error handling to match on the code prefix rather than free-text messages.

**Effort:** ~1 hour. Changes to fetch_transcript.py, fetch_metadata.py, and SKILL.md error handling section.

**Impact:** More reliable error detection by the LLM. Enables per-error recovery strategies in the skill prompt.

---

### QW5. Duplicate Detection

**Current:** Re-summarising the same video creates a new report file.

**Change:** In SKILL.md Step 4 (filename generation), before writing, check if a file matching `*video-lens*{VIDEO_ID}*` already exists in `~/Downloads/video-lens/reports/`. If found, ask the user: "A report for this video already exists ({filename}). Overwrite, or open the existing report?"

**Effort:** ~30 minutes. Bash glob check + SKILL.md conditional logic.

**Impact:** Prevents accidental duplicates. Saves time when users forget they already summarised a video.

---

### QW6. Consolidate Script Discovery

**Current:** The 8-agent discovery loop is duplicated in SKILL.md (2x), render_report.py, and potentially other scripts.

**Change:** Define the agent directory list once as an environment variable or shared config. Options:
- **Option A:** `VIDEO_LENS_SCRIPTS` env var set by the skill prompt at the start, passed to all subsequent scripts
- **Option B:** Each script accepts the scripts directory as an argument (SKILL.md already knows the path after the first discovery)

Recommended: **Option B** — SKILL.md discovers the path once in Step 2, then passes `$_sd` explicitly to all subsequent script calls. Scripts no longer need their own discovery logic.

**Effort:** ~45 minutes. Modify SKILL.md Steps 2b, 5, 6, 7 to pass `$_sd` as argument. Simplify scripts to accept path argument instead of self-discovering.

**Impact:** Adding a new agent means editing one list in SKILL.md instead of four.

---

## 5. Medium-Term Improvements

### MT1. Transcript Caching Layer

**Problem:** Every invocation re-fetches the transcript from YouTube. This is slow (~2-5 seconds), wastes bandwidth, and risks IP throttling.

**Proposal:** Add a file-based cache in `~/Downloads/video-lens/.cache/`:

```
.cache/
  transcripts/
    {VIDEO_ID}_{LANG}.json    # Full transcript + metadata
  metadata/
    {VIDEO_ID}.json           # yt-dlp metadata
```

Cache invalidation: TTL-based (e.g., 7 days). The transcript itself never changes, but metadata (view count) does. Could use separate TTLs: transcripts = infinite (or 30 days), metadata = 24 hours.

**Implementation:** Add `--cache-dir` argument to fetch_transcript.py and fetch_metadata.py. Check cache before fetching. Write to cache after successful fetch. SKILL.md already passes arguments — just add the cache dir.

**Effort:** 1-2 sessions. New caching logic in both Python scripts + SKILL.md flag.

**Impact:** Near-instant re-processing of previously fetched videos. Reduced risk of IP throttling.

---

### MT2. Whisper/ASR Fallback for Captionless Videos

**Problem:** Videos without captions produce a hard stop. This is a meaningful gap — many older videos, live streams, and niche content lack captions.

**Options:**

| Approach | Pros | Cons |
|----------|------|------|
| **Local Whisper (whisper.cpp / MLX)** | Free, private, works offline | Requires model download (1-6 GB), slow on CPU, needs audio extraction |
| **OpenAI Whisper API** | Fast, high quality | Costs money, requires API key, sends audio to cloud |
| **yt-dlp audio + local Whisper** | Combined: yt-dlp extracts audio, Whisper transcribes | Two-step pipeline, significant setup |
| **Qwen3-ASR MLX** (openclaw approach) | Apple Silicon native, competitive quality | M-series Mac only, newer/less tested |

**Recommendation:** Implement as a gated fallback — only trigger when captions are unavailable. Use local Whisper via `mlx-whisper` or `whisper.cpp` for Apple Silicon (video-lens is macOS-focused based on Raycast integration). Make it optional with clear documentation about model download requirements.

**Effort:** 2-3 sessions. New `transcribe_audio.py` script + yt-dlp audio extraction + SKILL.md fallback logic.

**Impact:** Unlocks an entire category of previously unsummarisable videos.

---

### MT3. MCP Server Wrapper

**Problem:** video-lens's transcript pipeline is locked inside a skill prompt. Other tools and agents cannot use it. An MCP server would make the transcript fetching composable.

**Proposal:** Wrap `fetch_transcript.py` and `fetch_metadata.py` into an MCP server with three tools:

```
get_transcript(video_id, lang?, use_cache?)
  → { transcript: [...], metadata: {...}, caption_type: "auto"|"manual" }

get_metadata(video_id)
  → { channel, duration, publish_date, views, description, chapters }

get_report(video_id, lang?)
  → { summary, key_points, takeaway, outline, tags, keywords }
  (delegates to LLM internally — this is the "full pipeline" tool)
```

**Trade-offs:**
- **Pro:** Any MCP client can use the transcript pipeline. Enables composition with other tools. Caching becomes natural (server-side state).
- **Con:** Adds infrastructure. The skill's simplicity (just Python scripts + a prompt) is a feature. An MCP server is a process that must be started, configured, and maintained.
- **Recommendation:** Build the MCP server as an optional complement, not a replacement. The skill continues to work standalone. The MCP server reuses the same Python scripts.

**Effort:** 2-3 sessions. New `mcp_server.py` using the MCP Python SDK. Wrap existing scripts.

---

### MT4. yt-dlp-First Architecture

**Problem:** The current pipeline fetches the transcript via youtube-transcript-api and metadata via yt-dlp in two separate calls. yt-dlp can do both in one call (`--write-subs --dump-json`).

**Proposal:** Restructure the pipeline:

1. **Primary:** yt-dlp fetches subtitles + metadata in a single call
2. **Fallback:** youtube-transcript-api fetches transcript if yt-dlp is unavailable or fails

This inverts the current dependency hierarchy. Benefits:
- Single network call instead of two
- yt-dlp's subtitle handling is more robust (handles more edge cases, actively maintained)
- Metadata and subtitles are guaranteed consistent (same video state)
- youtube-transcript-api becomes the lightweight fallback for users without yt-dlp

**Risk:** yt-dlp is currently "optional but recommended". Making it primary means users without it get a degraded experience (youtube-transcript-api fallback loses chapters, description, reliable metadata). However, the Taskfile already installs yt-dlp via `install-libraries`, so it's effectively a soft dependency.

**Effort:** 2-3 sessions. Restructure fetch_transcript.py and fetch_metadata.py into a single `fetch_video.py`. Update SKILL.md pipeline.

---

### MT5. Batch Processing

**Problem:** Summarising a playlist or channel requires invoking the skill once per video, manually.

**Proposal:** Accept playlist URLs and channel URLs. Use yt-dlp to extract video IDs from the playlist/channel, then process each sequentially (or in parallel with a concurrency limit).

**Existing art:** youtube-ai-digest already does channel-level batch processing with a configurable channel list.

**Effort:** 2-3 sessions. New `fetch_playlist.py` script + SKILL.md playlist handling + progress reporting.

---

## 6. Strategic Analysis: Build vs. Adopt

### 6.1 Should video-lens wrap an existing MCP server?

**Argument for adopting (e.g., kimtaeyoon83 or anaisbetts):**
- Maintained by active communities
- YouTube compatibility updates handled upstream
- Standardised MCP interface — works with any client
- kimtaeyoon83 has features video-lens lacks (ad filtering, Shorts support, Android client spoofing)

**Argument for staying self-contained:**
- Complete control over the pipeline
- No external dependency version conflicts
- The skill's value is in the LLM prompt + HTML template, not the transcript fetching
- MCP server adds infrastructure complexity (must be started, configured, kept running)
- The current approach (Python scripts + youtube-transcript-api) is battle-tested and understood

**Recommendation: Stay self-contained, but adopt specific techniques.**

The transcript fetching is not video-lens's differentiator — the summary quality, HTML template, and gallery are. Rather than depending on an external MCP server:

1. **Adopt kimtaeyoon83's ad-filtering technique** (using chapter markers to identify sponsor segments)
2. **Adopt jkawamoto's pagination approach** for very long videos
3. **Add Whisper fallback** (like tapestry-skills) as a gated option
4. **Build an optional MCP server** that wraps the existing pipeline (MT3) for users who want composability

This preserves the skill's simplicity while selectively incorporating the best ideas from the ecosystem.

### 6.2 Feature Comparison Matrix

| Feature | video-lens | kimtaeyoon83 MCP | anaisbetts MCP | tapestry-skills | youtube-ai-digest |
|---------|-----------|-----------------|----------------|-----------------|-------------------|
| Transcript fetching | youtube-transcript-api | Direct protobuf | yt-dlp | yt-dlp | yt-dlp |
| Metadata enrichment | yt-dlp (optional) | Built-in (title, author, views) | N/A | yt-dlp | yt-dlp |
| Shorts support | No | Yes | Unknown | Unknown | Unknown |
| Caption type detection | No | No | No | No | No |
| Proxy support | No | No | N/A (yt-dlp handles) | N/A | N/A |
| Whisper fallback | No | No | No | Yes | No |
| Caching | No | No | No | No | No |
| Pagination | No (temp file workaround) | No | No | No | No |
| Ad/sponsor filtering | No | Yes (chapter-based) | No | No | No |
| HTML report | Yes (best-in-class) | No | No | No | Markdown only |
| Gallery/index | Yes | No | No | No | No |
| Multi-language | Yes (10 + passthrough) | Yes (with fallback) | N/A | Unknown | Unknown |
| Batch processing | No | No | No | No | Yes (channels) |
| Summary quality | High (detailed prompt) | N/A (raw transcript) | N/A | Basic | Structured Markdown |
| Dark mode | Yes | N/A | N/A | N/A | N/A |
| Keyboard shortcuts | Yes | N/A | N/A | N/A | N/A |
| Timestamp sync | Yes (embedded player) | N/A | N/A | N/A | N/A |

**video-lens's unique advantages:** HTML report quality, gallery/index, embedded player with timestamp sync, dark mode, keyboard shortcuts, multi-language summary, detailed analytical Key Points.

**video-lens's gaps:** Shorts, Whisper fallback, caching, proxy support, ad filtering, batch processing.

---

## 7. Recommendations & Priority Matrix

### Priority 1: Quick Wins (implement now)

| ID | Change | Effort | Impact | Dependency |
|----|--------|--------|--------|------------|
| QW1 | YouTube Shorts support | 15 min | High | None |
| QW2 | Caption type detection | 30 min | Medium | None |
| QW3 | Proxy support | 30 min | High | None |
| QW4 | Structured error codes | 1 hour | Medium | None |
| QW5 | Duplicate detection | 30 min | Medium | None |
| QW6 | Consolidate script discovery | 45 min | Medium | None |

**Total effort:** ~3.5 hours. All are independent and can be done in any order.

### Priority 2: Foundation Improvements (next cycle)

| ID | Change | Effort | Impact | Dependency |
|----|--------|--------|--------|------------|
| MT1 | Transcript caching | 1-2 sessions | High | QW4 (error codes) |
| MT4 | yt-dlp-first architecture | 2-3 sessions | Medium | MT1 (caching) |
| M5 | Gallery incremental indexing | 1-2 sessions | Medium | Already designed in concepts/007 |

### Priority 3: Capability Expansion (future)

| ID | Change | Effort | Impact | Dependency |
|----|--------|--------|--------|------------|
| MT2 | Whisper/ASR fallback | 2-3 sessions | High | MT4 (yt-dlp-first for audio extraction) |
| MT3 | MCP server wrapper | 2-3 sessions | Medium | MT1, QW4 |
| MT5 | Batch processing | 2-3 sessions | Medium | MT1 (caching) |

### Implementation Order (recommended)

```
Phase 1 (Quick Wins):
  QW1 → QW2 → QW3 → QW4 → QW5 → QW6
  (all independent, do in a single session)

Phase 2 (Foundation):
  MT1 (caching) → MT4 (yt-dlp-first) → M5 (gallery incremental indexing from concepts/007)

Phase 3 (Expansion):
  MT2 (Whisper fallback) → MT3 (MCP server) → MT5 (batch processing)
```

---

## Appendix A: MCP Server Transport Comparison

| Transport | Use Case | Examples |
|-----------|----------|---------|
| stdio | Local agent (Claude Code, Cursor) | kimtaeyoon83, jkawamoto, anaisbetts |
| SSE | Remote / cloud deployment | ergut (Cloudflare Workers) |
| Streamable HTTP | Hybrid (local or remote) | egoist/fetch-mcp |

For video-lens, **stdio** is the right choice if building an MCP server — it matches the local, zero-infrastructure philosophy.

## Appendix B: Transcript Quality by Source

| Source | Punctuation | Technical Terms | Timing Accuracy | Reliability |
|--------|-------------|-----------------|-----------------|-------------|
| Manual captions | Full | Accurate | Sentence-aligned | High |
| YouTube auto-generated | Often missing | Frequently wrong | Per-word (1-5s segments) | Medium |
| YouTube auto-translated | Full (machine) | Machine-translated | Inherited from source | Low-Medium |
| Whisper (local, large model) | Full | Good for English | Per-word | High (English), Medium (other) |
| Whisper (local, tiny model) | Partial | Frequently wrong | Per-word | Low-Medium |

## Appendix C: IP Blocking Mitigation Strategies

| Strategy | Implementation | Cost |
|----------|---------------|------|
| Proxy environment variable | `HTTPS_PROXY` → youtube-transcript-api | Free (user provides proxy) |
| Rotating residential proxies | Webshare integration (youtube-transcript-api docs) | ~$5-30/mo |
| Android client spoofing | protobuf-based direct API (kimtaeyoon83 approach) | Free but maintenance burden |
| Commercial transcript API | TranscriptAPI.com, Supadata | Pay-per-use |
| yt-dlp with cookies | `--cookies-from-browser` flag | Free but fragile |

**Recommendation for video-lens:** QW3 (proxy env var) covers the 90% case. Users who need more can set up rotating proxies or cookies themselves. The protobuf approach (kimtaeyoon83) is clever but creates a maintenance burden that outweighs its benefit for a skill that prioritises simplicity.
