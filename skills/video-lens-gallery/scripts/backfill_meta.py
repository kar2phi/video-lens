#!/usr/bin/env python3
"""Backfill video-lens-meta blocks into existing reports that lack them.

Usage: python3 backfill_meta.py --dir DIR [--dry-run]

Scans DIR for *video-lens*.html files without a <script id="video-lens-meta">
block, extracts available metadata from the HTML structure, injects the block,
and writes the file back.

Note: tags will be empty for backfilled reports (cannot be generated retroactively).
"""
import argparse
import json
import pathlib
import re
import sys


META_SCRIPT_START = '<script type="application/json" id="video-lens-meta">'


def extract_video_id(html: str) -> str:
    """Extract YouTube video ID from iframe embed or outline links."""
    # iframe src="https://www.youtube.com/embed/VIDEO_ID"
    m = re.search(r'youtube\.com/embed/([A-Za-z0-9_-]{11})', html)
    if m:
        return m.group(1)
    # href="https://www.youtube.com/watch?v=VIDEO_ID"
    m = re.search(r'youtube\.com/watch\?v=([A-Za-z0-9_-]{11})', html)
    if m:
        return m.group(1)
    return ""


def extract_title(html: str) -> str:
    """Extract plain-text title from <title> tag."""
    m = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    if m:
        raw = m.group(1).strip()
        # Remove " — video-lens" suffix if present
        raw = re.sub(r'\s*[—–-]+\s*video.lens\s*$', '', raw, flags=re.IGNORECASE)
        return unescape_html(raw)
    return ""


_DURATION_RE = re.compile(r'^\d+\s*(min|h\b)', re.IGNORECASE)
_DATE_RE = re.compile(
    r'^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d+\s+\d{4}$'
    r'|^\d{4}-\d{2}-\d{2}$',
    re.IGNORECASE,
)


def _looks_like_duration_or_date(s: str) -> bool:
    return bool(_DURATION_RE.match(s) or _DATE_RE.match(s))


def extract_meta_line_parts(html: str) -> tuple[str, str, str]:
    """Extract channel, duration, publishDate from the meta-line element."""
    # <p class="meta-line">Channel · Duration · Date · Views</p>
    m = re.search(r'class="meta-line"[^>]*>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
    if not m:
        return "", "", ""
    raw = re.sub(r'<[^>]+>', '', m.group(1)).strip()
    raw = unescape_html(raw)  # converts &middot; → · (and other entities)
    parts = [p.strip() for p in raw.split('·')]
    # Drop trailing "Open on YouTube ↗" fragment that the template appends after META_LINE
    parts = [p for p in parts if '↗' not in p and 'youtube' not in p.lower()]
    channel = parts[0] if len(parts) > 0 else ""
    duration = parts[1] if len(parts) > 1 else ""
    pub_date = parts[2] if len(parts) > 2 else ""
    # If channel looks like a duration or date, META_LINE had no channel prefix — shift
    if _looks_like_duration_or_date(channel):
        duration = parts[0] if len(parts) > 0 else ""
        pub_date = parts[1] if len(parts) > 1 else ""
        channel = ""
    return channel, duration, pub_date


def extract_summary(html: str) -> str:
    """Extract plain text of the first <p> in the summary section."""
    m = re.search(r'id="summary".*?<p>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
    if m:
        raw = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        return unescape_html(raw[:400])
    return ""


def extract_keywords(html: str) -> list[str]:
    """Extract <strong> headline text from key-points section."""
    kp_m = re.search(r'id="key-points"(.*?)</section>', html, re.DOTALL | re.IGNORECASE)
    if not kp_m:
        return []
    kp_html = kp_m.group(1)
    strongs = re.findall(r'<strong>(.*?)</strong>', kp_html, re.DOTALL)
    keywords = []
    for s in strongs:
        plain = re.sub(r'<[^>]+>', '', s).strip()
        plain = unescape_html(plain)
        # Strip " — ..." suffix that sometimes appears in the strong tag
        plain = re.split(r'\s+[—–]\s+', plain)[0].strip()
        if plain:
            keywords.append(plain)
    return keywords[:10]


def parse_gen_date(filename: str) -> str:
    """Parse YYYY-MM-DD from filename like 2026-03-06-210126-video-lens_*.html"""
    m = re.match(r'^(\d{4}-\d{2}-\d{2})', filename)
    return m.group(1) if m else ""


def unescape_html(s: str) -> str:
    """Basic HTML entity unescaping."""
    replacements = {
        '&amp;': '&', '&lt;': '<', '&gt;': '>',
        '&quot;': '"', '&#39;': "'", '&apos;': "'",
        '&mdash;': '—', '&ndash;': '–', '&ldquo;': '"', '&rdquo;': '"',
        '&lsquo;': "'", '&rsquo;': "'", '&hellip;': '…', '&middot;': '·',
    }
    for entity, char in replacements.items():
        s = s.replace(entity, char)
    # Numeric entities
    s = re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), s)
    return s


def backfill_file(path: pathlib.Path, dry_run: bool) -> bool:
    """Add video-lens-meta block to a report file. Returns True if modified."""
    html = path.read_text(encoding="utf-8", errors="replace")

    if META_SCRIPT_START in html:
        return False  # already has meta block

    video_id = extract_video_id(html)
    title = extract_title(html)
    channel, duration, pub_date = extract_meta_line_parts(html)
    gen_date = parse_gen_date(path.name)
    summary = extract_summary(html)
    keywords = extract_keywords(html)

    meta_obj = {
        "videoId": video_id,
        "title": title,
        "channel": channel,
        "duration": duration,
        "publishDate": pub_date,
        "generationDate": gen_date,
        "summary": summary,
        "tags": [],  # cannot generate retroactively
        "keywords": keywords,
        "filename": path.name,
    }

    meta_block = f'{META_SCRIPT_START}{json.dumps(meta_obj, ensure_ascii=False)}</script>'
    new_html = html.replace('</body>', f'{meta_block}\n</body>', 1)

    if new_html == html:
        print(f"WARN: could not find </body> in {path.name}", file=sys.stderr)
        return False

    if not dry_run:
        path.write_text(new_html, encoding="utf-8")

    return True


def main():
    parser = argparse.ArgumentParser(description="Backfill video-lens-meta into existing reports")
    parser.add_argument("--dir", required=True, help="Directory containing video-lens HTML reports")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be changed without writing")
    args = parser.parse_args()

    scan_dir = pathlib.Path(args.dir).expanduser().resolve()
    if not scan_dir.is_dir():
        print(f"ERROR: directory not found: {scan_dir}", file=sys.stderr)
        sys.exit(1)

    # Reports live in scan_dir/reports/ since the directory reorganisation, but
    # older reports may still sit at the legacy flat location. Scan both.
    candidates = list(scan_dir.glob("*video-lens*.html"))
    candidates.extend((scan_dir / "reports").glob("*video-lens*.html"))
    seen: set[str] = set()
    report_files: list[pathlib.Path] = []
    for p in sorted(candidates):
        if p.name in seen:
            continue
        seen.add(p.name)
        report_files.append(p)

    modified = 0
    skipped = 0

    for path in report_files:
        if path.name == "index.html":
            continue
        changed = backfill_file(path, dry_run=args.dry_run)
        if changed:
            modified += 1
            action = "would update" if args.dry_run else "updated"
            print(f"{action}: {path.name}")
        else:
            skipped += 1

    print(f"\nDone: {modified} {'would be ' if args.dry_run else ''}updated, {skipped} already had meta block or skipped.")


if __name__ == "__main__":
    main()
