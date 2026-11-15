#!/usr/bin/env python3
"""First-run setup: install video-lens's Python packages into its own venv.

Usage: python3 setup.py [--upgrade] PACKAGE [PACKAGE ...]

PACKAGE is one of:
    transcript-api   youtube-transcript-api, needed for every report
    yt-dlp           chapters, description and richer metadata; recs; Whisper audio
    mlx-whisper      the no-captions fallback (Apple Silicon only)

The venv is `$XDG_DATA_HOME/video-lens/venv` (default ~/.local/share/video-lens/venv;
VIDEO_LENS_VENV overrides it), made with the stdlib `python3 -m venv`, so no uv, pipx or
--break-system-packages is needed. Nothing outside that folder is touched; delete it to
undo. The scripts find it on their own (venv_env.py). Never runs brew, apt or sudo.

--upgrade also upgrades packages that are already there (the fix when YouTube breaks
an older youtube-transcript-api or yt-dlp).

Stdout on success:
    SETUP_OK: <package>==<version>, …
    VENV: <absolute path>
Stdout + exit 1 on failure:
    ERROR:SETUP_UNKNOWN_PACKAGE <name>
    ERROR:SETUP_PLATFORM <reason>
    ERROR:SETUP_VENV_FAILED <reason and the fix>
    ERROR:SETUP_INSTALL_FAILED <last lines of pip's output>
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
import pathlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from venv_env import venv_dir, venv_python  # noqa: E402

# Lower bounds, not pins: pip takes the newest release that satisfies them.
PACKAGES = {
    "transcript-api": "youtube-transcript-api>=1.2.4",
    # 2026.8.19+: older builds can no longer download YouTube audio (transcribe_local.py).
    "yt-dlp": "yt-dlp>=2026.8.19",
    "mlx-whisper": "mlx-whisper>=0.4",
}
INSTALL_TIMEOUT_SECONDS = 900


def _fail(code: str, msg: str) -> int:
    print(f"ERROR:{code} {msg}")
    return 1


def _venv_hint() -> str:
    if sys.platform.startswith("linux") and shutil.which("apt-get"):
        v = f"{sys.version_info.major}.{sys.version_info.minor}"
        return f"on Debian/Ubuntu install the venv module first: sudo apt install python{v}-venv"
    return "install a Python 3.10+ that includes the venv module (e.g. brew install python)"


def ensure_venv(venv: pathlib.Path) -> str | None:
    """Create the venv when missing. Returns an error message, or None."""
    py = venv_python(venv)
    if py.exists():
        return None
    if venv.exists():
        # A half-made venv (interrupted run, missing ensurepip) is rebuilt from scratch.
        shutil.rmtree(venv, ignore_errors=True)
    venv.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, "-m", "venv", str(venv)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not py.exists():
        shutil.rmtree(venv, ignore_errors=True)
        detail = (r.stderr or r.stdout).strip().splitlines()[-1:] or ["venv was not created"]
        return f"{detail[0]} — {_venv_hint()}"
    return None


def installed_versions(py: pathlib.Path, dists: list[str]) -> list[str]:
    code = ("import importlib.metadata as m, sys\n"
            "for d in sys.argv[1:]:\n"
            "    try: print(f'{d}=={m.version(d)}')\n"
            "    except m.PackageNotFoundError: print(f'{d}==?')\n")
    r = subprocess.run([str(py), "-c", code, *dists], capture_output=True, text=True)
    return r.stdout.split()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("packages", nargs="+", metavar="PACKAGE")
    parser.add_argument("--upgrade", action="store_true")
    args = parser.parse_args()

    for name in args.packages:
        if name not in PACKAGES:
            return _fail("SETUP_UNKNOWN_PACKAGE", f"{name} (choose from {', '.join(PACKAGES)})")
    if "mlx-whisper" in args.packages and not (
            platform.system() == "Darwin" and platform.machine() == "arm64"):
        return _fail("SETUP_PLATFORM", "mlx-whisper needs an Apple Silicon Mac; this is "
                     f"{platform.system()} {platform.machine()}")

    venv = venv_dir()
    err = ensure_venv(venv)
    if err:
        return _fail("SETUP_VENV_FAILED", err)

    py = venv_python(venv)
    specs = [PACKAGES[n] for n in dict.fromkeys(args.packages)]
    cmd = [str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check"]
    if args.upgrade:
        cmd.append("--upgrade")
    try:
        r = subprocess.run(cmd + specs, capture_output=True, text=True,
                           timeout=INSTALL_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return _fail("SETUP_INSTALL_FAILED", f"pip took over {INSTALL_TIMEOUT_SECONDS}s")
    if r.returncode != 0:
        tail = " | ".join((r.stderr or r.stdout).strip().splitlines()[-3:])
        return _fail("SETUP_INSTALL_FAILED", tail or f"pip exited {r.returncode}")

    dists = [s.split(">=")[0] for s in specs]
    print(f"SETUP_OK: {', '.join(installed_versions(py, dists))}")
    print(f"VENV: {venv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
