#!/usr/bin/env python3
"""Local Whisper transcription fallback for videos without fetchable captions.

Downloads the audio with yt-dlp and transcribes it with mlx-whisper
(Apple Silicon GPU). Output is byte-compatible with fetch_transcript.py
so downstream steps need no changes.

Usage: python3 transcribe_local.py VIDEO_ID [--language LANG] [--model SIZE]
                                            [--audio-file PATH]

--audio-file skips the yt-dlp download and transcribes a file the user already
has, for when YouTube blocks the download outright. VIDEO_ID stays required:
the header block is still built from the video's public metadata.
"""
import argparse
import datetime
import pathlib
import shutil
import subprocess
import sys
import tempfile

# Below this, yt-dlp resolves media through YouTube's android_vr client, and YouTube
# serves only the first ~1 MiB from those URLs — every byte past it 403s. Used solely
# to turn an opaque "HTTP Error 403" into an actionable hint; never enforced up front,
# since a newer client-side workaround may land before the version number moves.
DOWNLOAD_TIMEOUT_SECONDS = 900  # total wall clock for the audio fetch
MIN_YTDLP = (2026, 8, 19)
MIN_YTDLP_LABEL = "2026.08.19"

MODEL_REPOS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
}


def normalize_language(code):
    """BCP-47 / locale code → primary ISO-639-1 subtag (en-US → en)."""
    return (code or "").split("-")[0].split("_")[0].lower().strip()


def model_repo(size):
    repo = MODEL_REPOS.get(size)
    if repo is None:
        print(f"ERROR:INVALID_INPUT: unknown model size {size!r} — use one of: {', '.join(MODEL_REPOS)}")
        sys.exit(1)
    return repo


def _format_timestamp(seconds):
    total_s = int(seconds)
    h, rem = divmod(total_s, 3600)
    m2, s2 = divmod(rem, 60)
    return f"[{h}:{m2:02d}:{s2:02d}]" if h > 0 else f"[{m2}:{s2:02d}]"


