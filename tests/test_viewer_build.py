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
    for rel in bv.SHARED_PAGES:
        (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp / rel)
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


@pytest.mark.parametrize("rel", bv.SHARED_PAGES)
def test_check_detects_stale_tokens_in_a_page(tmp_path, rel):
    root = _copy_tree(tmp_path)
    page = root / rel
    page.write_text(page.read_text().replace("--paper: #f9f9f7;", "--paper: #fff;", 1))
    r = _run("--check", "--root", str(root))
    assert r.returncode == 1 and rel in r.stderr
    assert _run("--mode", "local", "--root", str(root)).returncode == 0
    assert page.read_bytes() == (ROOT / rel).read_bytes()


def test_tokens_and_components_are_inlined_everywhere():
    shared = bv.shared_css(ROOT)
    assert shared in (ROOT / "skills" / "video-lens" / "template.html").read_text()
    for rel in bv.SHARED_PAGES:
        assert bv.SHARED_BEGIN + shared + bv.SHARED_END in (ROOT / rel).read_text(), rel


def test_inline_shared_needs_both_markers_once():
    with pytest.raises(SystemExit):
        bv.inline_shared("<style></style>", ":root{}")
    with pytest.raises(SystemExit):
        bv.inline_shared(bv.SHARED_BEGIN + bv.SHARED_END + bv.SHARED_END, ":root{}")


# 038 D1: a color token (a custom property whose value is a color or a shadow) is defined in
# viewer/tokens.css and nowhere else.
COLOR_TOKEN = re.compile(r"--[\w-]+\s*:\s*[^;{}]*(?:#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|color-mix\()")


def _outside_shared(text):
    if bv.SHARED_BEGIN in text:
        head, rest = text.split(bv.SHARED_BEGIN)
        text = head + rest.split(bv.SHARED_END)[1]
    return text


@pytest.mark.parametrize("rel", ["viewer/viewer.css", "viewer/components.css", "viewer/shell.html", "viewer/viewer.js", *bv.SHARED_PAGES])
def test_no_color_token_outside_shared_css(rel):
    found = COLOR_TOKEN.findall(_outside_shared((ROOT / rel).read_text()))
    assert not found, "%s defines color tokens; move them to viewer/tokens.css: %s" % (rel, found)


def test_color_token_lint_catches_a_definition():
    assert COLOR_TOKEN.search(":root { --card-bg: #fff; }")
    assert COLOR_TOKEN.search("--x: 0 1px rgba(0,0,0,.1)")
    assert not COLOR_TOKEN.search("color: var(--accent); --pad: clamp(1rem, 8%, 3rem);")


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


def test_share_build_writes_the_four_files(tmp_path):
    r, out = _share(tmp_path)
    assert r.returncode == 0, r.stderr
    assert sorted(p.name for p in out.iterdir()) == ["shell.html", "tokens.css", "viewer.css", "viewer.js"]
    tokens = (ROOT / "viewer" / "tokens.css").read_bytes()
    assert (out / "tokens.css").read_bytes() == tokens
    assert (out / "viewer.css").read_bytes() == bv.viewer_css(ROOT).encode("utf-8")
    assert (out / "viewer.css").read_bytes().startswith(tokens)
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
    for name in ("shell.html", "viewer.css", "viewer.js", "tokens.css"):
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


# 038 D2: one type system on every local page: DM Sans (the only web font, one request) for
# headlines and interface, Georgia for prose, the ui-monospace stack for code.
LOCAL_PAGES = ["skills/video-lens/template.html", *bv.SHARED_PAGES]


@pytest.mark.parametrize("rel", LOCAL_PAGES)
def test_local_pages_use_one_type_system(rel):
    text = (ROOT / rel).read_text()
    assert "DM Serif" not in text and "DM Mono" not in text
    fonts = re.findall(r'href="(https://fonts\.googleapis\.com/css2[^"]*)"', text)
    assert fonts == ["https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap"], fonts
    css = _outside_shared(text)
    assert not re.findall(r"font-family:\s*['\"]?(?!var\(|inherit)[^;']*DM Sans", css), "name the font through var(--sans)"


