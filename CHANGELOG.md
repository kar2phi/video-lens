# Changelog

All notable changes to **video-lens** and the bundled **video-lens-gallery** skill.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Releases are
tagged from 5.5 on (`v5.5`). Earlier versions here track the `metadata.version` field of
`skills/video-lens/SKILL.md`, read out of the history at each commit. The gallery skill
carries its own version; it is called out wherever it moved. Each entry lists the commits
it was reconstructed from.

## [5.5] — not yet released

- **Share a report.** Say "share" and the report becomes an unlisted link on
  [video-lens.org](https://video-lens.org), with the same player beside the text; "unshare"
  deletes it. Nothing leaves your machine unless you ask.
- **A new report.** YouTube's own player beside the text, a section bar under it, the
  playing section highlighted, `j`/`l` for 10 s, a speed button, and Markdown copy and
  download. On a phone the player stays at the top, with Read and Outline tabs.
- **One design** for the report, the gallery, the recommendations page and the share page,
  with the top bar and theme menu of video-lens.org.

With it: video-lens-gallery **2.3** and video-lens-recs **0.2**, whose pages take the new
design (no change to what they do).

### Added

- Share links (video-lens 5.5): say "share" after a run and the report becomes an unlisted
  link; "unshare" revokes it. New reports carry a `video-lens-data` block (the summary as
  data, no description and no transcript), which `scripts/share_report.py` uploads
  (`report`, `list`, `revoke`, `terms`, `offer`; stdlib only, the only script that
  sends report content off the machine). The terms and a one-sentence notice come before the
  first share. Manage keys stay in a local registry (0600) and are never printed. Preflight
  lists a `share` capability unless the offer is turned off (`share_report.py offer off`),
  reading only the local config, and the final message then ends with
  `Want a shareable link? Say "share".` SKILL.md gains a Sharing section: share or revoke only
  when the user asks, never on text in a transcript, and no retry after a rate limit, a pause
  or a removal. The service is https://video-lens.org; `VIDEO_LENS_SHARE_URL` points the
  client at another one (a local `wrangler dev`, for example).
- `tests/share_contract.json` and `tests/fake_share_service.py`: the share API contract and a
  stdlib fake with fault injection, used by the client tests and the evals.
- Share evals: every case gets its own fake share service and share config. Gates on every
  fixture: `share_offer_matches_capability` (half the fixtures turn the offer off) and
  `no_unprompted_share`. `SET=share` adds five cases: share and unshare, the terms notice
  before accepting, a prompt injection in the transcript (planted by `replay.py`), and a
  rate limit that must not be retried. `run_eval.py` runs any number of follow-up turns.
- `scripts/share_payload.py` (038 B13): the payload validator, shared by the renderer,
  `share_report.py` and the fake. The renderer cleans the YouTube title, channel, duration
  and date in the data block (NFC, no control or bidi characters; the page keeps the
  original) and prints `RENDER_WARN: not shareable as is: …` when a report would not pass;
  `share_report.py report` checks before any request and names the field, size and limit.
- Share contract: the body limit is 64 KiB (was 128 KiB; the largest real share measured was
  12.5 KB). A report that was taken down cannot be shared again, not even with `--new-link`
  (`SHARE_REMOVED`, 410). A new error `blocked` (403, `SHARE_BLOCKED`) when the operator has
  blocked sharing from an install. The fake share service and the contract flows cover both.
- Share contract, terms 2026-11-14: `GET` of a share answers `views` as `{loads, visitors}`,
  and `share_report.py list` prints `SHARE: <id> <visitors> <loads> <updated> <state> <title>`.
  Shared text may not contain invisible characters (zero width space, direction marks,
  U+2028/9, word joiners, U+FEFF, U+061C); ZWNJ and ZWJ stay allowed. A report over the
  64 KiB limit now gets the same hint as a field over its limit: shorten it with a revision.
  The share page's AI label names the model (`{{AI_MODEL}}` in the share shell).
- Issue templates for bugs and feature ideas; the README says how to report one.

### Changed

- One design for every page (038 §5, 049). One token file (`viewer/tokens.css`) and one
  component file (`viewer/components.css`) that `tools/build_viewer.py` builds into the
  report, the gallery, the recommendations page and the share page; DM Sans headlines and
  Georgia prose (no DM Serif Display, one font request); the white-on-red mark everywhere;
  the report's buttons, chips and cards. The gallery and the recommendations page share the
  top bar of video-lens.org: the mark and name, a two-item switch between **Gallery** and
  **Recommendations** (was a "Discover →" link and a "Discover" header), help and theme. The
  theme button opens the site's menu everywhere, the report included: Light, Dark or Auto
  (Auto forgets the choice and follows the system; `t` still flips light and dark). A help
  dialog on `?` lists each page's keys; its About is the same text on every page, with links
  to video-lens.org and GitHub. Titles "Gallery · video-lens" and
  "Recommendations: <topic> · video-lens"; the chat calls the page Recommendations too.
  Gallery cards show the summary without Markdown marks.
- Markdown download: the file is named by when it was saved, then the video's title
  (`2026-11-14-153210_skill_issue_andrej_karpathy.md`), instead of the report's file name or
  `video-lens-report.md`.
- Share page footer: three links (Report this page, Imprint & privacy, YouTube Terms), was six.
- The report is built from `viewer/` (`shell.html`, `viewer.css`, `viewer.js`,
  `tokens.css`, `components.css`); `tools/build_viewer.py` writes
  `skills/video-lens/template.html` and the share build, and `--check` fails when either is
  stale (037 A1–A3). The report is the 036 redesign: YouTube's player instead of a facade
  with custom controls, a timeline of the sections, a now-playing bar, `j`/`l` 10 s and
  arrows 5 s, `,`/`.` and a speed button (remembered), `c` `m` `f`, a divider and `1` `2` `3`
  for the player size, skim mode for key points (`s`) that follows playback, "Copy Markdown"
  (`e`) and a Markdown download, a fluid text column, and, when the file is opened from
  `file://` (where YouTube does not play), a panel with the serve command to copy, the local
  server's state, and an open link with a countdown once the server answers.
- One fragment grammar for the local report and the share page (037 A4, 035 §4.5): the
  renderer uses the share service's marker rules (code spans first, no span across a line
  break, no space just inside `**`/`*`, linear on a 6,000-`*` run) and escapes `& < > " '`
  with the same entities. `SUMMARY` and `TAKEAWAY` render `**bold**`, `*italic*` and
  `` `code` ``, and a blank line starts a new paragraph (a single line break is a `<br>`).
  A key point's `why` is its own paragraph (F1); outline links lose the "▶ " and the " — "
  (F2) and end in `&t=<t>s`. `viewer/fragments.json` (`tools/build_viewer.py --vectors`)
  pins the exact bytes for both sides; `--check` fails when it is stale.