def _ytdlp_version():
    """Installed yt-dlp as (comparable tuple, string as yt-dlp reports it), or None.

    The raw string is kept so the hint echoes back exactly what `yt-dlp --version`
    prints (`2026.03.17`), which the user can match against their own terminal.
    """
    try:
        out = subprocess.run(
            ["yt-dlp", "--no-update", "--version"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return tuple(int(part) for part in out.split(".")[:3]), out
    except ValueError:
        return None


def _stale_ytdlp_hint(stderr):
    """Actionable suffix when a download failure looks like the stale-yt-dlp 403.

    A five-month-old yt-dlp surfaces this as a bare "HTTP Error 403: Forbidden",
    which reads like an IP ban or a dead URL and sends you down the wrong path.
    Only consulted after a failure, so the happy path pays nothing for it.
    """
    found = _ytdlp_version()
    if found is None or found[0] >= MIN_YTDLP:
        return ""
    if "403" not in stderr and "Forbidden" not in stderr:
        return ""
    return (f" (yt-dlp {found[1]} is older than {MIN_YTDLP_LABEL} and YouTube now blocks its"
            f" downloads — run: brew upgrade yt-dlp, or pip install -U yt-dlp)")


def _pick_audio_file(tmp_dir):
    """Largest complete file yt-dlp left behind.

    Not simply the first name alphabetically: a partial `audio.m4a.part` from an
    interrupted transfer sorts before the real `audio.m4a` and would be fed to
    Whisper as if it were the whole thing.
    """
    files = [f for f in pathlib.Path(tmp_dir).iterdir()
             if f.is_file() and f.suffix != ".part"]
    if not files:
        return None
    return str(max(files, key=lambda f: f.stat().st_size))


def _download_audio(video_id, tmp_dir):
    # --socket-timeout bounds individual reads, not total runtime: a throttled
    # transfer otherwise runs until the agent's own 600 s Bash cap kills the whole
    # step, burning the transcription budget and returning no structured error.
    try:
        result = subprocess.run(
            ["yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio",
             "--socket-timeout", "30",
             "-o", f"{tmp_dir}/audio.%(ext)s", "--", video_id],
            capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        print(f"ERROR:AUDIO_DOWNLOAD_FAILED: download timed out after "
              f"{DOWNLOAD_TIMEOUT_SECONDS}s")
        sys.exit(1)
    if result.returncode != 0:
        stderr_lines = [l for l in result.stderr.strip().splitlines() if l.strip()]
        hint = stderr_lines[-1] if stderr_lines else "no error output"
        print(f"ERROR:AUDIO_DOWNLOAD_FAILED: {hint}{_stale_ytdlp_hint(result.stderr)}")
        sys.exit(1)
    audio_path = _pick_audio_file(tmp_dir)
    if audio_path is None:
        print("ERROR:AUDIO_DOWNLOAD_FAILED: yt-dlp exited 0 but produced no file")
        sys.exit(1)
    return audio_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video_id")
    parser.add_argument("--language", default="")
    parser.add_argument("--model", default="medium")
    parser.add_argument("--audio-file", default="",
                        help="transcribe this local file instead of downloading from YouTube")
    args = parser.parse_args()

    repo = model_repo(args.model)
    lang = normalize_language(args.language)
    supplied_audio = args.audio_file.strip()

    try:
        import mlx_whisper
    except ImportError:
        print("ERROR:WHISPER_MISSING: pip install mlx-whisper")
        sys.exit(1)
    if shutil.which("ffmpeg") is None:
        print("ERROR:FFMPEG_MISSING: brew install ffmpeg")
        sys.exit(1)
    if supplied_audio:
        if not pathlib.Path(supplied_audio).expanduser().is_file():
            print(f"ERROR:INVALID_INPUT: audio file not found: {supplied_audio}")
            sys.exit(1)
    elif shutil.which("yt-dlp") is None:
        # Not ERROR:YTDLP_MISSING — SKILL.md routes ERROR:YTDLP_* as non-fatal
        # (metadata-only), but here yt-dlp is required to get the audio.
        print("ERROR:AUDIO_DOWNLOAD_FAILED: yt-dlp not installed — brew install yt-dlp or pip install yt-dlp")
        sys.exit(1)

    # Only a directory we created ourselves is ever deleted; a user-supplied file
    # must survive the run.
    tmp_dir = None if supplied_audio else tempfile.mkdtemp(prefix="video-lens-audio-")
    try:
        audio_path = (str(pathlib.Path(supplied_audio).expanduser())
                      if supplied_audio else _download_audio(args.video_id, tmp_dir))

        try:
            result = mlx_whisper.transcribe(
                audio_path,
                path_or_hf_repo=repo,
                language=lang or None,
                condition_on_previous_text=False,
                # Pin verbosity: with the default (verbose=None) Whisper prints a
                # tqdm bar to stderr; verbose=True would dump decoded segments to
                # stdout and corrupt the transcript block we print below. Keep
                # stdout exclusively ours so the fetch_transcript.py contract holds.
                verbose=False,
            )
        except Exception as e:
            print(f"ERROR:TRANSCRIBE_FAILED: {type(e).__name__}: {e}")
            sys.exit(1)
    finally:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    try:
        from fetch_transcript import _fetch_html_metadata
        title, channel, published, views, duration = _fetch_html_metadata(args.video_id)
    except Exception:
        title = channel = published = views = duration = ""
    if not title:
        title = f"YouTube video {args.video_id}"

    lines = [
        f"TITLE: {title}",
        f"CHANNEL: {channel}",
        f"PUBLISHED: {published}",
        f"VIEWS: {views}",
        f"DURATION: {duration}",
        f"DATE: {datetime.date.today().isoformat()}",
        f"LANG: {result.get('language') or lang}",
        f"SOURCE: whisper-{args.model}-local-file" if supplied_audio
        else f"SOURCE: whisper-{args.model}-local",
    ]
    for segment in result.get("segments") or []:
        text = segment["text"].strip()
        if not text:
            continue
        lines.append(f"{_format_timestamp(segment['start'])} {text}")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
