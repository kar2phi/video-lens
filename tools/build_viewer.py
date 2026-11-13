#!/usr/bin/env python3
"""Build the viewer from its single source in viewer/ (stdlib only).

  python3 tools/build_viewer.py --mode local   write skills/video-lens/template.html
  python3 tools/build_viewer.py --check        exit 1 when template.html is stale
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def build_local(root):
    src = Path(root) / "viewer"
    shell = (src / "shell.html").read_text(encoding="utf-8")
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
    return head + css + mid + js + tail


def target(root):
    return Path(root) / "skills" / "video-lens" / "template.html"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=["local"], default="local")
    ap.add_argument("--check", action="store_true", help="exit 1 when the built file is stale")
    ap.add_argument("--root", default=str(ROOT), help="repo root (default: this repo)")
    a = ap.parse_args(argv)
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