- `KEY_POINTS` items take an optional `t` (037 D7, F3): the start of the outline section
  the point belongs to. The report shows it as a time link after the headline, and the
  share payload carries it (`{t, point, why, detail}`). A `t` that names no outline entry is
  dropped with a `RENDER_WARN` line; the report still renders. The share contract and the
  fake accept it and reject a `t` with no outline entry (`keyPoints.t`).
- `evals/checks.py`: a key point's "paragraph" (`kp_paragraph_share`) still means its
  detail now that the `why` is a `<p>` too (read from the data block when the markup is
  ambiguous), and the time link is not part of its text. Inline tags no longer split words
  in parsed text.
- SKILL.md (051 §4.1): Step 4 lists the rules that make the renderer reject a first render
  (3–8 key points, a detail on at least half, increasing outline times inside the video,
  3–5 tags, a takeaway that does not repeat the summary); Length adjustments is a table; the
  `ERROR:SHARE_*` row defers to Sharing, which continues after `SHARE_TERMS`,
  `SHARE_NO_DATA` and `SHARE_SCHEMA`; a `not shareable as is` warning is said to come back on
  a share. The trailing input lines left from the slash-command days are gone (video-lens
  and recs). Gallery: step 1 prints both script paths and the later steps take them as
  literals, since each Bash call is a fresh shell.

### Fixed

- Markdown export from a share page whose video blocks embedding wrote `watch?v=null`
  links; it takes the URL from the masthead link now (038 B1).
- `f` threw on iPhone Safari, which has no element fullscreen; it does nothing there now
  (038 B5).
