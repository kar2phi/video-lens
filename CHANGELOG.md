# Changelog

All notable changes to **video-lens** and the bundled **video-lens-gallery** skill.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). There are no
git tags in this repo — versions here track the `metadata.version` field of
`skills/video-lens/SKILL.md`, read out of the history at each commit. The gallery skill
carries its own version; it is called out wherever it moved. Each entry lists the commits
it was reconstructed from.

## [5.2] — 2026-08-22

_video-lens-gallery 2.1._ Findings from `concepts/024-comprehensive-skill-assessment.md`.

### Fixed

- Renderer no longer hard-fails on a `{{UPPER_CASE}}` token quoted in agent content —
  a video about Jinja, Handlebars or GitHub Actions puts one in front of the model, which
  quotes it back. Placeholders are collected before substitution and replaced in one pass,
  so injected text is never rescanned (B1).
- `_format_duration` returns blank instead of `0 min` for live streams and premieres,
  matching the adjacent `_format_views` (B2).
- HTML-scraped metadata is decoded: the `<title>` is run through `html.unescape` and
  `channelName` is parsed as a JSON string literal, so `Rock &amp; Roll` and
  `Café` no longer reach the report headline verbatim. `fetch_metadata.py` also
  emits `YTDLP_TITLE`, the one clean source for the title (B3).
- An empty `META_LINE` no longer renders a dangling `·` before the YouTube link (B4).
- The gallery manifest sorts on the filename's basename, so `reports/` entries no longer
  outrank older bare-path ones regardless of date (B5).
- Reports honour `prefers-color-scheme` on a first visit, as the gallery already did — a
  dark-mode user no longer gets a white report beside a dark gallery (B6).
- Markdown export keeps `**bold**`, `*italic*` and `` `code` `` structure via a new
  inline walker, and defers the object-URL revoke so the download completes in browsers
  other than Chrome (B7).
