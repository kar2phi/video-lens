#!/usr/bin/env python3
"""Build the viewer from its single source in viewer/ (stdlib only).

  python3 tools/build_viewer.py --mode local          write skills/video-lens/template.html
  python3 tools/build_viewer.py --check               exit 1 when template.html is stale
  python3 tools/build_viewer.py --mode share --out D  write D/shell.html, D/viewer.css, D/viewer.js
  python3 tools/build_viewer.py --vectors             write viewer/fragments.json (035 §4.5)

--check also fails when viewer/fragments.json differs from what --vectors writes.

The share shell keeps the Worker's slots ({{NAME}}, filled in one pass) and links the two
assets through {{ASSET_CSS}} / {{ASSET_JS}} (and {{ASSET_FONTS}}); nothing in it is inline code.
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED = "<!-- GENERATED from viewer/ by tools/build_viewer.py. Do not edit; edit viewer/ and rebuild. -->\n"


def _keep_mode(shell, mode):
    """035 §4.4 rule 4: drop the other mode's blocks, keep this mode's without the markers."""
    other = "share" if mode == "local" else "local"
    shell = re.sub(r"<!-- @%s -->.*?<!-- @end -->\n?" % other, "", shell, flags=re.S)
    return re.sub(r"<!-- @%s -->\n?|<!-- @end -->\n?" % mode, "", shell)


def build_local(root):
    src = Path(root) / "viewer"
    shell = _keep_mode((src / "shell.html").read_text(encoding="utf-8"), "local")
    css = (src / "viewer.css").read_text(encoding="utf-8")
    js = (src / "viewer.js").read_text(encoding="utf-8")
    for token in ("{{VL_CSS}}", "{{VL_JS}}"):
        if shell.count(token) != 1:
            raise SystemExit("shell.html must contain %s exactly once" % token)
    # Replace both slots in one pass over the shell so substituted text is never re-scanned.
    head, rest = shell.split("{{VL_CSS}}")
    mid, tail = rest.split("{{VL_JS}}") if "{{VL_JS}}" in rest else (None, None)
    if mid is None:
        raise SystemExit("{{VL_JS}} must come after {{VL_CSS}} in shell.html")
    return GENERATED + head + css + mid + js + tail


# What the share output must never contain (035 §4.3, 036 §7, 037 D3): the old player, Google
# Fonts, and any inline code or style. A script tag with src= is the only script there may be.
SHARE_FORBIDDEN = [
    ("yt-overlay", r"yt-overlay"),
    ("controls=0", r"controls=0"),
    ("fonts.googleapis.com", r"fonts\.googleapis\.com"),
    ("an inline <script>", r"<script(?![^>]*\ssrc=)"),
    ("a <style> element", r"<style"),
    ("a style= attribute", r"\sstyle\s*="),
    ("an on*= attribute", r"\son[a-z]+\s*="),
    ("data-autoload", r"data-autoload"),
    ("an @local/@share marker", r"<!-- @"),
]


def share_problems(shell, css, js):
    """The share lint: a list of what is wrong with a built share output (empty = clean)."""
    problems = []
    for what, pattern in SHARE_FORBIDDEN:
        if re.search(pattern, shell):
            problems.append("shell.html contains " + what)
    for what, pattern in SHARE_FORBIDDEN[:3]:
        for name, text in (("viewer.css", css), ("viewer.js", js)):
            if re.search(pattern, text):
                problems.append("%s contains %s" % (name, what))
    for name, text in (("viewer.css", css), ("viewer.js", js)):
        if "{{" in text:
            problems.append("%s contains a slot" % name)
    if 'data-vl-mode="share"' not in shell:
        problems.append('shell.html lacks data-vl-mode="share"')
    return problems


def build_share(root):
    """(shell, css, js) for the share page. The shell's slots are the Worker's to fill."""
    src = Path(root) / "viewer"
    shell = _keep_mode((src / "shell.html").read_text(encoding="utf-8"), "share")
    shell = shell.replace("{{VL_MODE}}", "share")   # a constant of this build, not a Worker slot
    css = (src / "viewer.css").read_text(encoding="utf-8")
    js = (src / "viewer.js").read_text(encoding="utf-8")
    problems = share_problems(shell, css, js)
    if problems:
        raise SystemExit("share build is not clean:\n  " + "\n  ".join(problems))
    return shell, css, js


# ── 035 §4.5: fragment vectors ──
# viewer/fragments.json pins the per-page fragments (outline, key points, summary, takeaway)
# for a payload v1, as exact bytes from the Python renderer. The Worker's tests assert the same
# bytes, so the local report and the share page cannot drift. Each payload is a validated,
# normalised payload v1 (all 17 keys, NFC), the form the Worker renders from.

VECTOR_BASE = {
    "v": 1, "videoId": "AAAAAAAAAAA", "title": "A made-up talk", "channel": "", "channelId": "",
    "duration": "", "durationS": None, "published": "", "lang": "", "tags": [],
    "summary": "Summary.", "takeaway": "Takeaway.",
    "keyPoints": [{"point": "Point", "why": "Why.", "detail": "Detail."}],
    "outline": [{"t": 0, "title": "Intro", "detail": ""}],
    "model": "", "notes": [], "created": "",
}


def _kp(point, why="", detail="", t=None):
    return ({"t": t} if t is not None else {}) | {"point": point, "why": why, "detail": detail}


def _ol(t, title, detail=""):
    return {"t": t, "title": title, "detail": detail}


VECTOR_CASES = [
    # M4: every place the two renderers disagreed before 037
    ("bold holding a star", {
        "summary": "**a*b** and x ** y ** z.",
        "takeaway": "2 * 3 * 4 stays text; so does a lone * and a lone `.",
        "keyPoints": [_kp("**a*b** headline", "**a*b**", "x ** y ** z")],
        "outline": [_ol(0, "**a*b**", "x ** y ** z")]}),
    ("paragraphs and line breaks", {
        "summary": "One **bold**.\n\nTwo\nlines.\n\n\n  Three, trimmed.  \n\n",
        "takeaway": "First\nsecond, **not\nbold** across a line.",
        "keyPoints": [_kp("Point", "A why with\na line break.", "Detail\n\nwith a blank line.")]}),
    ("markers", {
        "summary": "**bold**, *italic*, `code`, ***both***, *a **b** c*, **a *b* c**.",
        "takeaway": "`**not bold** in code` then **bold `code` inside**, `` empty, `open.",
        "keyPoints": [_kp("The **real** *cost* of `x`", "*w* **s** `c`", "** a** *a * **a **"),
                      _kp("`code` headline")],
        "outline": [_ol(0, "Disclosure **model** `code` *em*", "**b** *i* `c` `open")]}),
    ("quotes and ampersands", {
        "summary": "Tom's \"quote\" & <tag> &amp; &#39; > done.",
        "takeaway": "'single' \"double\" `<code & 'q'>`",
        "keyPoints": [_kp("A & B <tags>", "Quotes \"stay\" & 'too'.", "<script>alert(1)</script>")],
        "outline": [_ol(0, "Q&A: \"why\" <now>", "it's <b>not</b> bold")]}),
    ("empty why and detail", {
        "keyPoints": [_kp("Headline only"), _kp("Why only", why="Why."), _kp("Detail only", detail="Detail.")]}),
    ("empty outline", {
        "keyPoints": [_kp("No time")], "outline": []}),
    ("t over one hour", {
        "keyPoints": [_kp("Late point", "Why.", t=3725), _kp("End", t=86400)],
        "outline": [_ol(0, "Intro"), _ol(599, "Ten minutes"), _ol(3725, "One hour"), _ol(86400, "End")]}),
    ("key point t present and absent", {
        "keyPoints": [_kp("Timed", "Why.", "Detail.", t=754), _kp("Untimed", "Why.", "Detail."),
                      _kp("Timed at zero", t=0)],
        "outline": [_ol(0, "Intro", "Start."), _ol(754, "Middle")]}),
    ("6000 stars", {
        "summary": "*" * 6000, "takeaway": "*" * 2000,
        "keyPoints": [_kp("*" * 600, "*" * 1500, "*" * 4000)],
        "outline": [_ol(0, "*" * 300, "*" * 1500)]}),
    ("unicode and JavaScript whitespace", {
        "summary": "\ufeffCafé **naïve** *😀* 人工知能\ufeff\n\n\u3000Second\u00a0para\u3000",
        "takeaway": "*\ufeffx* *x\u00a0* **\u2003y** *\u2028z* stay text; *a\u2028b* is italic.",
        "keyPoints": [_kp("Emoji 🎙 **bold**", "*😀*", "`😀` **é**")],
        "outline": [_ol(0, "Tab\tand **mark**", "人工知能 *em*")]}),
]


def _golden_v1(root):
    """Payload v1 of the golden report (tests/golden/share_payload.json), as the renderer's data
    block writes it, with no metadata sidecar."""
    sys.path.insert(0, str(Path(root) / "skills" / "video-lens" / "scripts"))
    import render_report as rr
    payload = json.loads((Path(root) / "tests" / "golden" / "share_payload.json").read_text(encoding="utf-8"))
    saved = rr.METADATA_DIR
    with tempfile.TemporaryDirectory() as tmp:
        rr.METADATA_DIR = Path(tmp) / "none"
        try:
            clean = rr.sanitise_payload(payload, "golden.html")
        finally:
            rr.METADATA_DIR = saved
    raw = re.search(r'id="video-lens-data">(.*?)</script>', clean["VIDEO_LENS_DATA"], re.S).group(1)
    return json.loads(raw.replace("<\\/", "</")), rr


def build_vectors(root=ROOT):
    """viewer/fragments.json as text: [{name, payload, expect: {outline, keyPoints, summary, takeaway}}]."""
    golden, rr = _golden_v1(ROOT)   # the renderer and golden payload of this repo, whatever --root says
    cases = [("golden payload", golden)]
    cases += [(name, {**VECTOR_BASE, **patch}) for name, patch in VECTOR_CASES]
    out = [{"name": name, "payload": payload, "expect": rr.fragments(payload)} for name, payload in cases]
    return json.dumps(out, ensure_ascii=True, indent=1) + "\n"   # ASCII: invisible characters stay visible


def vectors_path(root):
    return Path(root) / "viewer" / "fragments.json"


def target(root):
    return Path(root) / "skills" / "video-lens" / "template.html"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["local", "share"], default="local")
    ap.add_argument("--out", help="share mode: the directory to write shell.html, viewer.css and viewer.js to")
    ap.add_argument("--check", action="store_true", help="exit 1 when the built file or the vectors are stale")
    ap.add_argument("--vectors", action="store_true", help="write viewer/fragments.json from the Python renderer")
    ap.add_argument("--root", default=str(ROOT), help="repo root (default: this repo)")
    a = ap.parse_args(argv)
    if a.vectors:
        dest = vectors_path(a.root)
        dest.write_bytes(build_vectors(a.root).encode("utf-8"))
        print("wrote %s" % dest)
        return 0
    if a.mode == "share":
        if a.check or not a.out:
            ap.error("--mode share needs --out DIR (and has no --check)")
        built = build_share(a.root)   # refuses an unclean source before anything is written
        outdir = Path(a.out)
        outdir.mkdir(parents=True, exist_ok=True)
        for name, text in zip(("shell.html", "viewer.css", "viewer.js"), built):
            (outdir / name).write_bytes(text.encode("utf-8"))
        print("wrote %s/{shell.html,viewer.css,viewer.js}" % outdir)
        return 0
    out = build_local(a.root)
    dest = target(a.root)
    if a.check:
        cur = dest.read_bytes() if dest.exists() else None
        if cur != out.encode("utf-8"):
            print("STALE: %s differs from the viewer/ sources; run: python3 tools/build_viewer.py --mode local" % dest, file=sys.stderr)
            return 1
        vec = vectors_path(a.root)
        if (vec.read_bytes() if vec.exists() else None) != build_vectors(a.root).encode("utf-8"):
            print("STALE: %s differs from the renderer; run: python3 tools/build_viewer.py --vectors" % vec, file=sys.stderr)
            return 1
        print("template.html and fragments.json are current")
        return 0
    dest.write_bytes(out.encode("utf-8"))
    print("wrote %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
