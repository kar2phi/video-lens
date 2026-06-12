# Whisper fallback integration plan — local transcription when captions are missing

**Date:** 2026-06-11
**Source reviewed:** `~/Library/Mobile Documents/com~apple~CloudDocs/Downloads/video-lens-changes/`
(CHANGES_REPORT.md, SKILL.md v4.0 snapshot, SKILL_repo_commit_diff.patch, 5 scripts)
**Goal:** when a YouTube video has no fetchable transcript, download the audio with yt-dlp and
transcribe it locally with Whisper — integrated **into the existing video-lens skill**, no
separate `video-transcribe` skill.

---

## 1. Review verdict on the delivered changes

### 1.1 Critical: the core capability was never delivered

The changed SKILL.md adds a "Step 2a fallback — local Whisper transcription" that shells out to
`transcribe.py` inside a `~/.{agent}/skills/video-transcribe/scripts/` directory. That script
exists **nowhere**: not in the changes folder, not installed on this machine, not in any repo.
Only the glue was delivered — error-table routing, a `YTDLP_LANGUAGE` hint, and prose describing
a script that has to be written from scratch. Section 3 below specs it.

This also resolves itself naturally with the decision to integrate rather than keep a separate
skill: the discovery loop over `~/.agents … ~/.codex` for `video-transcribe` is dropped entirely;
the script lives in video-lens's own `SCRIPTS_DIR`, which Step 1 already resolves.

### 1.2 What in the changes folder is actually new (vs this repo's working tree)

| Delta | Verdict |
|---|---|
| SKILL.md: error table splits `CAPTIONS_DISABLED`/`NO_TRANSCRIPT` into a fallback-offer row | **Adopt**, extended (see §2 decision 3) |
| SKILL.md: "Step 2a fallback" section | **Adopt rewritten** — bundled script, no skill discovery, background-execution guidance (§4.3) |
| SKILL.md: Step 2b bullet for `YTDLP_LANGUAGE` | **Adopt** with normalization caveat (§1.3) |
| SKILL.md: new "Quick reference" top section | **Adopt** — useful compaction-safety net; update to six scripts incl. the transcribe invocation |
| `fetch_metadata.py`: emit `YTDLP_LANGUAGE` | **Adopt** with BCP-47 → ISO-639-1 normalization (§4.2) |
| SKILL.md: "Common rejection causes" restructured into mixed prose | **Reject** — the repo's current bulleted version (edited 2026-06-08) is newer and clearer; the changes-folder version is a regression from an older snapshot |
| `serve_report.sh` | **Reject** — the changes-folder copy is **older** than the repo's: it is missing the port-takeover / `SERVE_PORT_BUSY` handling the repo added. Adopting it would silently regress commit-era fixes. Do not copy. |
| `AGENT_MODEL` example text (`qwen3-72b` → `qwen3.6`) | Cosmetic; skip |
| `preflight.py`, `fetch_transcript.py`, `render_report.py` | Byte-identical to this repo; nothing to do |
| `SKILL_repo_commit_diff.patch` | Historical diff of prompt-quality changes from an old `skill/` layout, all already present in this repo's v4.0. Irrelevant; discard. |

**General caution:** CHANGES_REPORT.md was generated on a different machine (`/Users/Q430426/…`)
against a repo clone that is ~3 commits old and uses the obsolete `skill/` layout. Its
"installed vs repo divergence" narrative does not apply to this repo, which already contains the
v4.0 SKILL.md and all five scripts under `skills/video-lens/`. Treat the folder as a snapshot to
cherry-pick from, never as a sync source.

### 1.3 Flaws and ambiguities in the proposed design (fixed in this plan)

1. **Missing script** — see §1.1.
2. **Fallback scope too narrow.** Only `CAPTIONS_DISABLED`/`NO_TRANSCRIPT` triggered the
   fallback. But `IP_BLOCKED`, `PO_TOKEN_REQUIRED`, and `REQUEST_BLOCKED` are
   transcript-*API* blocks where yt-dlp audio download usually still works — exactly the cases
   local transcription remedies. → Extended (decision in §2).
3. **`YTDLP_LANGUAGE` is unnormalized.** yt-dlp returns BCP-47 codes (`en-US`, `pt-BR`); Whisper
   expects ISO-639-1 (`en`, `pt`). The format-loop in the changed `fetch_metadata.py` also picks
   the first format's language in arbitrary order. → Normalize in the script (§4.2).