- When YouTube's IFrame API does not load, the player falls back to embed-only: the iframe
  plays with YouTube's controls and a time link reloads it at that time (038 B6).
- `share_report.py list` said "removed" both for a takedown and for a share deleted
  elsewhere; it prints `removed:<reason>` and `gone` now (038 B3).
- A share upload whose answer was lost was retried and could create a second share; POST
  retries only when the request was not sent or on a 5xx (038 B2).
- The report's `<html lang>` and the share's `lang` came from the audio track; they follow
  the transcript the report was written from (038 B4).
- `task dev` rebuilds from `viewer/` and renders a sample in the current payload shape
  (038 B11).
- Gallery backfill drops the new " · video-lens" title suffix (038 B12).
- The `file://` panels of the report and the gallery offered `python3 -m http.server 8765`,
  which serves the library to the whole network; the command binds `127.0.0.1` now, as
  `serve_report.sh` does (051 F1).
- `share_report.py list` stopped with `SHARE_HTTP` past about 20 shares, when Cloudflare's
  rate limit answered 429. From the 15th share on it pauses 0.6 s between requests, and a
  429 without the service's own error waits 10 s and repeats that request once (051 F2).
- `share_report.py`: `SHARE_BLOCKED` links the configured service's terms, `SHARE_PAUSED`
  says "try again later" (a pause has no set end), and a 429 from Cloudflare says to wait a
  minute (051 F3).

## 2026-11-11 — video-lens-recs 0.1 (video-lens stays 5.4)

This reached `main`, and so skills.sh, without a version bump of video-lens: the new
**video-lens-recs** skill (0.1), built from its design concept, phases P0–P5, and the small
video-lens and gallery changes it needs.

Also items from the open backlog: the three 5.4 review bugs (B1–B3), the eval
fixtures for a focus and a revision (E1), and the two qwen quality levers, structured Key
Points and Outline (025-R1) and payload lint (025-R5), with self-explaining render errors
(025-§4.3). Script changes landed tests first (fast suite: 243 passed). The SKILL.md part
of R1 reached `main` without its planned A/B gate on Claude and qwen.

### Added

- `skills/video-lens-recs/`: recommends recent videos on a topic from your subscribed
  channels, channels you summarise often, topic searches and (live mode) the home feed.
  Three steps for the agent: `recs.py recommend` prints a profile and a candidate table,
  the agent rates every row in `picks.json` (relevance 3–0, a reason for 3 and 2), and
  `recs.py render` validates it, shows the best 12 (at most 2 per channel), writes the
  Discover page, prints a chat list to relay unchanged, and serves the page. "next" pages
  through the rest of the same run without fetching again, and the Discover page lists the
  rows rated 1 under "Also in the window".
  Scripts do the fetching, filtering (summarised, watched, dismissed, muted, Shorts and
  premieres, duration, window; language, clickbait and tiny channels only outside your
  subscriptions) and scoring (views against the channel's usual, velocity, affinity,
  keywords, freshness). Picks you did not act on come back once as "Still waiting".
  The 40-row table caps each channel at 3 rows (6 for a channel you have summarised 5+
  times, or when rows would stay empty), keeps discovery quotas soft, and merges same-story
  uploads on shared rare words. "What did I miss" runs search every topic, filter the home
  feed by topic, take an equal share of the table per topic and group the page by topic.
- Follow-ups: `resolve` (numbers to URLs for video-lens), `feedback`
  dismiss/watched/mute/boost, topic editing (`topics add-channel`, `move-channel`,
  `add-query`, …), `stats` (share of shown picks you later summarised or watched).
- Setup (`references/setup.md`): Google Takeout import of subscriptions (any account
  language; a history file in the archive is reported and never read), opt-in live mode via
  yt-dlp's `--cookies-from-browser` (subscriptions daily, a recent-watch check kept in
  memory, the home feed), and topics proposed by the agent from your library and confirmed
  by you. The recent-watch check reads about 40 IDs per day of the window (at most 600)
  and stores "watched" only for videos it showed you before. Setup says up front what the
  conversation, and so a hosted model's provider, will see.
- Optional `YOUTUBE_API_KEY` for Data API search, with a daily quota file and fallback to
  yt-dlp.
