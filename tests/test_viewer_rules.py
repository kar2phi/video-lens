"""Source rules for viewer/ (035 §4.4) and the hooks other code reads in a report (036 §2).

Ported from the checks in video-lens-core design/build_prototype.py (037 A2): rules 1, 2 and 5,
plus "the source never closes its own inline tag". Rule 3 is a browser property (the share
build's CSP test); rule 4's mode blocks are checked for shape here.
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"
TEMPLATE = ROOT / "skills" / "video-lens" / "template.html"
GOLDEN = ROOT / "tests" / "golden"
sys.path.insert(0, str(ROOT / "skills" / "video-lens" / "scripts"))
import render_report as rr  # noqa: E402

ALLOWED_HOSTS = {"www.youtube.com", "www.youtube-nocookie.com"}

SHELL = (VIEWER / "shell.html").read_text(encoding="utf-8")
JS = (VIEWER / "viewer.js").read_text(encoding="utf-8")
CSS = (VIEWER / "viewer.css").read_text(encoding="utf-8")


# ── 035 §4.4 rule 1: no inline style or handler in the shell; no string code in the script ──

def test_shell_has_no_style_attribute():
    assert not re.search(r"\sstyle\s*=", SHELL)


def test_shell_has_no_event_handler_attribute():
    assert not re.search(r"\son[a-z]+\s*=", SHELL)


@pytest.mark.parametrize("bad", ["style=", "setAttribute('style'", 'setAttribute("style"', "eval(",
                                 "new Function", "innerHTML", "outerHTML", "insertAdjacentHTML",
                                 "document.write"])
def test_script_writes_no_style_attribute_and_no_string_code(bad):
    assert bad not in JS


def test_script_has_no_string_timers():
    assert not re.search(r"set(?:Timeout|Interval)\(\s*['\"`]", JS)


# ── rule 2: the script and the stylesheet are the same bytes on every page ──

@pytest.mark.parametrize("name,text", [("viewer.js", JS), ("viewer.css", CSS)])
def test_no_slot_in_script_or_stylesheet(name, text):
    assert "{{" not in text and "}}" not in text, name


# ── rule 4: mode blocks are well formed and balanced ──

def test_mode_blocks_are_balanced():
    markers = re.findall(r"<!-- @(local|share|end) -->", SHELL)
    opened = None
    for m in markers:
        if m == "end":
            assert opened, "an @end without an open block"
            opened = None
        else:
            assert opened is None, "mode blocks do not nest"
            opened = m
    assert opened is None and "local" in markers and "share" in markers


def test_mode_is_a_slot_not_a_test_in_the_script():
    assert '<html lang="{{LANG}}" data-vl-mode="{{VL_MODE}}">' in SHELL


# ── rule 5: the only hosts the script names ──

def test_script_names_only_youtube_hosts():
    hosts = set(re.findall(r"https?://([A-Za-z0-9.-]+)", JS))
    assert hosts <= ALLOWED_HOSTS, sorted(hosts - ALLOWED_HOSTS)


def test_source_never_closes_its_own_inline_tag():
    assert "</script" not in JS.lower()
    assert "</style" not in CSS.lower()


# ── The local build (037 A2 "done when") ──

def _local_page(tmp_path):
    out = tmp_path / "r.html"
    payload = json.loads((GOLDEN / "share_payload.json").read_text(encoding="utf-8"))
    rr.render_from_payload(payload, str(out))
    return out.read_text(encoding="utf-8")


@pytest.mark.parametrize("gone", ["controls=0", "yt-overlay", "DM+Serif", "<script src=\"https://www.youtube.com/iframe_api\">", "ctrl-bar",
                                  "progress-track", "info-overlay", "help-overlay", "localhost:8765/reports"])
def test_local_build_has_no_old_player_or_bar(gone):
    assert gone not in TEMPLATE.read_text(encoding="utf-8")


def test_rendered_local_page_has_only_local_blocks(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "METADATA_DIR", tmp_path / "metadata")
    page = _local_page(tmp_path)
    assert '<html lang="" data-vl-mode="local">' in page
    assert "{{" not in page and "<!-- @" not in page and "GENERATED" not in page
    for share_only in ("{{ASSET", "Report this page", "/legal/", 'class="load"'):
        assert share_only not in page
    assert 'data-autoload' in page and 'id="file-note"' in page
    assert '<a class="brand" href="../index.html"' in page   # gallery: <root>/index.html, reports in <root>/reports/


def test_page_lang_and_duration_come_from_the_sidecar(tmp_path, monkeypatch):
    side = tmp_path / "metadata"
    side.mkdir()
    (side / "bjdBVZa66oU.json").write_text(json.dumps({"durationS": 754, "lang": "de"}))
    monkeypatch.setattr(rr, "METADATA_DIR", side)
    page = _local_page(tmp_path)
    assert '<html lang="de" data-vl-mode="local">' in page
    assert '<ol class="topics" data-duration="754">' in page


@pytest.mark.parametrize("duration,seconds", [("12 min", 720), ("1h 36m", 5760), ("12:34", 754), ("", 0), ("?", 0)])
def test_duration_falls_back_to_the_duration_text(tmp_path, monkeypatch, duration, seconds):
    monkeypatch.setattr(rr, "METADATA_DIR", tmp_path / "metadata")
    assert rr._duration_seconds({"DURATION": duration}, "bjdBVZa66oU") == seconds


def test_renderer_drops_share_blocks_and_the_generated_line():
    """Whether or not the build has already stripped them (035 §4.4 rule 4)."""
    src = ("<!-- GENERATED from viewer/. Do not edit. -->\n<!doctype html>\n<!-- @local -->\nL\n<!-- @end -->\n"
           "<!-- @share -->\n{{ASSET_JS}}\n<!-- @end -->\nX\n")
    assert rr._local_build(src) == "<!doctype html>\nL\nX\n"


# ── 036 §2: stable hooks for anything that reads report HTML ──

HOOKS = [
    r"<h1>",
    r'class="meta-line"',
    r'class="meta-facts"',
    r'<ol class="topics"',
    r'<a class="ts" data-t="\d+"',
    r'class="outline-title"',
    r'class="outline-detail"',
    r'<section id="summary"',
    r'<section id="takeaway"',
    r'<section id="key-points"',
    r'class="description-details"',
    r'<script type="application/json" id="video-lens-meta">',
]


@pytest.mark.parametrize("hook", HOOKS)
def test_stable_hooks_are_in_a_rendered_report(tmp_path, monkeypatch, hook):
    monkeypatch.setattr(rr, "METADATA_DIR", tmp_path / "metadata")
    payload = json.loads((GOLDEN / "share_payload.json").read_text(encoding="utf-8"))
    payload["OUTLINE"][1]["detail"] = "Some detail."
    payload["DESCRIPTION_SECTION"] = ('<details class="description-details"><summary>YouTube Description</summary>'
                                      '<div class="video-description">Text.</div></details>')
    out = tmp_path / "r.html"
    rr.render_from_payload(payload, str(out))
    assert re.search(hook, out.read_text(encoding="utf-8")), hook


@pytest.mark.parametrize("selector", ["h1", ".meta-line", ".meta-facts", "ol.topics", "a.ts[data-t]", ".outline-title",
                                      ".outline-detail", "#summary", "#takeaway", "#key-points",
                                      ".description-details", "#video-lens-meta"])
def test_stable_hooks_are_still_what_the_viewer_reads(selector):
    """The viewer is built on the same hooks; a rename in viewer/ must rename them everywhere."""
    name = selector.split("[")[0].lstrip(".#").split(".")[-1].split(" ")[-1]
    assert name in SHELL + JS + CSS, selector


# ── 037 A3: the player adapter and the one place the mode appears ──

ADAPTER = ["available", "load", "loaded", "ready", "seek", "toggle", "time", "duration", "onState",
           "shift", "rate", "mute", "captions", "fullscreen"]


def _function_body(text, header):
    """The source of the block that opens at `header` (up to its matching brace)."""
    start = text.index(header)
    i = text.index("{", start)
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    raise AssertionError("unbalanced braces after " + header)


@pytest.mark.parametrize("method", ADAPTER)
def test_player_adapter_has_every_method(method):
    adapter = _function_body(JS, "var player = {")
    assert re.search(r"\n      %s: function \(" % method, adapter), method


def test_script_never_reads_the_mode():
    """035 §4.3 / 036 §7: the adapter is the only fork; no other code may test the mode."""
    for token in ("data-vl-mode", "vlMode", "VL_MODE", "vl-mode"):
        assert token not in JS, token
    assert not re.search(r"getAttribute\(['\"]data-(vl-)?mode", JS)


# ── 037 D2 and §3.3: playback marks a key point and changes nothing else ──

def _now_selectors():
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    out = []
    for block in re.finditer(r"([^{}]+)\{[^{}]*\}", css):
        for sel in block.group(1).split(","):
            sel = sel.strip()
            if re.search(r"\.now(?![\w-])", sel):
                out.append(sel)
    return out


def test_now_is_a_pseudo_element_rule_only():
    sels = _now_selectors()
    assert sels, "the key-point marker rule is gone"
    for sel in sels:
        assert sel.endswith("::before"), sel
    assert ".kp-list > li.now::before" in sels


def test_now_playing_bar_label_does_not_use_the_key_point_class():
    assert 'class="nowbar-label"' in SHELL and 'class="now"' not in SHELL
    assert re.search(r"^\.nowbar-label\s*\{", CSS, flags=re.M)


def _time_update_path():
    """Source of tick, the player's state callback, and everything they call, found by name."""
    roots = [_function_body(JS, "function tick()"), _function_body(JS, "player.onState(function (state)")]
    seen = {}
    todo = list(roots)
    while todo:
        body = todo.pop()
        for name in set(re.findall(r"\b([A-Za-z_$][\w$]*)\(", body)):
            if name in seen or not re.search(r"\n\s*function %s\(" % re.escape(name), JS):
                continue
            seen[name] = _function_body(JS, "function %s(" % name)
            todo.append(seen[name])
    return roots, seen


