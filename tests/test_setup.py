"""First-run setup (057 D1–D3, D7): the private venv, the re-exec into it, preflight's
SETUP_NEEDED and LIBRARY_OUTDATED lines, and setup.py's contract.

Everything here runs offline except the one marked `network`, which really installs
youtube-transcript-api into a throw-away venv.
"""
import os
import subprocess
import sys
import venv as venv_mod
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "skills" / "video-lens" / "scripts"
RECS_DIR = REPO_ROOT / "skills" / "video-lens-recs" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import venv_env  # noqa: E402

PY_TAG = f"python{sys.version_info.major}.{sys.version_info.minor}"


def _fake_venv(root: Path, *, module=None, version="1.2.4", dist=None, ytdlp=False) -> Path:
    """A venv's shape on disk, without creating a real one."""
    (root / "bin").mkdir(parents=True)
    (root / "bin" / "python").symlink_to(sys.executable)
    sp = root / "lib" / PY_TAG / "site-packages"
    sp.mkdir(parents=True)
    if module:
        (sp / module).mkdir()
        (sp / module / "__init__.py").write_text("")
        name = dist or venv_env.DISTRIBUTIONS.get(module, module)
        info = sp / f"{name.replace('-', '_')}-{version}.dist-info"
        info.mkdir()
        info.joinpath("METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    if ytdlp:
        exe = root / "bin" / "yt-dlp"
        exe.write_text("#!/bin/sh\necho 2026.08.19\n")
        exe.chmod(0o755)
    return root


@pytest.fixture
def no_venv(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEO_LENS_VENV", str(tmp_path / "no-venv"))
    return tmp_path / "no-venv"


# ---------- venv_env ----------

def test_venv_dir_follows_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.delenv("VIDEO_LENS_VENV", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert venv_env.venv_dir() == tmp_path / "video-lens" / "venv"


def test_venv_has_reads_site_packages_on_disk(monkeypatch, tmp_path):
    v = _fake_venv(tmp_path / "v", module="youtube_transcript_api")
    monkeypatch.setenv("VIDEO_LENS_VENV", str(v))
    assert venv_env.venv_has("youtube_transcript_api")
    assert not venv_env.venv_has("mlx_whisper")


def test_venv_without_python_counts_as_absent(monkeypatch, tmp_path):
    v = _fake_venv(tmp_path / "v", module="youtube_transcript_api")
    (v / "bin" / "python").unlink()
    monkeypatch.setenv("VIDEO_LENS_VENV", str(v))
    assert not venv_env.venv_has("youtube_transcript_api")


def test_module_version_prefers_the_venv_copy(monkeypatch, tmp_path):
    v = _fake_venv(tmp_path / "v", module="youtube_transcript_api", version="0.6.3")
    monkeypatch.setenv("VIDEO_LENS_VENV", str(v))
    assert venv_env.module_version("youtube_transcript_api") == "0.6.3"


def test_ytdlp_path_prefers_path_then_the_venv(monkeypatch, tmp_path):
    v = _fake_venv(tmp_path / "v", ytdlp=True)
    monkeypatch.setenv("VIDEO_LENS_VENV", str(v))
    monkeypatch.setattr(venv_env.shutil, "which", lambda name: None)
    assert venv_env.ytdlp_path() == str(v / "bin" / "yt-dlp")
    assert venv_env.ytdlp_in_venv()
    monkeypatch.setattr(venv_env.shutil, "which", lambda name: "/usr/local/bin/yt-dlp")
    assert venv_env.ytdlp_path() == "/usr/local/bin/yt-dlp"
    assert not venv_env.ytdlp_in_venv()


@pytest.mark.parametrize("raw,expected", [
    ("1.2.4", (1, 2, 4)), ("2026.08.19", (2026, 8, 19)), ("1.0.0rc1", (1, 0, 0)),
    ("", ()), (None, ()),
])
def test_parse_version(raw, expected):
    assert venv_env.parse_version(raw) == expected


def _real_venv(root: Path, module: str) -> Path:
    """A real (pip-less) venv holding a stub `module`, for the re-exec tests."""
    venv_mod.EnvBuilder(with_pip=False, symlinks=os.name != "nt").create(root)
    sp = next((root / "lib").glob("python3*/site-packages"))
    (sp / module).mkdir()
    (sp / module / "__init__.py").write_text("STUB = True\n")
    return root


REEXEC_PROBE = (
    "import sys; sys.path.insert(0, {scripts!r})\n"
    "from venv_env import reexec_if_needed\n"
    "reexec_if_needed({module!r})\n"
    "print(sys.prefix); print(sys.argv[1:])\n"
)


def _run_probe(tmp_path, module, venv):
    probe = tmp_path / "probe.py"
    probe.write_text(REEXEC_PROBE.format(scripts=str(SCRIPT_DIR), module=module))
    env = {k: v for k, v in os.environ.items() if k != venv_env.REEXEC_MARK}
    env["VIDEO_LENS_VENV"] = str(venv)
    r = subprocess.run([sys.executable, str(probe), "--", "abc"],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    prefix, argv = r.stdout.splitlines()
    return Path(prefix), argv


def test_reexec_switches_to_the_venv_that_holds_the_module(tmp_path):
    v = _real_venv(tmp_path / "v", "vl_stub_mod")
    prefix, argv = _run_probe(tmp_path, "vl_stub_mod", v)
    assert prefix.resolve() == v.resolve()
    assert argv == "['--', 'abc']"


def test_no_reexec_when_the_venv_lacks_the_module(tmp_path):
    v = _real_venv(tmp_path / "v", "vl_stub_mod")
    prefix, _ = _run_probe(tmp_path, "some_other_mod", v)
    assert prefix.resolve() != v.resolve()


def test_no_reexec_without_a_venv(tmp_path):
    prefix, _ = _run_probe(tmp_path, "vl_stub_mod", tmp_path / "missing")
    assert prefix.resolve() == Path(sys.prefix).resolve()


# ---------- preflight ----------

def _preflight(tmp_path, venv, *, path=None, no_site=False):
    env = {**os.environ, "VIDEO_LENS_VENV": str(venv), "XDG_CACHE_HOME": str(tmp_path / "cache"),
           "XDG_CONFIG_HOME": str(tmp_path / "config")}
    if path is not None:
        env["PATH"] = path
    cmd = [sys.executable] + (["-S"] if no_site else []) + [str(SCRIPT_DIR / "preflight.py"),
                                                             "--", "dQw4w9WgXcQ"]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_preflight_asks_for_setup_when_the_transcript_library_is_missing(tmp_path):
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    out = _preflight(tmp_path, tmp_path / "no-venv", path=str(empty_bin), no_site=True)
    assert "SETUP_NEEDED: transcript-api, yt-dlp\n" in out


def test_preflight_setup_line_leaves_out_a_present_yt_dlp(tmp_path):
    v = _fake_venv(tmp_path / "v", ytdlp=True)
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    out = _preflight(tmp_path, v, path=str(empty_bin), no_site=True)
    assert "SETUP_NEEDED: transcript-api\n" in out


def test_preflight_is_quiet_when_the_venv_has_the_library(tmp_path):
    v = _fake_venv(tmp_path / "v", module="youtube_transcript_api", version="9.9.9")
    out = _preflight(tmp_path, v, no_site=True)
    assert "SETUP_NEEDED" not in out
    assert "LIBRARY_OUTDATED" not in out


def test_preflight_warns_on_an_old_transcript_library(tmp_path):
    v = _fake_venv(tmp_path / "v", module="youtube_transcript_api", version="0.6.3")
    out = _preflight(tmp_path, v, no_site=True)
    import preflight  # type: ignore
    assert (f"LIBRARY_OUTDATED: youtube-transcript-api 0.6.3 (known good: "
            f"{preflight.KNOWN_GOOD_TRANSCRIPT_API})\n") in out
    assert "SETUP_NEEDED" not in out


# ---------- the scripts' missing-dependency messages ----------

def test_fetch_transcript_points_at_setup_when_the_library_is_missing(tmp_path):
    env = {**os.environ, "VIDEO_LENS_VENV": str(tmp_path / "no-venv")}
    r = subprocess.run([sys.executable, "-S", str(SCRIPT_DIR / "fetch_transcript.py"), "--",
                        "dQw4w9WgXcQ"], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 1
    assert r.stdout.startswith("ERROR:LIBRARY_MISSING: youtube-transcript-api is not installed")
    assert f'python3 "{SCRIPT_DIR / "setup.py"}" transcript-api' in r.stdout


def test_fetch_metadata_finds_yt_dlp_in_the_venv(tmp_path):
    """yt-dlp off PATH but in the venv: fetch_metadata runs it (a stub printing no JSON)."""
    v = _fake_venv(tmp_path / "v", ytdlp=True)
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    env = {**os.environ, "VIDEO_LENS_VENV": str(v), "PATH": str(empty_bin),
           "XDG_CACHE_HOME": str(tmp_path / "cache")}
    r = subprocess.run([sys.executable, str(SCRIPT_DIR / "fetch_metadata.py"), "--", "dQw4w9WgXcQ"],
                       capture_output=True, text=True, env=env, timeout=30)
    assert "YTDLP_MISSING" not in r.stdout


def test_fetch_metadata_points_at_setup_without_yt_dlp(tmp_path):
    empty_bin = tmp_path / "bin"
    empty_bin.mkdir()
    env = {**os.environ, "VIDEO_LENS_VENV": str(tmp_path / "no-venv"), "PATH": str(empty_bin)}
    r = subprocess.run([sys.executable, str(SCRIPT_DIR / "fetch_metadata.py"), "--", "dQw4w9WgXcQ"],
                       capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0  # non-fatal
    assert r.stdout.startswith("ERROR:YTDLP_MISSING: yt-dlp not installed — run: python3 ")
    assert "setup.py\" yt-dlp" in r.stdout


def test_recs_finds_yt_dlp_in_the_video_lens_venv(monkeypatch, tmp_path):
    sys.path.insert(0, str(RECS_DIR))
    import yt_sources  # type: ignore
    v = _fake_venv(tmp_path / "v", ytdlp=True)
    monkeypatch.setenv("VIDEO_LENS_VENV", str(v))
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert yt_sources.ytdlp_bin() == str(v / "bin" / "yt-dlp")
    assert f'python3 "{SCRIPT_DIR / "setup.py"}" yt-dlp' in yt_sources.setup_hint()


# ---------- setup.py ----------

def _setup(tmp_path, *args):
    env = {**os.environ, "VIDEO_LENS_VENV": str(tmp_path / "venv")}
    return subprocess.run([sys.executable, str(SCRIPT_DIR / "setup.py"), *args],
                          capture_output=True, text=True, env=env, timeout=900)


def test_setup_rejects_an_unknown_package(tmp_path):
    r = _setup(tmp_path, "requests")
    assert r.returncode == 1
    assert r.stdout.startswith("ERROR:SETUP_UNKNOWN_PACKAGE requests")
    assert not (tmp_path / "venv").exists()


@pytest.mark.skipif(sys.platform == "darwin" and os.uname().machine == "arm64",
                    reason="mlx-whisper is allowed here")
def test_setup_refuses_mlx_whisper_off_apple_silicon(tmp_path):
    r = _setup(tmp_path, "mlx-whisper")
    assert r.returncode == 1
    assert r.stdout.startswith("ERROR:SETUP_PLATFORM")


@pytest.mark.network
def test_setup_installs_the_transcript_library_into_its_own_venv(tmp_path):
    r = _setup(tmp_path, "transcript-api")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("SETUP_OK: youtube-transcript-api==")
    assert f"VENV: {tmp_path / 'venv'}" in r.stdout
    v = tmp_path / "venv"
    assert venv_env.venv_has("youtube_transcript_api", v)
    # A second run is a no-op install, not an error.
    assert _setup(tmp_path, "transcript-api").returncode == 0


def test_recs_preflight_asks_for_yt_dlp_when_it_is_missing(monkeypatch, tmp_path):
    sys.path.insert(0, str(RECS_DIR))
    import collect  # type: ignore
    import yt_sources  # type: ignore
    monkeypatch.setenv("VIDEO_LENS_VENV", str(tmp_path / "no-venv"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv(yt_sources.REPLAY_ENV, raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    out, _, _ = collect.preflight("ai this week")
    assert any(line.startswith("SETUP_NEEDED: yt-dlp — run: python3 ") for line in out)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/yt-dlp")
    out, _, _ = collect.preflight("ai this week")
    assert not any(line.startswith("SETUP_NEEDED") for line in out)
