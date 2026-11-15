"""The skill update check (058 §4): version.json, the daily cache, the SKILL_OUTDATED line.

No network: version.json comes from a file:// URL or a stubbed urlopen.
"""
import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "skills" / "video-lens" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import preflight  # noqa: E402
import update_check  # noqa: E402

NOW = 1_800_000_000.0
HOUR = 3600


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.delenv("VIDEO_LENS_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return tmp_path


def skill(tmp_path, version="5.5"):
    d = tmp_path / "skill"
    d.mkdir(exist_ok=True)
    meta = f'  version: "{version}"\n' if version else ""
    (d / "SKILL.md").write_text(
        f"---\nname: video-lens\nmetadata:\n  author: someone\n{meta}---\n\nBody\n  version: 1.0\n",
        encoding="utf-8")
    return d


def serve(tmp_path, monkeypatch, data):
    path = tmp_path / "version.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("VIDEO_LENS_VERSION_URL", path.as_uri())


def lock(tmp_path, source="kar2phi/video-lens", raw=None):
    p = tmp_path / "home" / ".agents" / ".skill-lock.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(raw if raw is not None else json.dumps(
        {"version": 3, "skills": {"video-lens": {"source": source}}}), encoding="utf-8")


def cache(tmp_path):
    return json.loads((tmp_path / "data" / "video-lens" / "update-check.json").read_text())


def write_cache(tmp_path, checked_at, latest="5.6", minimum=None):
    p = tmp_path / "data" / "video-lens" / "update-check.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"checked_at": checked_at, "latest": latest, "minimum": minimum}))


class Calls:
    def __init__(self, result=None, exc=None):
        self.n, self.result, self.exc = 0, result, exc

    def __call__(self, req, timeout=None):
        self.n += 1
        if self.exc:
            raise self.exc
        return self.result


class Resp(io.BytesIO):
    def __init__(self, body: bytes, status=200):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ---------- the notice ----------

def test_older_install_without_lock_is_manual(env, monkeypatch):
    serve(env, monkeypatch, {"latest": "5.6"})
    assert update_check.check(skill(env), now=NOW) == "5.5 (latest: 5.6) via manual"


def test_lock_entry_for_the_public_repo_is_npx(env, monkeypatch):
    serve(env, monkeypatch, {"latest": "5.6"})
    lock(env, source="Kar2phi/Video-Lens")
    assert update_check.check(skill(env), now=NOW) == "5.5 (latest: 5.6) via npx"


@pytest.mark.parametrize("kw", [{"source": "someone/fork"}, {"raw": "{not json"}, {"raw": "[]"}])
def test_other_source_or_corrupt_lock_is_manual(env, monkeypatch, kw):
    serve(env, monkeypatch, {"latest": "5.6"})
    lock(env, **kw)
    assert update_check.check(skill(env), now=NOW).endswith("via manual")


@pytest.mark.parametrize("installed", ["5.6", "5.7", "5.6.0", "6"])
def test_silent_when_equal_or_ahead(env, monkeypatch, installed):
    serve(env, monkeypatch, {"latest": "5.6"})
    assert update_check.check(skill(env, installed), now=NOW) is None


def test_below_minimum_says_so(env, monkeypatch):
    serve(env, monkeypatch, {"latest": "5.6", "minimum": "5.0"})
    assert update_check.check(skill(env, "4.9"), now=NOW) == "4.9 (latest: 5.6, minimum: 5.0) via manual"


def test_minimum_left_out_when_installed_meets_it(env, monkeypatch):
    serve(env, monkeypatch, {"latest": "5.6", "minimum": "5.0", "message": "ignored"})
    assert update_check.check(skill(env, "5.0"), now=NOW) == "5.0 (latest: 5.6) via manual"


def test_skill_md_without_version(env, monkeypatch):
    serve(env, monkeypatch, {"latest": "5.6"})
    assert update_check.check(skill(env, None), now=NOW) is None


# ---------- the daily cache ----------

def test_fresh_cache_skips_the_fetch(env, monkeypatch):
    write_cache(env, NOW - HOUR)
    calls = Calls(exc=AssertionError("fetched"))
    monkeypatch.setattr(urllib.request, "urlopen", calls)
    assert update_check.check(skill(env), now=NOW) == "5.5 (latest: 5.6) via manual"
    assert calls.n == 0


def test_stale_cache_fetches_once_and_rewrites(env, monkeypatch):
    write_cache(env, NOW - 25 * HOUR, latest="5.6")
    calls = Calls(result=Resp(b'{"latest": "5.8"}'))
    monkeypatch.setattr(urllib.request, "urlopen", calls)
    assert update_check.check(skill(env), now=NOW) == "5.5 (latest: 5.8) via manual"
    assert calls.n == 1
    assert cache(env) == {"checked_at": NOW, "latest": "5.8", "minimum": None}


def test_future_checked_at_counts_as_stale(env, monkeypatch):
    write_cache(env, NOW + 10 * HOUR, latest="5.6")
    calls = Calls(result=Resp(b'{"latest": "5.7"}'))
    monkeypatch.setattr(urllib.request, "urlopen", calls)
    assert update_check.check(skill(env), now=NOW) == "5.5 (latest: 5.7) via manual"
    assert calls.n == 1


def test_corrupt_cache_counts_as_stale(env, monkeypatch):
    p = env / "data" / "video-lens" / "update-check.json"
    p.parent.mkdir(parents=True)
    p.write_text("garbage")
    serve(env, monkeypatch, {"latest": "5.6"})
    assert update_check.check(skill(env), now=NOW) is not None
    assert cache(env)["checked_at"] == NOW