- `backfill_meta.py` escapes `</` in the JSON meta block the same way the renderer and
  `build_index.py` do, so a title or summary containing a literal `</script>` cannot
  truncate it — thanks [@stantheman0128](https://github.com/stantheman0128) (#2).

### Changed

- The Raycast script passes its model argument through verbatim and omits `--model` when
  blank. The pinned model IDs and the Taskfile's per-agent model rewriting are gone —
  they were two generations stale and a standing maintenance tax (B8).
- The Raycast URL guard accepts `m.youtube.com`, which is what the iOS share sheet emits
  and what `preflight.py` already accepted (B8).

### Security

- Payload files moved from `~/Downloads/video-lens/.tmp/` to
  `${XDG_CACHE_HOME:-~/.cache}/video-lens/payloads/`, outside the tree the local report
  server publishes. Payloads written to the old location keep ageing out under the
  existing TTL and the directory is removed once empty (H1).

### Accessibility

- Outline entries are keyboard-operable: `role="button"`, `tabindex`, a synced
  `aria-expanded`, Enter/Space activation and a `:focus-visible` ring. Expansion was
  mouse-only before (U4).

_Commits: `f5b826c`, `887a42d`, `9f8125d`._

## [5.1] — 2026-08-22

### Added

- `--audio-file` escape hatch for `transcribe_local.py`: transcribe a file the user
  already has when YouTube blocks the download outright. `VIDEO_ID` stays required (the
  report header is still built from the video's public metadata) and the file is left in
  place.

### Fixed

- The yt-dlp audio fetch is bounded by a 900 s subprocess timeout, reported through the
  existing `ERROR:AUDIO_DOWNLOAD_FAILED` contract. `--socket-timeout` only bounds
  individual reads, so a throttled transfer used to run until the agent's 600 s Bash cap
  killed the whole step with no structured error (H4).
- The largest non-`.part` file is picked after a download, so an interrupted transfer is
  never handed to Whisper as if it were the complete recording.
- A download failure on a pre-2026.8.19 yt-dlp carries an upgrade hint, instead of the
  bare `HTTP Error 403: Forbidden` that reads like an IP ban.

### Changed

- `yt-dlp>=2026.8.19` is now required for local transcription: older builds resolve media
  through the `android_vr` client, and YouTube serves only the first ~1 MiB from those
  URLs.
- `ERROR:AUDIO_DOWNLOAD_FAILED` has its own row in the SKILL.md error table, routing to
  the upgrade hint first and the escape hatch second.

_Commit: `566c8bd`._

## [5.0] — 2026-06-12

_video-lens-gallery 2.0._

### Added

- Local Whisper transcription fallback (`transcribe_local.py`, mlx-whisper) for videos
  without captions; its output is byte-compatible with `fetch_transcript.py`, so the
  downstream steps need no changes.
- The fallback is offered on `CAPTIONS_DISABLED`, `NO_TRANSCRIPT`, `IP_BLOCKED`,
  `PO_TOKEN_REQUIRED` and persistent `REQUEST_BLOCKED`.
- `fetch_metadata.py` emits a normalized `YTDLP_LANGUAGE` (BCP-47 → ISO-639-1 primary
  subtag).

### Fixed

- `serve_report.sh` kills an untracked `http.server` occupying port 8765 and reports
  `ERROR:SERVE_PORT_BUSY` for non-http occupants.

### Changed

- The gallery skill gates its success message on the `HTML_REPORT:` line and reports
  `ERROR:` codes instead of claiming success.

_Commit: `7a182d7`._

## [4.0] — 2026-05-18

### Added

- `preflight.py`: URL validation, video-id extraction and duplicate checking, run before
  anything else.

### Changed

- `render_report.py` took over the mechanical glue — `--output-dir`, slug derivation,
  duration math and `META_LINE` composition.
- SKILL.md shrank ~22 % (299 → 233 lines) as that logic left the prompt.
- ~190 lines of new test coverage in `tests/test_e2e.py`.

_Commit: `3fc20d2`._

## [3.0] — 2026-05-16

### Security

- Allowlist HTML sanitiser in `render_report.py`, blocking XSS through injected JSON.
- `VIDEO_ID` and `VIDEO_URL` validation; output paths clamped to the reports subdirectory.
- Untrusted-input guardrail and a bundled-scripts section added to SKILL.md.
- Security-focused tests: script escaping, `javascript:` URLs, path traversal.

### Fixed

- `serve_report.sh` binds `127.0.0.1` via `nohup`, giving the server a stable lifecycle.

### Changed

- README install instructions (Option B) and Taskfile `REPORTS_DIR` expansion.

_Commit: `aa3fadc`._

## [2.0] — 2026-03-14 → 2026-03-27

### Added

- **video-lens-gallery skill** — `index.html` viewer, `build_index.py`,
  `backfill_meta.py` and the `build-index` task (2026-03-19).
- Typed `ERROR:` codes across the fetch scripts, with a matching error table in SKILL.md.
- Pre-flight duplicate check; the video ID is embedded in report filenames.
- pytest end-to-end suite with fast/slow markers, plus `test` and `test-full` tasks.
- `install-skill-local` for syncing to local agent directories, `npx skills add
  kar2phi/video-lens` as the published install path, and SKILL.md frontmatter (license,
  compatibility, metadata).
- Report and gallery UX: back-to-gallery link, drag-to-seek progress bar, outline fade
  animation, gallery theme toggle, "+N more" tag chips, empty state, card hover.

### Changed

- `skill/` → `skills/video-lens/` for the standard skills CLI layout; `install` renamed to
  `install-libraries`.
- Inline Python blobs in SKILL.md replaced by modular scripts (`fetch_transcript.py`,
  `fetch_metadata.py`, `render_report.py`, `serve_report.sh`).
- Reports moved to `~/Downloads/video-lens/reports/`; `serve_report.sh` uses a PID file
  and accepts a directory argument; yt-dlp floor raised to 2026.3.17.

### Fixed

- YAML error in the SKILL.md frontmatter.
- Template lookup scans multiple agent directories at runtime.
- Resizer handle visibility, help modal overflow, section nav underline weight.

_Commits: `906fb13`, `c254f34`, `dd999ce`, `95d99f2`, `e93ad7a`, `deb7779`, `3e8dc05`,
`bcdfd2d`, `d5437c7`._

## [1.0] — 2026-03-08 → 2026-03-13

Predates the `version` field in SKILL.md; recorded here as 1.0.

### Added

- Initial release: YouTube URL in, polished HTML report out — executive summary, key
  points, timestamped outline with click-to-seek, lightweight embedded player, dark mode,
  one-click Markdown export, and a Raycast launcher.
- Takeaway section (the 1–2 sentence "so what?"), collapsible outline entries with
  title + detail, and a structured error-handling section.
- Multi-agent support: Copilot, Gemini CLI, Cursor, Windsurf, OpenCode and Codex, with
  SKILL.md paths and Raycast CLI flags patched per agent at install time.
- yt-dlp enrichment for richer metadata; playback-speed controls and a resizable layout.

### Changed

- Transcript sampling replaced by full sequential reads.
- Key Points rewritten to carry inline analytical paragraphs; the standalone Analysis
  section was removed and Summary/Takeaway overlap ruled out explicitly.
- Rigid per-length bullet counts replaced by a content-density-driven range (3–8).
- Raycast default model changed from haiku to sonnet.

### Fixed

- URL sanitisation and path quoting in the Raycast script.

_Commits: `4111f83`, `6eed640`, `79fdc28`, `e8e5d08`._