def test_time_update_path_is_the_one_this_lint_expects():
    _, fns = _time_update_path()
    assert {"setActive", "paint", "showNow", "keepVisible", "indexAt"} <= set(fns)
    # Nothing that a click or a key starts is reachable from the time update.
    assert not {"go", "step", "toggleSkim", "toggleOutline", "setTab", "flag", "snap"} & set(fns)


def test_time_update_path_never_opens_skims_or_scrolls_key_points():
    roots, fns = _time_update_path()
    for name, body in [("tick", roots[0]), ("onState", roots[1])] + sorted(fns.items()):
        assert not re.search(r"""["']open["']|\.open\b|data-skim|\bhasAttribute\(|\bsetAttribute\(""", body), name
        assert not re.search(r"scrollIntoView|scrollTo\(|scrollBy\(|\.focus\(", body), name
        if name != "keepVisible":
            assert "scrollTop" not in body, name
        for m in re.finditer(r"classList\.(?:add|remove|toggle)\(\s*([^,)]+)", body):
            assert m.group(1).strip() in ('"now"', '"active"', '"done"', '"playing"'), (name, m.group(0))


def test_the_only_scroll_on_the_time_update_path_is_the_outlines_own_box():
    _, fns = _time_update_path()
    writes = re.findall(r"(\w+)\.scrollTop\s*=", fns["keepVisible"])
    assert writes and set(writes) == {"outlineEl"}
    assert 'outlineEl = $("outline")' in JS
    # The playing key point is marked, with the class and nothing more.
    assert re.search(r'p\.li\.classList\.toggle\("now"', fns["setActive"])


