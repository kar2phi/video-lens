"""video-lens's private Python environment (first-run setup).

`setup.py` installs the third-party packages into one venv,
`$XDG_DATA_HOME/video-lens/venv` (default `~/.local/share/video-lens/venv`), so
nothing touches the system Python and PEP 668 does not apply. The scripts stay
plain `python3 script.py` calls; this module finds that venv for them:

- `reexec_if_needed(module)`: when the venv holds `module`, re-run this script with
  the venv's Python (once; a marker in the environment stops a loop). Otherwise the
  current interpreter carries on and the script reports the module as missing.
- `ytdlp_path()`: yt-dlp on PATH first, then the venv's own.
- `module_version(module)`: the installed version the scripts will actually use.

`VIDEO_LENS_VENV` overrides the location (tests point it at an empty directory).
Stdlib only: this module runs before anything is installed.
"""
from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import pathlib
import shutil
import sys

REEXEC_MARK = "VIDEO_LENS_VENV_REEXEC"

# Import name -> distribution name, for the version lookup.
DISTRIBUTIONS = {
    "youtube_transcript_api": "youtube-transcript-api",
    "mlx_whisper": "mlx-whisper",
    "yt_dlp": "yt-dlp",
}


def venv_dir() -> pathlib.Path:
    override = os.environ.get("VIDEO_LENS_VENV")
    if override:
        return pathlib.Path(override).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME") or str(pathlib.Path.home() / ".local" / "share")
    return pathlib.Path(data_home) / "video-lens" / "venv"


def _bin_dir(venv: pathlib.Path) -> pathlib.Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def venv_python(venv: pathlib.Path | None = None) -> pathlib.Path:
    venv = venv or venv_dir()
    return _bin_dir(venv) / ("python.exe" if os.name == "nt" else "python")


def _site_packages(venv: pathlib.Path) -> list[pathlib.Path]:
    if os.name == "nt":
        return [p for p in [venv / "Lib" / "site-packages"] if p.is_dir()]
    return sorted(p for p in (venv / "lib").glob("python3*/site-packages") if p.is_dir())


def venv_has(module: str, venv: pathlib.Path | None = None) -> bool:
    """True when the venv's site-packages holds `module` (checked on disk, no subprocess)."""
    venv = venv or venv_dir()
    if not venv_python(venv).exists():
        return False
    for sp in _site_packages(venv):
        if (sp / module).is_dir() or (sp / f"{module}.py").is_file():
            return True
    return False


def _running_in(venv: pathlib.Path) -> bool:
    try:
        return pathlib.Path(sys.prefix).resolve() == venv.resolve()
    except OSError:
        return False


def reexec_if_needed(module: str) -> None:
    """Re-run the calling script with the venv's Python when the venv holds `module`.

    The venv wins over the current interpreter when it has the module, so
    `setup.py --upgrade` fixes an outdated copy even if an older one sits in the
    system Python. Returns (and the caller carries on) when there is no venv, the
    venv lacks the module, or this process already is the venv's Python.
    """
    venv = venv_dir()
    if os.environ.get(REEXEC_MARK) or _running_in(venv) or not venv_has(module, venv):
        return
    py = str(venv_python(venv))
    env = {**os.environ, REEXEC_MARK: "1"}
    script = os.path.abspath(sys.argv[0])
    sys.stdout.flush()
    sys.stderr.flush()
    os.execve(py, [py, script, *sys.argv[1:]], env)


def module_available(module: str) -> bool:
    """Installed here or in the venv, so a script that needs it can run."""
    return venv_has(module) or importlib.util.find_spec(module) is not None


def module_version(module: str) -> str | None:
    """Version of `module` the scripts will use: the venv's copy first, then this Python's."""
    dist = DISTRIBUTIONS.get(module, module)
    venv = venv_dir()
    if venv_has(module, venv):
        for sp in _site_packages(venv):
            for d in importlib.metadata.distributions(path=[str(sp)]):
                if (d.metadata["Name"] or "").lower().replace("_", "-") == dist:
                    return d.version
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return None


def ytdlp_path() -> str | None:
    """yt-dlp on PATH, else the venv's, else None."""
    found = shutil.which("yt-dlp")
    if found:
        return found
    exe = _bin_dir(venv_dir()) / ("yt-dlp.exe" if os.name == "nt" else "yt-dlp")
    return str(exe) if exe.is_file() and os.access(exe, os.X_OK) else None


def ytdlp_in_venv() -> bool:
    """True when the yt-dlp the scripts use is the venv's (so setup.py --upgrade updates it)."""
    found = ytdlp_path()
    if not found:
        return False
    try:
        return pathlib.Path(found).resolve().is_relative_to(venv_dir().resolve())
    except OSError:
        return False


def parse_version(v: str | None) -> tuple:
    """'1.2.4' -> (1, 2, 4); '2026.08.19' -> (2026, 8, 19); junk parts stop the tuple."""
    out = []
    for part in (v or "").split("."):
        digits = ""
        for ch in part:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)