@pytest.mark.parametrize("exc", [TimeoutError("slow"), urllib.error.URLError("offline")])
def test_failed_fetch_without_cache(env, monkeypatch, exc):
    monkeypatch.setattr(urllib.request, "urlopen", Calls(exc=exc))
    assert update_check.check(skill(env), now=NOW) is None
    assert cache(env) == {"checked_at": NOW, "latest": None, "minimum": None}


def test_failed_fetch_keeps_the_old_latest(env, monkeypatch):
    write_cache(env, NOW - 30 * HOUR, latest="5.6")
    calls = Calls(exc=urllib.error.URLError("offline"))
    monkeypatch.setattr(urllib.request, "urlopen", calls)
    assert update_check.check(skill(env), now=NOW) == "5.5 (latest: 5.6) via manual"
    assert cache(env)["checked_at"] == NOW
    # The timestamp went in before the fetch: the next run within a day does not retry.
    assert update_check.check(skill(env), now=NOW + HOUR) is not None
    assert calls.n == 1


def test_timestamp_is_written_before_the_fetch(env, monkeypatch):
    seen = {}

    def urlopen(req, timeout=None):
        seen["cache"] = cache(env)
        seen["timeout"] = timeout
        seen["ua"] = req.get_header("User-agent")
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    update_check.check(skill(env), now=NOW)
    assert seen["cache"]["checked_at"] == NOW
    assert seen["timeout"] == update_check.FETCH_TIMEOUT_SECONDS
    assert seen["ua"] == "video-lens-update-check"


def test_cache_dir_is_private(env, monkeypatch):
    serve(env, monkeypatch, {"latest": "5.6"})
    update_check.check(skill(env), now=NOW)
    mode = (env / "data" / "video-lens").stat().st_mode & 0o777
    assert mode & 0o077 == 0


# ---------- untrusted responses (U6) ----------

@pytest.mark.parametrize("resp", [
    Resp(b'{"latest": "5.6"}', status=404),
    Resp(b'{"latest": "5.6", "pad": "' + b"x" * 5000 + b'"}'),
    Resp(b"<html>not json</html>"),
    Resp(b'["5.6"]'),
    Resp(b'{"latest": "5.6; rm -rf ~"}'),
    Resp(b'{"latest": 5.6}'),
    Resp(b'{"latest": "v5.6"}'),
    Resp(b'{"latest": "5.6", "minimum": "five"}'),
    Resp(b'{"latest": "1.2.3.4.5"}'),
    Resp(b"\xff\xfe"),
])
def test_junk_responses_are_ignored(env, monkeypatch, resp):
    monkeypatch.setattr(urllib.request, "urlopen", Calls(result=resp))
    assert update_check.check(skill(env), now=NOW) is None
    assert cache(env)["latest"] is None


# ---------- opt-out ----------

@pytest.mark.parametrize("var,value", [("VIDEO_LENS_NO_UPDATE_CHECK", "1"),
                                       ("VIDEO_LENS_NO_UPDATE_CHECK", "true"),
                                       ("CI", "true")])
def test_opt_out_makes_no_call_and_no_cache(env, monkeypatch, var, value):
    monkeypatch.setenv(var, value)
    calls = Calls(exc=AssertionError("fetched"))
    monkeypatch.setattr(urllib.request, "urlopen", calls)
    assert update_check.check(skill(env), now=NOW) is None
    assert calls.n == 0
    assert not (env / "data").exists()


# ---------- preflight ----------

def _run_preflight(monkeypatch, capsys, tmp_path, check):
    monkeypatch.setattr(sys, "argv", ["preflight.py", "dQw4w9WgXcQ"])
    monkeypatch.setattr(preflight, "PAYLOAD_BASE_DIR", tmp_path / "cache" / "payloads")
    monkeypatch.setattr(preflight, "LEGACY_PAYLOAD_BASE_DIR", tmp_path / "legacy")
    monkeypatch.setattr(preflight, "setup_status", lambda: ([], "youtube-transcript-api 1.0 (known good: 1.2.4)"))
    monkeypatch.setattr(preflight, "probe_capabilities", lambda: [])
    monkeypatch.setattr(preflight.update_check, "check", check)
    rc = preflight.main()
    return rc, capsys.readouterr().out.splitlines()


def test_preflight_prints_the_line_after_library_outdated(env, monkeypatch, capsys):
    rc, lines = _run_preflight(monkeypatch, capsys, env, lambda d: "5.5 (latest: 5.6) via npx")
    assert rc == 0
    i = next(i for i, l in enumerate(lines) if l.startswith("LIBRARY_OUTDATED:"))
    assert lines[i + 1] == "SKILL_OUTDATED: 5.5 (latest: 5.6) via npx"


def test_preflight_survives_a_raising_check(env, monkeypatch, capsys):
    def boom(d):
        raise RuntimeError("boom")
    rc, lines = _run_preflight(monkeypatch, capsys, env, boom)
    assert rc == 0
    assert not any(l.startswith("SKILL_OUTDATED:") for l in lines)


def test_preflight_passes_the_skill_dir(env, monkeypatch, capsys):
    seen = []
    _run_preflight(monkeypatch, capsys, env, lambda d: seen.append(d))
    assert seen == [SCRIPT_DIR.parent]


# ---------- release guard ----------

def test_version_json_matches_skill_md():
    data = json.loads((REPO_ROOT / "version.json").read_text(encoding="utf-8"))
    assert re.fullmatch(r"\d+(\.\d+){0,3}", data["latest"])
    assert data["latest"] == update_check.installed_version(REPO_ROOT / "skills" / "video-lens")
    if "minimum" in data:
        assert update_check.parse_version(data["minimum"]) <= update_check.parse_version(data["latest"])
