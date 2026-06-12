"""Tests for the local Whisper transcription fallback.

Unit tests cover language normalization, model mapping, and the
YTDLP_LANGUAGE detection in fetch_metadata.py. Structured-error tests run
transcribe_local.py as a subprocess with stubbed/missing dependencies and
assert the exact ERROR: prefixes that SKILL.md's error table routes on.
The end-to-end transcription test skips on machines without
mlx-whisper/ffmpeg.
"""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "skills" / "video-lens" / "scripts"
TRANSCRIBE = SCRIPT_DIR / "transcribe_local.py"

sys.path.insert(0, str(SCRIPT_DIR))
from fetch_metadata import _detect_language  # noqa: E402
from transcribe_local import MODEL_REPOS, normalize_language  # noqa: E402

# "What are skills?" (2 min) — same short, stable video as test_e2e.py
VIDEO_ID = "bjdBVZa66oU"


# ---------- language normalization ----------

@pytest.mark.parametrize("raw,expected", [
    ("en-US", "en"),
    ("pt_BR", "pt"),
    ("EN", "en"),
    ("de", "de"),
    ("", ""),
    (None, ""),
])
def test_normalize_language(raw, expected):
    assert normalize_language(raw) == expected


# ---------- model mapping ----------

def test_model_repos_cover_documented_sizes():
    assert set(MODEL_REPOS) == {"tiny", "small", "medium", "large-v3"}
    for size, repo in MODEL_REPOS.items():
        assert repo == f"mlx-community/whisper-{size}-mlx"


def test_unknown_model_size_rejected():
    result = subprocess.run(
        [sys.executable, str(TRANSCRIBE), VIDEO_ID, "--model", "gigantic"],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert result.stdout.startswith("ERROR:INVALID_INPUT")


# ---------- fetch_metadata YTDLP_LANGUAGE ----------

def test_detect_language_normalizes_top_level():
    assert _detect_language({"language": "en-US"}) == "en"


def test_detect_language_falls_back_to_formats_skipping_und():
    data = {
        "language": None,
        "formats": [
            {"language": None},
            {"language": "und"},
            {"language": "pt-BR"},
        ],
    }
    assert _detect_language(data) == "pt"


def test_detect_language_empty_when_unknown():
    assert _detect_language({}) == ""
    assert _detect_language({"formats": [{"language": "und"}]}) == ""


def test_detect_language_prefers_original_track_over_dub():
    """Multi-audio videos: language_preference 10 marks the original audio."""
    data = {
        "formats": [
            {"language": "en", "language_preference": -10},
            {"language": "fr", "language_preference": 10},
            {"language": "es", "language_preference": -10},
        ],
    }
    assert _detect_language(data) == "fr"


def test_detect_language_top_level_wins_over_formats():
    data = {
        "language": "de",
        "formats": [{"language": "en", "language_preference": 10}],
    }
    assert _detect_language(data) == "de"


# ---------- structured-error paths (SKILL.md contract) ----------

def test_whisper_missing_error(tmp_path):
    """With mlx_whisper unimportable, the script prints ERROR:WHISPER_MISSING."""
    stub = tmp_path / "mlx_whisper.py"
    stub.write_text("raise ImportError('stubbed out for test')\n")
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, str(TRANSCRIBE), VIDEO_ID],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 1
    assert result.stdout.startswith("ERROR:WHISPER_MISSING: pip install mlx-whisper")