4. **Bash tool timeout.** Agent Bash calls default to 2 min and cap at 10 min. Even on
   mlx-whisper (~8–15× realtime on Apple Silicon GPU), a 2 h video can exceed the cap; on the
   originally implied CPU path it certainly would. The changed SKILL.md says nothing about this
   — a long transcription would be killed mid-run. → SKILL.md must instruct an explicit timeout
   and background execution for long videos (§4.3).
5. **First-run model download undisclosed.** The medium model is a ~1.5 GB download from
   Hugging Face on first use. The "Bundled scripts" section claims the only network calls are
   YouTube fetches — that statement becomes false and must be updated (§4.3). It is also a
   first-run latency surprise the user should be warned about when asked for consent.
6. **No metadata on the fallback path.** `fetch_transcript.py` prints its `TITLE:`/`CHANNEL:`/…
   header block only on *success*; on the error paths that trigger the fallback, nothing was
   printed. The new script must emit the full header block itself (§4.1).
7. **No provenance disclosure.** An ASR transcript has different error characteristics
   (misheard names, numbers, hallucinated text over music/silence). Reports should disclose it:
   append `· 🎙 transcribed locally` to `META_LINE` (§4.3).
8. **Audio file lifecycle unspecified.** Where the download lands and who deletes it was never
   stated. → Script downloads to its own temp dir and deletes it on success and on failure (§4.1).
9. **ffmpeg dependency unstated.** mlx-whisper requires the `ffmpeg` CLI for audio decoding; it
   is not installed on this machine. → New `ERROR:FFMPEG_MISSING` with install hint (§4.1);
   mention in SKILL.md frontmatter `compatibility:`.
10. **Quick reference drift.** "Five local scripts" becomes six; the invocation list must gain
    the transcribe call, or the compaction-safety net itself goes stale.

### 1.4 Explicitly out of scope (note, don't build)

- **Age-restricted videos** still stop hard. yt-dlp *can* sometimes fetch them with browser
  cookies, but that drags auth/cookie handling into the skill — separate decision if wanted.
- **Shorts** remain unsupported (preflight rejects them before any of this runs).
- **Speaker diarization** — Whisper alone doesn't label speakers; interview transcripts will be
  one undifferentiated stream. Acceptable for summarisation.
- **Whisper hallucination mitigation** beyond defaults — the script should pass
  `condition_on_previous_text=False` (cheap, reduces repetition loops) but no VAD pipeline.

---

## 2. Decisions taken (with karphi, 2026-06-11)

1. **Backend: `mlx-whisper`.** Apple-Silicon GPU via MLX, ~8–15× realtime on the medium model.
   Deps: `pip install mlx-whisper`, `brew install ffmpeg`. macOS/Apple-Silicon only — if the
   skill is ever run on Linux/Intel, the script fails with a clear `ERROR:WHISPER_MISSING`
   message naming the requirement; no secondary backend is maintained.
2. **UX: ask first.** On a fallback-eligible error, report it, estimate the transcription time
   from the video duration (known from Step 2b), warn about the one-time ~1.5 GB model download
   if relevant, and proceed only on user consent. If the user *already* asked for local
   transcription in their prompt, skip the question.
3. **Scope: include blocked-API errors.** Fallback is offered on `CAPTIONS_DISABLED`,
   `NO_TRANSCRIPT`, `IP_BLOCKED`, `PO_TOKEN_REQUIRED`, and on `REQUEST_BLOCKED` *after* its
   existing retry-once also fails.
4. **Default model: `medium`** (per the original changes). User may say "small" (faster) or
   "large-v3" (best non-English accuracy); SKILL.md documents the mapping.

---

## 3. New script: `skills/video-lens/scripts/transcribe_local.py`

```
Usage: python3 transcribe_local.py VIDEO_ID [--language LANG] [--model SIZE]
```

### Behaviour

1. **Dependency checks first, fail fast with structured errors:**
   - `import mlx_whisper` → on ImportError: `ERROR:WHISPER_MISSING: pip install mlx-whisper` , exit 1
   - `shutil.which("ffmpeg")` → `ERROR:FFMPEG_MISSING: brew install ffmpeg`, exit 1
   - `shutil.which("yt-dlp")` → `ERROR:YTDLP_MISSING: brew install yt-dlp`, exit 1
2. **Download audio** with yt-dlp into a `tempfile.mkdtemp()` dir:
   `yt-dlp -f "bestaudio[ext=m4a]/bestaudio" -o "<tmp>/audio.%(ext)s" -- <VIDEO_ID>`
   (note `--` before the ID — IDs can start with `-`). On non-zero exit:
   `ERROR:AUDIO_DOWNLOAD_FAILED: <last stderr line>`, exit 1. The temp dir is removed in a
   `finally:` block — success *and* failure.
