# video-lens — first-run setup

Read this when preflight prints `SETUP_NEEDED:`, a script prints `ERROR:LIBRARY_MISSING`,
`ERROR:YTDLP_MISSING` or `ERROR:WHISPER_MISSING`, or the user asks to install or update
video-lens's packages (§1–§4), or when preflight prints `SKILL_OUTDATED:` (§5). `SETUP` below means `python3 "SCRIPTS_DIR/setup.py"`, with
`SCRIPTS_DIR` from preflight.

`setup.py` installs into video-lens's own Python environment,
`~/.local/share/video-lens/venv`. It never touches the system Python, never runs `brew`,
`apt` or `sudo`, and deleting that folder undoes it. The scripts find the environment on
their own; nothing needs activating.

## 1. Ask once

Say what is missing, why, and the exact command, in one short message, then ask one
question. Name only what the `SETUP_NEEDED:` line (or the error) lists:

- `transcript-api`: youtube-transcript-api, which every report needs to read the captions.
- `yt-dlp`: optional; adds chapters, the video description and richer metadata.

For example, when the line reads `SETUP_NEEDED: transcript-api, yt-dlp`:

> video-lens needs one Python package to read captions: youtube-transcript-api. It goes into
> video-lens's own folder (`~/.local/share/video-lens/venv`), not your system Python:
> `python3 ".../setup.py" transcript-api`
> Install it now? I can add yt-dlp too, for chapters and richer metadata.

Wait for the answer. Do not install anything without a yes, and do not ask again in the
same conversation once the user said no.

## 2. Run it

- Yes to both: `SETUP transcript-api yt-dlp`
- Yes, without yt-dlp: `SETUP transcript-api`
- Only yt-dlp (after `ERROR:YTDLP_MISSING`): `SETUP yt-dlp`
- mlx-whisper (only after the user accepted the local transcription fallback and
  `transcribe_local.py` printed `ERROR:WHISPER_MISSING`): `SETUP mlx-whisper`

It takes up to a minute and prints `SETUP_OK: <package>==<version>, …`. Tell the user in one
line what was installed, then **carry on with the same video**: run Step 1 (preflight) again
and continue from there. The user should not have to repeat the request.

## 3. If it fails

- `ERROR:SETUP_VENV_FAILED`: Python could not make the environment. Relay the message; it
  names the fix (on Debian or Ubuntu, `sudo apt install python3.X-venv`). Stop; the user runs
  that and asks again.
- `ERROR:SETUP_INSTALL_FAILED`: pip failed, usually no network or a proxy. Relay the last
  lines and stop.
- `ERROR:SETUP_PLATFORM`: mlx-whisper needs an Apple Silicon Mac. Stop.
- The user declines: print the command so they can run it later, and stop. A missing
  transcript library means no report.

`ffmpeg` (for the local Whisper fallback) and `deno` (some yt-dlp edge cases) are not Python
packages. Suggest `brew install ffmpeg` / `sudo apt install ffmpeg`; never run them yourself.

## 4. Updating

YouTube breaks older releases of youtube-transcript-api and yt-dlp a few times a year. When
preflight prints `LIBRARY_OUTDATED:`, or a transcript fetch fails with
`ERROR:TRANSCRIPT_FETCH_FAILED` or a request error that persists, offer:
`SETUP --upgrade transcript-api` (add `yt-dlp` when yt-dlp lives in the same folder, which
`SETUP_OK` showed earlier). Ask first, as above. If the old library sits in the system Python
instead, the upgrade still works: the scripts prefer video-lens's own folder once it holds the
package.

## 5. Updating video-lens

Read this when preflight prints `SKILL_OUTDATED:` (a newer video-lens is out), after the
report, or when the user asks to update the skills. The line ends in `via npx` or `via manual`:

- `via npx`: offer `npx skills update video-lens video-lens-gallery video-lens-recs` (if the
  CLI rejects the names, plain `npx skills update`). Ask first, as in §1, and run it only on a
  yes.
- `via manual`: run nothing. Tell the user how: from a clone, `git pull` and then
  `task install-skill-local AGENT=<agent>` again; otherwise reinstall with
  `npx skills add kar2phi/video-lens`.

After an update, the instructions loaded in this session are still the old ones: say a new
session picks up the new version. Do not rerun the report.

The check runs at most once a day and can be turned off with
`VIDEO_LENS_NO_UPDATE_CHECK=1` in the shell profile. Tell the user so if they ask; never set
it without being asked.