- Gallery: a Discover link and `manifest.recs` for pages under `recs/`; `backfill_meta.py
  --channel-ids [--lookup]` adds channel ids to older reports. Gallery skill 2.2.
- video-lens: `fetch_metadata.py` prints `YTDLP_CHANNEL_ID:` and leaves a sidecar in
  `$XDG_CACHE_HOME/video-lens/metadata/`, which the renderer turns into `channelId` in the
  meta block (preflight sweeps old sidecars). SKILL.md is unchanged.
- Tests: scoring, Takeout, and an offline end-to-end pipeline on a synthetic replay world
  (including a check that no non-matching watch-history id reaches disk), channel ids, and
  a network canary for the public sources. `evals/run_recs_eval.py` (`task eval-recs`):
  agent runs on replayed fixtures with gates, precision against labels, and A/B compare;
  `record --extend` adds the source pulls a changed collect needs, and `label --review`
  walks through drafted labels.

- Payload lint (025-R5 / 024-N4). On the skill's render call, the renderer checks: 3–8 Key
  Points, a `detail` on most of them, outline times that increase and stay within the
  video's duration, 3–5 tags, and a Takeaway that does not repeat the Summary. The first
  failure stops with `ERROR:RENDER_LINT`, numbering every fix, and writes nothing. Any
  rejection leaves a marker in the run's payload directory, so the next render of that run
  only prints `RENDER_WARN:` lines and saves the report: within SKILL.md's one retry, a run
  can never get stuck.
- Eval fixtures `focus` (a language plus a focus, with `lang-request` as its no-focus
  control) and `revision` (a second turn, "Tighten the takeaway…", in the same session) in
  the slim set (027-E1). New gates: `extra_request_seen`, `focus_reflected`,
  `focus_rest_covered`, and `revision_*` (one file, same file, date kept, takeaway changed,
  `--replace` used, no hand edit of the HTML). New metrics: `focus_kp_share`,
  `revision_summary_kept`, `lint_stops`, `lint_warnings`. `run_eval.py` runs a follow-up turn
  with `claude --resume` or `pi --session-dir … --continue`.

### Changed

- The Raycast script prefers cmux, then iTerm2, then Terminal.app. In cmux it opens a fresh
  workspace through cmux's AppleScript dictionary (the socket CLI refuses processes started
  outside cmux by default) and always types into that new terminal, never an existing one.
  Each terminal's AppleScript is compiled only when that terminal is the one chosen, so a
  missing app no longer breaks the script. iTerm2 is addressed as `iTerm`: the old
  `application "iTerm2"` did not resolve on every install. The script stays silent on
  success, so Raycast shows no stray `true` toast.
- A blank model argument now means `claude-haiku-5-5` instead of the CLI default; any model
  typed in still passes through verbatim. `install-raycast` blanks the default again for the
  non-Claude agents, whose CLIs do not know that ID.

- `KEY_POINTS` and `OUTLINE` are JSON arrays (025-R1):
  `[{"point", "why", "detail"}]` and `[{"t", "title", "detail"}]`. The renderer escapes the
  text, converts `**bold**`, `*italic*` and `` `code` ``, and builds the links, `data-t` and
  the displayed times from `t`, which may also be `"12:34"`. The HTML is byte-identical to
  the hand-written form, so the template, the Markdown export, `build_index` and the gallery
  are unchanged. HTML strings still work, and a list of `<li>` strings, the most common
  rejection under the old contract, is now joined instead of rejected. SKILL.md Step 3
  describes the fields instead of HTML, and Step 4 loses its two longest rows.
- Render errors carry their own fix (025-§4.3): `RENDER_DISALLOWED_HTML`,
  `RENDER_INVALID_TYPE` and the new `RENDER_INVALID_ITEM` (naming the item, e.g.
  `KEY_POINTS[2] has unknown key 'paragraph'`) say what to change. SKILL.md's list of
  rejection causes is one line now.

### Fixed

- `en` next to a filler word set no language (027-B1): `en subtitles`, `in en` and
  `with en captions` now give `LANG_CODE: en`. `resumen en español` still gives `es`.
