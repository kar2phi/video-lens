"""viewer/ is the single source of skills/video-lens/template.html (tools/build_viewer.py)."""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "tools" / "build_viewer.py"

_spec = importlib.util.spec_from_file_location("build_viewer", BUILD)
bv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bv)


def _copy_tree(tmp):
    shutil.copytree(ROOT / "viewer", tmp / "viewer")
    (tmp / "skills" / "video-lens").mkdir(parents=True)
    shutil.copy(ROOT / "skills" / "video-lens" / "template.html",
                tmp / "skills" / "video-lens" / "template.html")
    return tmp


def _run(*args):
    return subprocess.run([sys.executable, str(BUILD), *args], capture_output=True, text=True)


def test_build_is_byte_identical_to_committed_template():
    built = bv.build_local(ROOT).encode("utf-8")
    assert built == (ROOT / "skills" / "video-lens" / "template.html").read_bytes()


def test_check_passes_when_current():
    assert _run("--check").returncode == 0


def test_check_detects_edited_template(tmp_path):
    root = _copy_tree(tmp_path)
    t = root / "skills" / "video-lens" / "template.html"
    t.write_bytes(t.read_bytes() + b"<!-- edit -->\n")
    r = _run("--check", "--root", str(root))
    assert r.returncode == 1 and "STALE" in r.stderr


def test_check_detects_edited_source(tmp_path):
    root = _copy_tree(tmp_path)
    css = root / "viewer" / "viewer.css"
    css.write_text(css.read_text() + "\n/* new */\n")
    assert _run("--check", "--root", str(root)).returncode == 1
    assert _run("--mode", "local", "--root", str(root)).returncode == 0
    assert _run("--check", "--root", str(root)).returncode == 0


def test_include_points_do_not_collide_with_render_slots():
    shell = (ROOT / "viewer" / "shell.html").read_text()
    assert shell.count("{{VL_CSS}}") == 1 and shell.count("{{VL_JS}}") == 1
    for name in ("viewer.css", "viewer.js"):
        assert "{{VL_" not in (ROOT / "viewer" / name).read_text()