def test_ffmpeg_missing_error(tmp_path):
    """With mlx_whisper importable but ffmpeg absent from PATH: ERROR:FFMPEG_MISSING."""
    stub = tmp_path / "mlx_whisper.py"
    stub.write_text("def transcribe(*a, **k):\n    raise RuntimeError('stub')\n")
    empty_path = tmp_path / "bin"
    empty_path.mkdir()
    env = {**os.environ, "PYTHONPATH": str(tmp_path), "PATH": str(empty_path)}
    result = subprocess.run(
        [sys.executable, str(TRANSCRIBE), VIDEO_ID],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 1
    assert result.stdout.startswith("ERROR:FFMPEG_MISSING: brew install ffmpeg")


def test_ytdlp_missing_is_fatal_download_error(tmp_path):
    """yt-dlp absent must NOT emit ERROR:YTDLP_MISSING — SKILL.md routes
    ERROR:YTDLP_* as non-fatal metadata errors, but here it is fatal."""
    stub = tmp_path / "mlx_whisper.py"
    stub.write_text("def transcribe(*a, **k):\n    raise RuntimeError('stub')\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ffmpeg = fake_bin / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\nexit 0\n")
    ffmpeg.chmod(0o755)
    env = {**os.environ, "PYTHONPATH": str(tmp_path), "PATH": str(fake_bin)}
    result = subprocess.run(
        [sys.executable, str(TRANSCRIBE), VIDEO_ID],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 1
    assert result.stdout.startswith("ERROR:AUDIO_DOWNLOAD_FAILED: yt-dlp not installed")
    assert "ERROR:YTDLP_MISSING" not in result.stdout


def test_leading_dash_video_id_accepted_with_separator(tmp_path):
    """SKILL.md invokes scripts with `--` before the ID; an ID starting with
    `-` must reach the dependency checks instead of dying in argparse."""
    stub = tmp_path / "mlx_whisper.py"
    stub.write_text("raise ImportError('stubbed out for test')\n")
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, str(TRANSCRIBE), "--model", "tiny", "--", "-Abc123XYZ_w"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 1
    assert result.stdout.startswith("ERROR:WHISPER_MISSING")


def test_audio_download_failed_error(tmp_path):
    """With all deps present but yt-dlp failing: ERROR:AUDIO_DOWNLOAD_FAILED."""
    stub = tmp_path / "mlx_whisper.py"
    stub.write_text("def transcribe(*a, **k):\n    raise RuntimeError('stub')\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for tool, body in [("ffmpeg", "exit 0"), ("yt-dlp", "echo 'ERROR: boom' >&2; exit 1")]:
        f = fake_bin / tool
        f.write_text(f"#!/bin/sh\n{body}\n")
        f.chmod(0o755)
    env = {**os.environ, "PYTHONPATH": str(tmp_path),
           "PATH": f"{fake_bin}:{os.environ['PATH']}"}
    result = subprocess.run(
        [sys.executable, str(TRANSCRIBE), VIDEO_ID],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 1
    assert result.stdout.startswith("ERROR:AUDIO_DOWNLOAD_FAILED: ERROR: boom")


# ---------- end-to-end (skips without mlx-whisper/ffmpeg) ----------

def _has_mlx_whisper():
    try:
        import mlx_whisper  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(
    not _has_mlx_whisper() or not shutil.which("ffmpeg") or not shutil.which("yt-dlp"),
    reason="requires mlx-whisper, ffmpeg, and yt-dlp",
)
def test_e2e_transcription_output_contract():
    """Output must parse like fetch_transcript.py output: headers + [M:SS] lines."""
    result = subprocess.run(
        [sys.executable, str(TRANSCRIBE), "--model", "tiny",
         "--language", "en-US", "--", VIDEO_ID],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    headers = dict(
        line.split(": ", 1) if ": " in line else (line.rstrip(":"), "")
        for line in lines[:8]
    )
    for key in ("TITLE", "CHANNEL", "PUBLISHED", "VIEWS", "DURATION",
                "DATE", "LANG", "SOURCE"):
        assert key in headers, f"missing header {key} in: {lines[:8]}"
    assert headers["LANG"] == "en"
    assert headers["SOURCE"] == "whisper-tiny-local"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", headers["DATE"])
    segment_lines = lines[8:]
    assert segment_lines, "no transcript segments emitted"
    ts = re.compile(r"^\[(\d+:)?\d{1,2}:\d{2}\] \S")
    assert all(ts.match(l) for l in segment_lines if l.strip()), segment_lines[:5]