def test_playing_never_changes_what_a_key_point_shows():
    """Skim visibility depends on [data-skim] and .open (and the reader's buttons) only."""
    css = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    for block in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel = block.group(1)
        if "kp-list" in sel and (".now" in sel or ".active" in sel or ".playing" in sel):
            assert sel.strip().endswith("::before"), sel


# ── 037 D1: the text column is fluid ──

def test_masthead_and_doc_fill_their_pane():
    assert re.search(r"^\.masthead > \*, \.doc > \* \{ max-width: 100%; \}", CSS, flags=re.M)
    assert "41rem" not in CSS


# ── 037 D5, D6: keys and the speed button ──

def test_keys_seek_by_the_decided_amounts():
    assert 'case "j": if (ready) player.shift(-10)' in JS and 'case "l": if (ready) player.shift(10)' in JS
    assert 'case "ArrowLeft": if (ready) { e.preventDefault(); player.shift(-5)' in JS
    assert 'case "ArrowRight": if (ready) { e.preventDefault(); player.shift(5)' in JS
    assert "<dt><kbd>j</kbd> <kbd>l</kbd></dt><dd>Back or forward 10 s</dd>" in SHELL
    assert "<dt><kbd>←</kbd> <kbd>→</kbd></dt><dd>Back or forward 5 s</dd>" in SHELL


def test_speed_button_and_its_storage_key_stay():
    assert 'id="speed"' in SHELL
    assert 'speed: "video-lens:speed"' in JS
    assert "write(KEYS.speed" in JS


def test_playback_keys_before_the_player_loads_pulse_and_load_nothing():
    keys = _function_body(JS, 'document.addEventListener("keydown"')
    for k in "jlpn":
        assert re.search(r'case "%s":[^\n]*else hint\(\);' % k, keys), k
    assert 'else if (k === "k") hint();' in keys
    # Only a click on the panel (or a time) loads the player; no key handler calls load.
    assert "player.load(" not in keys
    # Space: when nothing is loaded toggle() returns false and the page scrolls.
    assert 'if (player.toggle()) e.preventDefault(); // before the player is loaded, Space still scrolls' in keys


# ── 037 §9 A2 row: the file:// note names the command and link serve_report.sh serves ──

def test_file_note_has_slots_for_the_command_and_the_link():
    assert 'id="file-cmd"' in SHELL and 'id="file-link"' in SHELL and 'id="file-note"' in SHELL
    assert 'location.protocol === "file:"' in JS
    assert 'folder === "reports"' in JS and '"reports/" + name' in JS
    assert 'href="http://localhost:8765/"' in SHELL   # the host stays in the shell; the script only appends the path
