#!/usr/bin/env python3
"""Local Whisper transcription fallback for videos without fetchable captions.

Downloads the audio with yt-dlp and transcribes it with mlx-whisper
(Apple Silicon GPU). Output is byte-compatible with fetch_transcript.py
so downstream steps need no changes.

Usage: python3 transcribe_local.py VIDEO_ID [--language LANG] [--model SIZE]
"""
import argparse
import datetime
import pathlib
import shutil
import subprocess
import sys
import tempfile

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


def _download_audio(video_id, tmp_dir):
    result = subprocess.run(
        ["yt-dlp", "-f", "bestaudio[ext=m4a]/bestaudio",
         "--socket-timeout", "30",
         "-o", f"{tmp_dir}/audio.%(ext)s", "--", video_id],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        stderr_lines = [l for l in result.stderr.strip().splitlines() if l.strip()]
        hint = stderr_lines[-1] if stderr_lines else "no error output"
        print(f"ERROR:AUDIO_DOWNLOAD_FAILED: {hint}")
        sys.exit(1)
    files = sorted(p for p in pathlib.Path(tmp_dir).iterdir() if p.is_file())
    if not files:
        print("ERROR:AUDIO_DOWNLOAD_FAILED: yt-dlp exited 0 but produced no file")
        sys.exit(1)
    return str(files[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video_id")
    parser.add_argument("--language", default="")
    parser.add_argument("--model", default="medium")
    args = parser.parse_args()

    repo = model_repo(args.model)
    lang = normalize_language(args.language)

    try:
        import mlx_whisper
    except ImportError:
        print("ERROR:WHISPER_MISSING: pip install mlx-whisper")
        sys.exit(1)
    if shutil.which("ffmpeg") is None:
        print("ERROR:FFMPEG_MISSING: brew install ffmpeg")
        sys.exit(1)
    if shutil.which("yt-dlp") is None:
        # Not ERROR:YTDLP_MISSING — SKILL.md routes ERROR:YTDLP_* as non-fatal
        # (metadata-only), but here yt-dlp is required to get the audio.
        print("ERROR:AUDIO_DOWNLOAD_FAILED: yt-dlp not installed — brew install yt-dlp or pip install yt-dlp")
        sys.exit(1)

    tmp_dir = tempfile.mkdtemp(prefix="video-lens-audio-")
    try:
        audio_path = _download_audio(args.video_id, tmp_dir)

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
        f"SOURCE: whisper-{args.model}-local",
    ]
    for segment in result.get("segments") or []:
        text = segment["text"].strip()
        if not text:
            continue
        lines.append(f"{_format_timestamp(segment['start'])} {text}")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
