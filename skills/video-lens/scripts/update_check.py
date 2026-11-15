"""Tell the user when a newer video-lens is out (058).

`check(skill_dir)` returns the value of preflight's `SKILL_OUTDATED:` line, or None.
At most once a day it reads `version.json` from the public repo on GitHub (one plain
GET, no data about the user); every other run reads only a small cache file,
`$XDG_DATA_HOME/video-lens/update-check.json`. Notify only: nothing is ever updated
here (058 U4).

- `VIDEO_LENS_NO_UPDATE_CHECK=1` (or a set `CI`) turns it off (058 U2).
- `VIDEO_LENS_VERSION_URL` points it elsewhere (tests and evals).
- The timestamp is written before the fetch, so offline runs never retry (058 U3).
- Only version-shaped strings are taken from the network; nothing else reaches the
  agent (058 U6).

Stdlib only, and it never raises: every failure returns None.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile
import time
import urllib.request

from venv_env import parse_version

VERSION_URL = "https://raw.githubusercontent.com/kar2phi/video-lens/main/version.json"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
FETCH_TIMEOUT_SECONDS = 2.0
MAX_BODY_BYTES = 4096
OPT_OUT_ENV = "VIDEO_LENS_NO_UPDATE_CHECK"
URL_ENV = "VIDEO_LENS_VERSION_URL"
LOCK_SOURCE = "kar2phi/video-lens"

VERSION_RE = re.compile(r"^\d+(\.\d+){0,3}$")
FRONTMATTER_VERSION_RE = re.compile(r'^\s+version:\s*"?([0-9.]+)"?\s*$', re.MULTILINE)


def _opted_out() -> bool:
    if os.environ.get(OPT_OUT_ENV, "").strip().lower() in {"1", "true", "yes"}:
        return True
    return bool(os.environ.get("CI", "").strip())


def _valid(v) -> str | None:
    return v if isinstance(v, str) and VERSION_RE.fullmatch(v) else None


def installed_version(skill_dir: pathlib.Path) -> str | None:
    """`metadata.version` from SKILL.md's frontmatter, read with a regex (no YAML)."""
    try:
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration:
        return None
    m = FRONTMATTER_VERSION_RE.search("\n".join(lines[1:end]))
    return _valid(m.group(1)) if m else None


def cache_path() -> pathlib.Path:
    data_home = os.environ.get("XDG_DATA_HOME") or str(pathlib.Path.home() / ".local" / "share")
    return pathlib.Path(data_home) / "video-lens" / "update-check.json"


def _read_cache(path: pathlib.Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    checked = data.get("checked_at")
    if not isinstance(checked, (int, float)) or isinstance(checked, bool):
        return None
    return {"checked_at": checked, "latest": _valid(data.get("latest")),
            "minimum": _valid(data.get("minimum"))}


def _write_cache(path: pathlib.Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(prefix=".update-check-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:
        pass


def fetch_latest() -> tuple[str, str | None] | None:
    """(latest, minimum) from version.json, or None on any failure or junk."""
    url = os.environ.get(URL_ENV) or VERSION_URL
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "video-lens-update-check"})
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", None)
            # file:// responses carry no status; anything else must be a plain 200.
            if status is not None and status != 200:
                return None
            body = resp.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            return None
        data = json.loads(body.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    latest = _valid(data.get("latest"))
    if latest is None:
        return None
    minimum = data.get("minimum")
    if minimum is not None and _valid(minimum) is None:
        return None
    return latest, minimum


def install_method() -> str:
    """`npx` when the global skills lock records video-lens from the public repo (057 D8)."""
    try:
        lock = json.loads((pathlib.Path.home() / ".agents" / ".skill-lock.json")
                          .read_text(encoding="utf-8"))
        source = lock["skills"]["video-lens"]["source"]
        if isinstance(source, str) and source.strip().lower() == LOCK_SOURCE:
            return "npx"
    except Exception:
        pass
    return "manual"


def check(skill_dir: pathlib.Path, now: float | None = None) -> str | None:
    """The SKILL_OUTDATED line's value, or None (up to date, opted out, offline, junk)."""
    try:
        if _opted_out():
            return None
        installed = installed_version(skill_dir)
        if installed is None:
            return None
        now = time.time() if now is None else now
        path = cache_path()
        cached = _read_cache(path)
        latest = cached["latest"] if cached else None
        minimum = cached["minimum"] if cached else None
        fresh = cached is not None and 0 <= now - cached["checked_at"] < CHECK_INTERVAL_SECONDS
        if not fresh:
            _write_cache(path, {"checked_at": now, "latest": latest, "minimum": minimum})
            fetched = fetch_latest()
            if fetched is not None:
                latest, minimum = fetched
                _write_cache(path, {"checked_at": now, "latest": latest, "minimum": minimum})
        if latest is None:
            return None
        have = parse_version(installed)
        if have >= parse_version(latest):
            return None
        value = f"{installed} (latest: {latest}"
        if minimum is not None and have < parse_version(minimum):
            value += f", minimum: {minimum}"
        return f"{value}) via {install_method()}"
    except Exception:
        return None
