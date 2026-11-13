#!/usr/bin/env python3
"""Build the viewer from its single source in viewer/ (stdlib only).

  python3 tools/build_viewer.py --mode local          write skills/video-lens/template.html
  python3 tools/build_viewer.py --check               exit 1 when template.html is stale
  python3 tools/build_viewer.py --mode share --out D  write D/shell.html, D/viewer.css, D/viewer.js

The share shell keeps the Worker's slots ({{NAME}}, filled in one pass) and links the two
assets through {{ASSET_CSS}} / {{ASSET_JS}} (and {{ASSET_FONTS}}); nothing in it is inline code.
"""
import argparse
import re
import sys
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


def target(root):
    return Path(root) / "skills" / "video-lens" / "template.html"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["local", "share"], default="local")
    ap.add_argument("--out", help="share mode: the directory to write shell.html, viewer.css and viewer.js to")
    ap.add_argument("--check", action="store_true", help="exit 1 when the built file is stale")
    ap.add_argument("--root", default=str(ROOT), help="repo root (default: this repo)")
    a = ap.parse_args(argv)
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
        print("template.html is current")
        return 0
    dest.write_bytes(out.encode("utf-8"))
    print("wrote %s" % dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