3. **Model mapping** (`--model` → HF repo):
   `tiny|small|medium|large-v3` → `mlx-community/whisper-{size}-mlx`
   (medium default; reject unknown sizes with `ERROR:INVALID_INPUT`).
4. **Language normalization:** take `--language` if given, lowercase, split on `-`/`_`, keep the
   primary subtag (`en-US` → `en`). Pass to `mlx_whisper.transcribe(..., language=...)`; omit
   entirely when empty so Whisper auto-detects.
5. **Transcribe:** `mlx_whisper.transcribe(audio_path, path_or_hf_repo=repo, language=lang or None, condition_on_previous_text=False)`.
   On exception: `ERROR:TRANSCRIBE_FAILED: <type>: <msg>`, exit 1.
6. **Output — byte-compatible with `fetch_transcript.py`** so Steps 3–6 need zero changes:
   - Reuse the HTML metadata scrape: `from fetch_transcript import _fetch_html_metadata`
     (same directory; guard with try/except and empty-string fallbacks).
   - Header block: `TITLE:`, `CHANNEL:`, `PUBLISHED:`, `VIEWS:`, `DURATION:`,
     `DATE: <today ISO>`, `LANG: <result["language"]>`, plus one extra informational line
     `SOURCE: whisper-<size>-local`.
   - Then one line per Whisper segment: `[M:SS] text` / `[H:MM:SS] text`, same formatting code
     as `fetch_transcript.py` (int seconds from `segment["start"]`).

### Why these choices

- Identical output contract means the SKILL.md instruction "use it as the transcript for
  Steps 3–6 without modification" is literally true — outline timestamps, `LANG:`-driven
  language fidelity, and `DATE:` for `GENERATION_DATE` all keep working.
- Importing `_fetch_html_metadata` instead of duplicating it keeps one scrape implementation.
- `condition_on_previous_text=False` is the single cheapest guard against Whisper's repetition
  loops on long/quiet audio.

---

## 4. File-by-file changes

### 4.1 `skills/video-lens/scripts/transcribe_local.py` — **new** (spec in §3)

### 4.2 `skills/video-lens/scripts/fetch_metadata.py`

Adopt the changes-folder addition, plus normalization, after the `YTDLP_CHAPTERS` print:

```python
def _primary_lang(code):
    return (code or "").split("-")[0].split("_")[0].lower()

lang = _primary_lang(data.get("language"))
if not lang:
    for fmt in (data.get("formats") or []):
        fl = _primary_lang(fmt.get("language"))
        if fl and fl != "und":
            lang = fl
            break
print(f"YTDLP_LANGUAGE: {lang}")
```

### 4.3 `skills/video-lens/SKILL.md`

All edits are against the **current repo working tree** (which is ahead of the changes-folder
snapshot in places — do not paste from the snapshot wholesale).

1. **Frontmatter `compatibility:`** — append: "Local transcription fallback (videos without
   captions) additionally requires mlx-whisper, ffmpeg, and yt-dlp (Apple Silicon only)."
   `description:` — append a clause like "Falls back to local Whisper transcription when a video
   has no captions."
2. **Quick reference** (new section from the snapshot) — adopt, with the script list extended:
   `python3 .../transcribe_local.py <VIDEO_ID> [--language L] [--model M]`.
3. **Bundled scripts** — "Six local scripts … `transcribe_local.py` …". Update the network
   statement: add "When the local-transcription fallback runs: audio download from YouTube via
   yt-dlp, and a one-time Whisper model download (~1.5 GB for medium) from Hugging Face."
