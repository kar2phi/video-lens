#!/usr/bin/env python3
"""Render an HTML report by substituting JSON values into template.html.

Usage: echo '{"VIDEO_ID": "...", ...}' | python3 render_report.py OUTPUT_PATH

Reads JSON from stdin with these keys:
    VIDEO_ID, VIDEO_TITLE, VIDEO_URL, META_LINE, SUMMARY,
    KEY_POINTS, TAKEAWAY, OUTLINE, DESCRIPTION_SECTION, VIDEO_LENS_META

Discovers template.html via multi-agent path search.
"""
import json
import pathlib
import re
import sys

EXPECTED_KEYS = {
    "VIDEO_ID", "VIDEO_TITLE", "VIDEO_URL", "META_LINE", "SUMMARY",
    "KEY_POINTS", "TAKEAWAY", "OUTLINE", "DESCRIPTION_SECTION", "VIDEO_LENS_META",
}

AGENT_DIRS = ("agents", "claude", "copilot", "gemini", "cursor", "windsurf", "opencode", "codex")


def find_template() -> pathlib.Path:
    """Search known agent skill directories for template.html."""
    home = pathlib.Path.home()
    for agent in AGENT_DIRS:
        prefix = "."
        p = home / f"{prefix}{agent}" / "skills" / "video-lens" / "template.html"
        if p.exists():
            return p
    raise FileNotFoundError(
        "template.html not found — run: npx skills add kar2phi/video-lens"
    )


def render(data: dict, output_path: str, template_path: pathlib.Path | None = None) -> str:
    """Substitute data into template and write to output_path. Returns the output path."""
    if template_path is None:
        template_path = find_template()

    html = template_path.read_text(encoding="utf-8")
    for key, value in data.items():
        html = html.replace("{{" + key + "}}", value)

    remaining = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if remaining:
        print(f"WARNING: unreplaced template placeholders: {remaining}", file=sys.stderr)

    out = pathlib.Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return str(out)


def main():
    if len(sys.argv) != 2:
        print("Usage: echo '{...}' | render_report.py OUTPUT_PATH", file=sys.stderr)
        sys.exit(1)

    output_path = sys.argv[1]

    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON on stdin: {e}", file=sys.stderr)
        sys.exit(1)

    missing = EXPECTED_KEYS - set(data.keys())
    if missing:
        print(f"WARNING: missing keys: {sorted(missing)}", file=sys.stderr)

    try:
        result = render(data, output_path)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Rendered → {result}")


if __name__ == "__main__":
    main()
