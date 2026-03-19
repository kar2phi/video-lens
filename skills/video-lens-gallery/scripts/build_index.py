#!/usr/bin/env python3
"""Build a manifest.json index from video-lens HTML reports in a directory.

Usage: python3 build_index.py --dir DIR [--output DIR]

Scans DIR for *video-lens*.html files, extracts the embedded
<script id="video-lens-meta"> JSON block from each, and writes manifest.json
to --output (defaults to --dir). Also copies index.html to the output directory
if it is not already present.
"""
import argparse
import json
import pathlib
import re
import shutil
import sys
from datetime import datetime, timezone


SCRIPT_START = '<script type="application/json" id="video-lens-meta">'
SCRIPT_END = "</script>"

_CHAN_DURATION_RE = re.compile(r'^\d+\s*(min|h\b)', re.IGNORECASE)
_CHAN_DATE_RE = re.compile(
    r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d',
    re.IGNORECASE,
)


def _sanitize_channel(value: str) -> str:
    """Return empty string if value is obviously not a channel name."""
    if not value:
        return ""
    # Stored as literal HTML entity — full meta-line was used as channel
    if "&middot;" in value:
        return ""
    # Multiple middle-dots → full meta-line accidentally stored as channel
    if value.count("·") >= 2:
        return ""
    # Duration like "18 min" or "1h 16m"
    if _CHAN_DURATION_RE.match(value):
        return ""
    # Date like "Mar 10 2026"
    if _CHAN_DATE_RE.match(value):
        return ""
    return value


def extract_meta(path: pathlib.Path) -> dict | None:
    """Extract the video-lens-meta JSON block from an HTML report file."""
    content = path.read_text(encoding="utf-8", errors="replace")
    i = content.find(SCRIPT_START)
    if i == -1:
        return None
    i += len(SCRIPT_START)
    j = content.find(SCRIPT_END, i)
    if j == -1:
        return None
    raw = content[i:j].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"WARNING: invalid JSON in {path.name}: {e}", file=sys.stderr)
        return None


def find_index_html() -> pathlib.Path | None:
    """Find index.html co-located with this script (deployed skill location)."""
    # In the deployed skill, index.html lives alongside SKILL.md, one level up from scripts/
    candidates = [
        pathlib.Path(__file__).parent.parent / "index.html",  # skills/video-lens-gallery/index.html
        pathlib.Path(__file__).parent / "index.html",          # scripts/index.html (fallback)
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def main():
    parser = argparse.ArgumentParser(description="Build video-lens manifest.json")
    parser.add_argument("--dir", required=True, help="Directory containing video-lens HTML reports")
    parser.add_argument("--output", help="Directory to write manifest.json (default: same as --dir)")
    args = parser.parse_args()

    scan_dir = pathlib.Path(args.dir).expanduser().resolve()
    out_dir = pathlib.Path(args.output).expanduser().resolve() if args.output else scan_dir

    if not scan_dir.is_dir():
        print(f"ERROR: directory not found: {scan_dir}", file=sys.stderr)
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)

    seen = set()
    reports = []
    skipped = 0

    # Phase 1: reports/ subdir (new location)
    reports_subdir = scan_dir / "reports"
    if reports_subdir.is_dir():
        for path in sorted(reports_subdir.glob("*video-lens*.html"),
                           key=lambda p: p.name, reverse=True):
            meta = extract_meta(path)
            if meta is None:
                skipped += 1
                print(f"SKIP (no meta block): reports/{path.name}", file=sys.stderr)
                continue
            meta["filename"] = "reports/" + path.name
            seen.add(path.name)
            meta["channel"] = _sanitize_channel(meta.get("channel", ""))
            reports.append(meta)

    # Phase 2: root (backward compat — old flat layout)
    for path in sorted(scan_dir.glob("*video-lens*.html"),
                       key=lambda p: p.name, reverse=True):
        if path.name == "index.html" or path.name in seen:
            continue
        meta = extract_meta(path)
        if meta is None:
            skipped += 1
            print(f"SKIP (no meta block): {path.name}", file=sys.stderr)
            continue
        if not meta.get("filename"):
            meta["filename"] = path.name
        meta["channel"] = _sanitize_channel(meta.get("channel", ""))
        reports.append(meta)

    # Re-sort combined list newest-first
    reports.sort(key=lambda m: m.get("filename", ""), reverse=True)

    manifest = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(reports),
        "reports": reports,
    }

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifest.json → {manifest_path}  ({len(reports)} reports, {skipped} skipped)")

    # Write index.html with manifest inlined as window.__MANIFEST__ so it works
    # from file:// as well as http://localhost:8765/
    index_src = find_index_html()
    index_dst = out_dir / "index.html"
    if index_src:
        index_html = index_src.read_text(encoding="utf-8")
        safe_json = json.dumps(manifest, ensure_ascii=False).replace("</", "<\\/")
        inline_script = (
            "<script>window.__MANIFEST__ = "
            + safe_json
            + ";</script>"
        )
        # Insert inline script just before the first <script> tag in <body>
        patched = index_html.replace("<script>\n(function", inline_script + "\n<script>\n(function", 1)
        if patched == index_html:
            # fallback: inject before </body>
            patched = index_html.replace("</body>", inline_script + "\n</body>", 1)
        index_dst.write_text(patched, encoding="utf-8")
        print(f"index.html → {index_dst}")


if __name__ == "__main__":
    main()