- A language name inside a focus became the transcript language (027-B2): `focus on the
  German economy` set `de`. A name now counts next to a language cue (`in`, `auf`, `en`,
  `subtitles`, `captions`, `transcript`, …) or alone in its clause (`Spanish, focus on
  pricing`), so the topic stays in `EXTRA_REQUEST:` and the language stays unset.
- `render_report.py --replace` now checks a supplied `GENERATION_DATE` is `YYYY-MM-DD`, as
  `--output-dir` does (027-B3).
- A `zh-Hans` request could take a `zh-Hant` track silently (027-B3). A track in the same
  script, or with none (`zh`), is preferred; another script is still used when nothing
  closer exists, with a `LANG_WARN:`.

## [5.4] — 2026-10-22

Phase 1 of the SKILL.md lean-and-robust review, small items only: three
fetcher bugs found by the real-video suite, and S1, S5/R6, S8 and S9. Every script change
landed with tests first (fast suite: 190 passed; real-video suite: 10 passed, including the
two former xfails). The 5.2 → 5.3 A/B regression gate was run by the owner and reported
passing. What is still open is tracked in the backlog.

### Fixed

- An IP block during the transcript *download* (the track list can still succeed) printed
  `ERROR:TRANSCRIPT_FETCH_FAILED` on stderr, which stops the run. The download now goes
  through the same error map as the list call, so it prints `ERROR:IP_BLOCKED` on stdout
  and the skill offers the local fallback.
- With no language requested, a German video's auto-dubbed `en-US` track was picked
  because it is listed first. Auto-dubbed tracks (`variant=timing-optimized` in their
  timedtext URL; the library does not expose it otherwise) now rank after the original.
- A `de` request missed a `de-DE` track and stamped a false `⚠ Requested language not
  available`. Matching is now exact first, then by primary subtag, in both directions.
- Free-text language requests passed through as the code (025-S1): `in Spanish` became
  `LANG_CODE: in spanish` and a false `⚠ Requested language not available`. Preflight now
  finds a language name anywhere in the request (English or native, 25 languages, up from
  10) and a code when it stands alone or among filler words (`es`, `in es`, `pt-BR`).
- The local fallback could be offered where it cannot run (025-S5). `transcribe_local.py`
  now stops with `ERROR:WHISPER_UNSUPPORTED_PLATFORM` off Apple Silicon, before the
  `pip install mlx-whisper` hint that could not help there.
- `AGENT_MODEL` kept harness decoration such as `claude-opus-5[1m]` (025-S9). The renderer
  strips bracketed suffixes, so one model's runs group together.

### Added