# 038 D3: one brand mark (viewer/mark.svg): a red circle and a white "VL", in both themes, for the
# favicon of every page and every mark drawn in a page.
MARK_RE = re.compile(r"<svg[^>]*>(<circle[^>]*/><text[^>]*>VL</text>)</svg>")


def _marks(text):
    decoded = text.replace("%23", "#").replace("'", '"')
    return MARK_RE.findall(decoded)


@pytest.mark.parametrize("rel", ["viewer/shell.html", *bv.SHARED_PAGES])
def test_every_mark_is_the_one_mark(rel):
    canonical = _marks((ROOT / "viewer" / "mark.svg").read_text())
    assert len(canonical) == 1 and 'fill="#c0392b"' in canonical[0] and 'fill="#fff"' in canonical[0]
    text = (ROOT / rel).read_text()
    found = _marks(text)
    assert found and set(found) == set(canonical), rel
    assert text.count("VL</text>") == len(found), "a VL mark that is not the canonical one"
    assert 'rel="icon"' in text and "ffd700" not in text


# 038 D4: one theme control on every local page: the report's half-circle icon, the shared key
# "theme", the OS until the reader chooses (nothing written at load), t toggles.
HALF_CIRCLE = '<path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor"/>'


@pytest.mark.parametrize("rel", bv.SHARED_PAGES)
def test_theme_control_is_the_reports(rel):
    text = (ROOT / rel).read_text()
    assert HALF_CIRCLE in text and 'title="Light or dark [t]"' in text
    assert "sunPath" not in text and "moonPath" not in text
    assert "matches ? 'dark' : 'light'" not in text, "data-theme from the OS at load"
    assert "if (t === 'dark' || t === 'light') document.documentElement.setAttribute('data-theme', t);" in text
    assert "e.key === 't'" in text and "localStorage.setItem('theme', next)" in text


# 038 D5: help is the report's <dialog> on every local page: ? opens it, Esc closes it (native),
# the keys of the page are listed, and the gallery's text names the report's four parts.
@pytest.mark.parametrize("rel", bv.SHARED_PAGES)
def test_help_is_a_dialog_with_the_pages_keys(rel):
    text = (ROOT / rel).read_text()
    assert '<dialog id="help" aria-labelledby="help-h" tabindex="-1">' in text
    assert "help-overlay" not in text and "help-modal" not in text
    keys = re.search(r'<dl class="keys">(.*?)</dl>', text, re.S).group(1)
    assert "<kbd>t</kbd>" in keys and "<kbd>?</kbd>" in keys
    assert "e.key === '?'" in text and 'title="Keyboard shortcuts and info [?]"' in text


def test_gallery_help_lists_its_keys_and_the_four_parts():
    text = (ROOT / "skills/video-lens-gallery/index.html").read_text()
    keys = re.search(r'<dl class="keys">(.*?)</dl>', text, re.S).group(1)
    assert "<kbd>/</kbd>" in keys and "<kbd>1</kbd> <kbd>2</kbd>" in keys
    about = text[text.index("<h2>About</h2>"):text.index("</dialog>")]
    assert "analysis" not in about
    for part in ("summary", "takeaway", "key points", "timed outline"):
        assert part in about, part


# 038 D6: one title pattern, "<page> · video-lens".
def test_page_titles_follow_one_pattern():
    assert "<title>Gallery · video-lens</title>" in (ROOT / "skills/video-lens-gallery/index.html").read_text()
    assert "<title>{{VIDEO_TITLE}} · video-lens</title>" in (ROOT / "viewer/shell.html").read_text()
    sys.path.insert(0, str(ROOT / "skills" / "video-lens-recs" / "scripts"))
    import page
    src = Path(page.__file__).read_text()
    assert '"PAGE_TITLE": _e(f"Discover: {data[\'label\']} · video-lens"),' in src
