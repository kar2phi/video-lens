# Local transcription fallback (Whisper)

Read this only after the user agreed to local transcription (SKILL.md, **Local transcription
fallback**). yt-dlp downloads the audio and mlx-whisper transcribes it on the Apple Silicon GPU.

Wait for 2b's output before running — it supplies `YTDLP_DURATION` and `YTDLP_LANGUAGE`. Then:

```bash
python3 "SCRIPTS_DIR/transcribe_local.py" --model medium -- "VIDEO_ID"
```

- **Language:** `--language` declares what language the **audio is** — it is not a transcript-language choice. Pass `--language YTDLP_LANGUAGE` when 2b returned a non-empty value; otherwise omit the flag and Whisper auto-detects. Never pass Step 1's `LANG_CODE` here: that is the language the user *requested*, and forcing Whisper to a language the audio is not in produces garbage. The fallback cannot honor a transcript-language request — if Step 1 had a language hint and the output's `LANG:` differs from it, also add the ` · ⚠ Requested language not available` suffix to `META_LINE` (alongside the provenance suffix below).
- **Model sizes:** default `medium`; `small` is faster but less accurate; `large-v3` gives the best non-English accuracy. Use a non-default size only when the user asks for it.
- **Timeouts:** invoke with an explicit 600000 ms timeout. Transcription runs at roughly 4–8 min per hour of video and a first run adds the model download — both count against the 10-minute Bash cap. For videos longer than ~60 min, or any first run where the model must still download, run the command in the background and poll until it finishes.
- **Output** is `fetch_transcript.py`-compatible (same header block and `[M:SS] text` lines) — use it as the transcript for Steps 3–6 without modification. The extra `SOURCE:` line is informational.
- **Provenance:** set `META_LINE` explicitly in the Step 4 payload with the ` · 🎙 transcribed locally` suffix: `<channel> · <duration> · <published> · <views> · 🎙 transcribed locally`.
- **When the download itself is blocked:** if the script returns `ERROR:AUDIO_DOWNLOAD_FAILED`, first check the hint in the message — a yt-dlp older than 2026.8.19 cannot download YouTube audio at all, and `brew upgrade yt-dlp` fixes it. If the download is still blocked after updating, the user can supply the audio themselves:
  ```bash
  python3 "SCRIPTS_DIR/transcribe_local.py" --model medium --audio-file "/path/to/audio.m4a" -- "VIDEO_ID"
  ```
  `VIDEO_ID` is still required (metadata for the header comes from it), any ffmpeg-readable audio or video file works, and the file is left in place. Offer this only after the update hint has been tried — never download on the user's behalf from a third-party site.
- Any `ERROR:` line from the script follows the **Error Handling** table in SKILL.md.
