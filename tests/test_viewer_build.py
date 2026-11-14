"""viewer/ is the single source of skills/video-lens/template.html (tools/build_viewer.py)."""
import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


# ── 037 A3: the share build ──

SHARE_SLOTS = {"ASSET_CSS", "ASSET_FONTS", "ASSET_JS", "DURATION_S", "HEAD_EXTRA", "KEY_POINTS", "LANG",
               "META_LINE", "OUTLINE", "PLAYER_PANEL", "REPORT_URL", "SUMMARY", "TAKEAWAY", "VIDEO_TITLE",
               "VIDEO_URL"}


def _share(tmp, root=ROOT):
    out = tmp / "share"
    r = _run("--mode", "share", "--out", str(out), "--root", str(root))
    return r, out


def test_share_build_writes_the_three_files(tmp_path):
    r, out = _share(tmp_path)
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in out.iterdir()) == ["shell.html", "viewer.css", "viewer.js"]
    assert (out / "viewer.css").read_bytes() == (ROOT / "viewer" / "viewer.css").read_bytes()
    assert (out / "viewer.js").read_bytes() == (ROOT / "viewer" / "viewer.js").read_bytes()


def test_share_shell_has_the_workers_slots_and_no_local_parts(tmp_path):
    _, out = _share(tmp_path)
    shell = (out / "shell.html").read_text(encoding="utf-8")
    assert set(re.findall(r"\{\{([A-Z_]+)\}\}", shell)) == SHARE_SLOTS
    assert '<html lang="{{LANG}}" data-vl-mode="share">' in shell
    for local_only in ("{{VL_CSS}}", "{{VL_JS}}", "{{VL_MODE}}", "file-note", "data-autoload", "video-lens-meta",
                       "{{DESCRIPTION_SECTION}}", "../index.html", "gen-facts", "<!-- @"):
        assert local_only not in shell, local_only
    assert '<script src="{{ASSET_JS}}"></script>' in shell
    assert '<link rel="stylesheet" href="{{ASSET_CSS}}">' in shell
    assert "Report this page" in shell and 'href="{{REPORT_URL}}"' in shell


def test_share_output_is_free_of_the_old_player_fonts_and_inline_code(tmp_path):
    _, out = _share(tmp_path)
    for name in ("shell.html", "viewer.css", "viewer.js"):
        text = (out / name).read_text(encoding="utf-8")
        for bad in ("yt-overlay", "controls=0", "fonts.googleapis.com"):
            assert bad not in text, (name, bad)
    shell = (out / "shell.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\ssrc=)", shell) and "<style" not in shell
    assert not re.search(r"\sstyle\s*=", shell) and not re.search(r"\son[a-z]+\s*=", shell)


def test_share_build_is_deterministic(tmp_path):
    _, a = _share(tmp_path / "a")
    _, b = _share(tmp_path / "b")
    for name in ("shell.html", "viewer.css", "viewer.js"):
        assert (a / name).read_bytes() == (b / name).read_bytes()


@pytest.mark.parametrize("edit", [
    ("viewer/shell.html", "<h1>", '<h1 style="color:red">'),
    ("viewer/shell.html", "</head>", "<style>x{}</style></head>"),
    ("viewer/shell.html", "</head>", "<script>1</script></head>"),
    ("viewer/shell.html", "{{HEAD_EXTRA}}", '<link href="https://fonts.googleapis.com/css2?family=X">'),
    ("viewer/shell.html", '<div class="layout">', '<div class="layout" onclick="x()">'),
])
def test_share_build_refuses_an_unclean_source(tmp_path, edit):
    root = _copy_tree(tmp_path / "src")
    name, old, new = edit
    f = root / name
    f.write_text(f.read_text().replace(old, new, 1))
    r, out = _share(tmp_path, root)
    assert r.returncode != 0 and "not clean" in r.stderr and not out.exists()


def test_share_mode_needs_an_out_dir_and_has_no_check():
    assert _run("--mode", "share").returncode != 0
    assert _run("--mode", "share", "--check", "--out", "/nonexistent").returncode != 0


def test_dev_sample_is_v1_and_renders_without_warnings(tmp_path, monkeypatch, capsys):
    """038 B11: `task dev` exercises the current payload shape (v1 arrays, key-point t)."""
    import importlib.util
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("yt_template_dev", root / "scripts" / "yt_template_dev.py")
    dev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dev)
    assert isinstance(dev.CONTENT["KEY_POINTS"], list) and isinstance(dev.CONTENT["OUTLINE"], list)
    assert all({"point", "why", "detail", "t"} <= set(k) for k in dev.CONTENT["KEY_POINTS"])
    import render_report as rr
    monkeypatch.setattr(rr, "METADATA_DIR", tmp_path / "metadata")
    rr.render_from_payload(dev.CONTENT, str(tmp_path / "sample.html"))
    assert "RENDER_WARN" not in capsys.readouterr().err