4. **Step 2b** — adopt the `YTDLP_LANGUAGE` bullet (wording: "primary language subtag, already
   normalized, e.g. `en`").
5. **Error Handling table** — replace the single stop-row split as follows:
   - `ERROR:CAPTIONS_DISABLED`, `ERROR:NO_TRANSCRIPT`, `ERROR:IP_BLOCKED`,
     `ERROR:PO_TOKEN_REQUIRED` → "Report the message, then offer the local Whisper fallback
     (see **Step 2a fallback**). Proceed only if the user agrees or already asked for local
     transcription; otherwise stop."
   - `ERROR:REQUEST_BLOCKED`, `ERROR:NETWORK_ERROR` → keep retry-once; if `REQUEST_BLOCKED`
     persists, offer the fallback instead of stopping.
   - `ERROR:VIDEO_UNAVAILABLE`, `ERROR:AGE_RESTRICTED`, `ERROR:INVALID_VIDEO_ID`,
     `ERROR:LIBRARY_MISSING` → unchanged: report and stop.
   - New row: `ERROR:WHISPER_MISSING`, `ERROR:FFMPEG_MISSING`, `ERROR:AUDIO_DOWNLOAD_FAILED`,
     `ERROR:TRANSCRIBE_FAILED` → "Report code + message (include the install hint). Stop."
6. **New section "Step 2a fallback — local Whisper transcription"** (replaces the snapshot's
   skill-discovery version):
   - Invocation: `python3 "SCRIPTS_DIR/transcribe_local.py" "VIDEO_ID" --model medium` — same
     `SCRIPTS_DIR` literal from Step 1, no discovery loop.
   - Language: `--language LANG_CODE` when Step 1 gave a hint; else `--language YTDLP_LANGUAGE`
     when Step 2b returned one; else omit (Whisper auto-detects). Wait for 2b before invoking.
   - **Consent step:** before running, tell the user transcription will run locally, estimate
     duration from `YTDLP_DURATION` ("a 1 h video takes roughly 4–8 min on this machine"), and
     note the one-time model download. Skip the question if the user already requested it.
   - **Timeouts:** invoke with an explicit 600000 ms timeout. For videos longer than ~90 min,
     run in the background and poll, since transcription may exceed the 10-minute Bash cap.
   - Output is `fetch_transcript.py`-compatible; `SOURCE:` line is informational.
   - **Provenance:** when the fallback produced the transcript, append `· 🎙 transcribed
     locally` to `META_LINE` (compose it explicitly in the Step 4 payload, like the existing
     `LANG_WARN` case).
   - Model sizes: default `medium`; `small` faster/less accurate; `large-v3` best for
     non-English.

### 4.4 `requirements.txt`

Add a commented optional block (don't make the whole skill require torch-free-but-large deps):

```
# Optional — local transcription fallback (Apple Silicon):
# mlx-whisper>=0.4
```

…and mention `brew install ffmpeg` in README/SKILL compatibility rather than requirements.

### 4.5 Tests (`tests/test_e2e.py` or a new `tests/test_transcribe.py`)

- Unit: language normalization (`en-US`→`en`, `pt_BR`→`pt`, empty→empty), model-size→repo
  mapping, unknown size rejected.
- Unit: `fetch_metadata.py` emits normalized `YTDLP_LANGUAGE` (feed a fake info dict through the
  helper).
- Structured-error paths: run the script with mlx_whisper import stubbed out / PATH stripped and
  assert `ERROR:WHISPER_MISSING` / `ERROR:FFMPEG_MISSING` exact prefixes (the SKILL contract).
- E2E transcription test marked `@pytest.mark.skipif` on missing mlx_whisper/ffmpeg/network —
  use a known very short video (< 1 min).

### 4.6 No changes needed

- `Taskfile.yml` / install flow — `install-skill-local` copies the whole skill dir; the new
  script rides along.
- `preflight.py`, `render_report.py`, `template.html`, gallery — untouched; provenance flows
  through `META_LINE`.
- `serve_report.sh` — **keep the repo version**; explicitly do not copy from the changes folder.

---

## 5. Acceptance checklist

- [ ] `transcribe_local.py` exists, executable spec per §3; temp audio removed on success and failure.
- [ ] Output of `transcribe_local.py` on a captionless test video parses identically to
      `fetch_transcript.py` output (headers + `[M:SS]` lines) and Steps 3–6 complete unmodified.
- [ ] `fetch_metadata.py` prints normalized `YTDLP_LANGUAGE` (verify against an `en-US` video).
- [ ] SKILL.md: quick-ref lists six scripts; error table routes the five fallback-eligible codes;
      consent + timeout + provenance instructions present; no reference to `video-transcribe`
      anywhere.
- [ ] Missing-dep errors print exact codes with install hints (`pip install mlx-whisper`,
      `brew install ffmpeg`).
- [ ] Report generated via fallback shows `🎙 transcribed locally` in its meta line and appears
      in the gallery index normally.
- [ ] `pytest` green; new tests skip cleanly on machines without mlx-whisper.
- [ ] Deploy: `task install-skill-local AGENT=claude` after merging (repo is source of truth —
      do not edit `~/.agents/skills/` directly).