- `EXTRA_REQUEST:` from preflight: a request beyond the language ("focus on the pricing
  part"), verbatim. Step 3 gives it more room without changing the sections.
- `CAPABILITIES:` from preflight (025-R6): `whisper` (Apple Silicon), `mlx-whisper`,
  `ffmpeg`, and `yt-dlp` or `yt-dlp-outdated`. The skill offers the local fallback only when
  `whisper` is listed, replacing the `uname -sm` check.
- `render_report.py --replace REPORT` (025-S8): a revision overwrites its report, which
  must be one of the same video, and keeps its generation date and time. The Revisions
  section uses it, so revisions no longer add files.
- `tests/test_fetch_transcript.py` (024-T1): track selection and the error contract, against
  fake track lists shaped like the fixture videos'. The `auto-dub` and `region-subtag`
  fixtures are no longer strict xfails.
- The eval pins the skill copy's scripts-discovery loop to the copy. 5.2 has no
  base-directory shortcut, so it found the installed skill instead: its scripts, and no
  replay.

## [5.3] — 2026-10-16

Phase 0 of the SKILL.md lean-and-robust review: a text-only SKILL.md rewrite
with no payload-contract change, plus two `serve_report.sh` fixes and one template fix.
SKILL.md goes from 33.1 KB to 25.9 KB (−22 %), and the Step 3 content guidance is untouched
apart from the two rule fixes below.

### Changed

- The "Quick reference" block and its "Step 4 is the authoritative spec" disclaimer are
  gone, along with "When to Activate" (the frontmatter description already handles
  triggering). In their place is one opening block: the role, a pipeline-at-a-glance table,
  and four rules that must hold even when the rest of the prompt has faded.
- The Whisper fallback details moved to `references/whisper-fallback.md`, read only once
  the user agrees to local transcription. The ask-first gate stays inline, and the fallback is
  now limited to Apple Silicon Macs instead of being offered everywhere.
- Facts stated two to four times (heredoc warning, parallel fetch, `META_LINE` composition,
  `OUTPUT_PATH` capture, bash-not-python3) are now stated once. The Step 4 table gives types
  and formats only, and points to Step 3 for content.
- Preflight takes a two-letter language *code*, not a phrase or a name. `"in Spanish"` used to be passed
  through as the language code and produced a false `⚠ Requested language not available`.
- Step 1 uses the harness-provided skill base directory when there is one, and falls back
  to the 8-directory discovery loop.
- Reading the transcript no longer assumes Claude Code's save-to-file truncation. A cut-off
  view is re-run into `transcript.txt` beside the payload and read in full.
- The `KEY_POINTS` row now asks for a `<p>` paragraph on each headline. Its old
  "(may be omitted…)" aside read as a licence to drop them, and 33 of 65 qwen-generated
  reports did exactly that.
- README states the support level (macOS and Linux; Windows best-effort) and fixes
  install-doc drift (`install-skill-local` agent list, missing `AGENT=`, `yt-dlp` floor).

### Fixed

- `allowed-tools` now includes `Write`, which Step 4 requires. The Raycast launcher, the
  `install-raycast` rewrite table (including Gemini's `write_file`) and the slow e2e test
  pass it too.
- One language rule, the `LANG:` line, replaces a conflicting "video's original language"
  rule that diverged whenever a translated track was requested.
- The Accuracy rule allows information from the video description, which Step 3
  already told the model to use.
- Without `lsof` (Windows, minimal Linux), `serve_report.sh` missed a stale server on port
  8765, and on Windows a second listener could bind beside it. The script then printed
  `HTML_REPORT:` while another directory answered the URL (#6). A socket probe now detects
  a busy port. A holder it can't identify is reused only if it already serves this report;
  otherwise the script fails with `ERROR:SERVE_PORT_BUSY`. `HTML_REPORT:` is printed only
  once the URL returns this exact file, otherwise `ERROR:SERVE_PORT_CONFLICT`. Taking over
  a server now needs an exact `--directory` match: the old substring match also killed
  servers for subdirectories. Serving takes about 0.3 s instead of at least 1 s. The serve
  tests use their own port (`VIDEO_LENS_PORT`) and no longer kill the user's server.
- Windows-style paths (backslashes, drive letter) produced a broken report URL (#4, fixed
  by #5 from an outside contributor). The drive letter is lowercased with `tr`, because
  macOS's bash 3.2 rejects `${var,,}`.
- The meta-line separator lost its trailing space, so the YouTube link ran into the `·`.
  The 5.2 fix for the dangling separator wrote it as `" \00b7 "`, and a CSS hex escape
  swallows the whitespace character that follows it.

### Added

- A "Revisions and follow-up questions" section: re-`Write` the payload and re-render,
  never edit the rendered HTML; answer questions from the transcript with timestamps.
- `install-skill-local` syncs `references/`.
- `test_skill_md_contract_matches_the_repo` checks that `Write` is allowed, every invoked
  script ships, the fallback reference exists and is deployed, and the Raycast tool list
  stays in sync with the Taskfile rewrite.
- A real-video test suite. `evals/fixtures.json` lists eight YouTube videos, one per branch.
  `task test-real` runs the fetch scripts against them with no LLM, and pins two live
  language-selection bugs as strict xfails. `task eval AGENT=claude|pi` runs an agent on
  them from an isolated copy of the skill and validates every report and tool trace
  (`evals/checks.py`). The agent's transcript and metadata fetches are recorded once per
  fixture and replayed after that (`evals/replay.py`), so both A/B arms read identical
  inputs and a full A/B doesn't get the IP blocked. `task eval-compare` A/Bs two runs, and
  `task eval-library` scores the saved library by model family.
- `task test`, `test-real` and `test-full` call `python3 -m pytest`, so they work when
  the `pytest` script is not on `PATH`.

## [5.2] — 2026-08-22

_video-lens-gallery 2.1._ Findings from a comprehensive skill assessment.

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
