#!/usr/bin/env python3
"""Render an HTML report by substituting JSON values into template.html.

Usage: echo '{"VIDEO_ID": "...", ...}' | python3 render_report.py OUTPUT_PATH

Reads JSON from stdin. Required keys:
    VIDEO_ID, VIDEO_TITLE, VIDEO_URL, META_LINE, SUMMARY,
    KEY_POINTS, TAKEAWAY, OUTLINE, DESCRIPTION_SECTION

Renderer builds VIDEO_LENS_META from agent-authored content. Optional fields:
    TAGS (list), CHANNEL, DURATION, PUBLISH_DATE, GENERATION_DATE,
    GENERATION_DURATION_SECONDS, AGENT_MODEL.

Discovers template.html via multi-agent path search.
"""
import html as html_lib
import json
import os
import pathlib
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

EXPECTED_KEYS = {
    "VIDEO_ID", "VIDEO_TITLE", "VIDEO_URL", "META_LINE", "SUMMARY",
    "KEY_POINTS", "TAKEAWAY", "OUTLINE", "DESCRIPTION_SECTION",
}

REQUIRED_NONEMPTY = (
    "SUMMARY", "KEY_POINTS", "OUTLINE", "TAKEAWAY",
    "VIDEO_ID", "VIDEO_TITLE",
)

PLAINTEXT_KEYS = ("VIDEO_TITLE", "META_LINE", "SUMMARY", "TAKEAWAY")
HTML_KEYS = ("KEY_POINTS", "OUTLINE", "DESCRIPTION_SECTION")

ALLOWED_TAGS_BY_KEY = {
    "KEY_POINTS": {
        "li": set(),
        "p": set(),
        "strong": set(),
        "em": set(),
    },
    "OUTLINE": {
        "li": set(),
        "a": {"href", "target", "rel", "class", "data-t"},
        "span": {"class"},
    },
    "DESCRIPTION_SECTION": {
        "details": {"class"},
        "summary": set(),
        "div": {"class"},
        "br": set(),
        "a": {"href", "target", "rel"},
        "p": set(),
        "strong": set(),
        "em": set(),
    },
}

ALLOWED_CLASSES_BY_TAG = {
    "a": {"ts"},
    "span": {"outline-title", "outline-detail"},
    "details": {"description-details"},
    "div": {"video-description"},
}

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
DATA_T_RE = re.compile(r"^\d{1,6}$")
ALLOWED_OUTPUT_ROOT = pathlib.Path.home() / "Downloads" / "video-lens" / "reports"
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
YOUTUBE_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}

AGENT_DIRS = ("agents", "claude", "copilot", "gemini", "cursor", "windsurf", "opencode", "codex")

SUMMARY_TRUNCATE_AT = 300


class RenderValidationError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class _Disallowed(Exception):
    pass


def find_template() -> pathlib.Path:
    """Find template.html — prefer the copy adjacent to this script, then search agent skill dirs."""
    local = pathlib.Path(__file__).resolve().parent.parent / "template.html"
    if local.exists():
        return local
    home = pathlib.Path.home()
    for agent in AGENT_DIRS:
        p = home / f".{agent}" / "skills" / "video-lens" / "template.html"
        if p.exists():
            return p
    raise FileNotFoundError(
        "template.html not found — install from github.com/kar2phi/video-lens (see Bundled scripts in SKILL.md)"
    )


def _extract_youtube_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if parsed.scheme != "https":
        return None
    if host in YOUTUBE_SHORT_HOSTS:
        candidate = parsed.path.strip("/").split("/", 1)[0]
        return candidate if VIDEO_ID_RE.fullmatch(candidate) else None
    if host not in YOUTUBE_HOSTS:
        return None

    if parsed.path == "/watch":
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    elif parsed.path.startswith("/embed/") or parsed.path.startswith("/live/"):
        parts = parsed.path.strip("/").split("/", 1)
        if len(parts) != 2:
            return None
        candidate = parts[1].split("/", 1)[0]
    else:
        return None
    return candidate if VIDEO_ID_RE.fullmatch(candidate) else None


def _canonical_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


class AllowlistSanitiser(HTMLParser):
    def __init__(self, key: str, video_id: str):
        super().__init__(convert_charrefs=False)
        self.key = key
        self.video_id = video_id
        self.allowed_tags = ALLOWED_TAGS_BY_KEY[key]
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag not in self.allowed_tags:
            raise _Disallowed(f"tag <{tag}>")

        allowed_attrs = self.allowed_tags[tag]
        kept = []
        href_seen = False
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            value = raw_value or ""

            if name.startswith("on"):
                raise _Disallowed(f"event handler {name} on <{tag}>")
            if name not in allowed_attrs:
                raise _Disallowed(f"attr {name} on <{tag}>")

            if name == "href":
                href_seen = True
                if self.key == "OUTLINE":
                    linked_id = _extract_youtube_id(value)
                    if linked_id != self.video_id:
                        raise _Disallowed(f"outline href {value!r}")
                elif not _is_http_url(value):
                    raise _Disallowed(f"href {value!r}")
                kept.append((name, value))
                continue

            if name == "target":
                if value != "_blank":
                    raise _Disallowed(f"target {value!r}")
                continue

            if name == "rel":
                rel_tokens = set(value.split())
                if not rel_tokens or not rel_tokens <= {"noopener", "noreferrer"}:
                    raise _Disallowed(f"rel {value!r}")
                continue

            if name == "class":
                allowed_classes = ALLOWED_CLASSES_BY_TAG.get(tag, set())
                tokens = (value or "").split()
                if not tokens or any(token not in allowed_classes for token in tokens):
                    raise _Disallowed(f"class {value!r}")
                kept.append((name, " ".join(tokens)))
                continue

            if name == "data-t":
                if self.key != "OUTLINE" or not DATA_T_RE.fullmatch(value):
                    raise _Disallowed(f"data-t {value!r}")
                kept.append((name, value))
                continue

        if tag == "a":
            if not href_seen:
                raise _Disallowed("a href missing")
            kept.append(("target", "_blank"))
            kept.append(("rel", "noopener noreferrer"))

        attr_str = "".join(
            f' {name}="{html_lib.escape(value, quote=True)}"'
            for name, value in kept
        )
        self.out.append(f"<{tag}{attr_str}>")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag not in self.allowed_tags:
            raise _Disallowed(f"tag </{tag}>")
        if tag != "br":
            self.out.append(f"</{tag}>")

    def handle_startendtag(self, tag, attrs):
        tag = tag.lower()
        self.handle_starttag(tag, attrs)
        if tag != "br":
            self.out.append(f"</{tag}>")

    def handle_data(self, data):
        self.out.append(html_lib.escape(data, quote=False))

    def handle_entityref(self, name):
        self.out.append(f"&{name};")

    def handle_charref(self, name):
        self.out.append(f"&#{name};")

    def handle_comment(self, data):
        raise _Disallowed("comment")

    def handle_decl(self, decl):
        raise _Disallowed("declaration")

    def unknown_decl(self, data):
        raise _Disallowed("declaration")

    def handle_pi(self, data):
        raise _Disallowed("processing instruction")


class _LIFirstStrongCollector(HTMLParser):
    """Collect text inside the first <strong> child of each top-level <li>.

    Per CH1 in concepts/017: a regex over all <strong> over-counts because
    KEY_POINTS uses <strong> for inline emphasis inside paragraph text too.
    Only the headline (first <strong> of each <li>) becomes a keyword.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_li = False
        self.first_strong_seen_in_current_li = False
        self.in_first_strong = False
        self.buf: list[str] = []
        self.out: list[str] = []

    def handle_starttag(self, tag, _attrs):
        if tag == "li":
            self.in_li = True
            self.first_strong_seen_in_current_li = False
        elif tag == "strong" and self.in_li and not self.first_strong_seen_in_current_li:
            self.first_strong_seen_in_current_li = True
            self.in_first_strong = True
            self.buf = []

    def handle_endtag(self, tag):
        if tag == "li":
            self.in_li = False
        elif tag == "strong" and self.in_first_strong:
            self.in_first_strong = False
            text = "".join(self.buf).strip()
            if text and text not in self.out:
                self.out.append(text)

    def handle_data(self, data):
        if self.in_first_strong:
            self.buf.append(data)


def _extract_keywords_from_key_points(clean_key_points_html: str) -> list[str]:
    collector = _LIFirstStrongCollector()
    collector.feed(clean_key_points_html)
    collector.close()
    return collector.out


def _truncate_summary(summary_raw: str, n: int = SUMMARY_TRUNCATE_AT) -> str:
    """Unescape HTML entities and truncate at the last word boundary at-or-before n."""
    s = html_lib.unescape(summary_raw)
    if len(s) <= n:
        return s
    cut = s.rfind(" ", 0, n)
    if cut == -1:
        cut = n
    return s[:cut].rstrip() + "…"


def _coerce_duration_seconds(value) -> int | None:
    """Return a non-negative integer duration, or None when omitted."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
        if not re.fullmatch(r"\d+", value):
            raise RenderValidationError(
                "RENDER_INVALID_META_JSON",
                "GENERATION_DURATION_SECONDS must be a non-negative integer",
            )
        return int(value)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RenderValidationError(
            "RENDER_INVALID_META_JSON",
            "GENERATION_DURATION_SECONDS must be a non-negative integer",
        )
    return value


def _build_meta_dict(raw_payload: dict, clean_key_points: str, output_path: str) -> dict:
    """Build the VIDEO_LENS_META dict from agent-authored payload + clean KEY_POINTS."""
    tags_raw = raw_payload.get("TAGS")
    if tags_raw is None:
        tags: list = []
    elif isinstance(tags_raw, list):
        tags = [str(t) for t in tags_raw if str(t).strip()]
    else:
        raise RenderValidationError("RENDER_INVALID_META_JSON", "TAGS must be a JSON array")

    duration_seconds = _coerce_duration_seconds(
        raw_payload.get("GENERATION_DURATION_SECONDS")
    )

    meta = {
        "videoId":        raw_payload["VIDEO_ID"],
        "title":          html_lib.unescape(str(raw_payload.get("VIDEO_TITLE", ""))),
        "channel":        str(raw_payload.get("CHANNEL", "")),
        "duration":       str(raw_payload.get("DURATION", "")),
        "publishDate":    str(raw_payload.get("PUBLISH_DATE", "")),
        "generationDate": str(raw_payload.get("GENERATION_DATE", "")),
        "summary":        _truncate_summary(str(raw_payload.get("SUMMARY", ""))),
        "tags":           tags,
        "keywords":       _extract_keywords_from_key_points(clean_key_points),
        "filename":       pathlib.Path(output_path).name,
        "agentModel":     str(raw_payload.get("AGENT_MODEL", "")),
        "generatedAt":    datetime.now(timezone.utc)
                                  .isoformat(timespec="seconds")
                                  .replace("+00:00", "Z"),
    }
    if duration_seconds is not None:
        meta["durationSeconds"] = duration_seconds
    return meta


def _serialize_meta(meta: dict) -> str:
    return json.dumps(meta, ensure_ascii=True).replace("</", "<\\/")


def sanitise_html(key: str, value: str, video_id: str) -> str:
    parser = AllowlistSanitiser(key, video_id)
    parser.feed(value)
    parser.close()
    return "".join(parser.out)


def sanitise_payload(data: dict, output_path: str = "") -> dict:
    video_id = str(data.get("VIDEO_ID", ""))
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise RenderValidationError("RENDER_INVALID_VIDEO_ID", f"invalid video id: {video_id!r}")

    video_url = str(data.get("VIDEO_URL", ""))
    linked_id = _extract_youtube_id(video_url)
    if linked_id != video_id:
        raise RenderValidationError("RENDER_INVALID_VIDEO_URL", f"invalid video url: {video_url!r}")

    clean = {}
    clean["VIDEO_ID"] = video_id
    clean["VIDEO_URL"] = _canonical_video_url(video_id)

    for key in PLAINTEXT_KEYS:
        clean[key] = html_lib.escape(str(data.get(key, "")), quote=False)

    for key in HTML_KEYS:
        try:
            clean[key] = sanitise_html(key, str(data.get(key, "")), video_id)
        except _Disallowed as e:
            raise RenderValidationError(
                "RENDER_DISALLOWED_HTML",
                f"key={key} reason={e}",
            ) from e

    meta = _build_meta_dict(data, clean["KEY_POINTS"], output_path)
    clean["VIDEO_LENS_META"] = _serialize_meta(meta)

    return clean


def validate_output_path(path: str) -> pathlib.Path:
    resolved = pathlib.Path(path).expanduser().resolve()
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("VIDEO_LENS_ALLOW_ANY_PATH") == "1":
        return resolved
    if resolved.suffix != ".html":
        raise RenderValidationError("RENDER_INVALID_OUTPUT_PATH", "must end in .html")
    try:
        resolved.relative_to(ALLOWED_OUTPUT_ROOT.resolve())
    except ValueError as e:
        raise RenderValidationError(
            "RENDER_INVALID_OUTPUT_PATH",
            f"must live under {ALLOWED_OUTPUT_ROOT}",
        ) from e
    return resolved


def _render_clean(data: dict, output_path: str, template_path: pathlib.Path | None = None) -> str:
    """Substitute pre-sanitised data into template and write to output_path.

    Private: callers in production code should use `render_from_payload` so the
    sanitiser cannot be bypassed. Exposed for tests that pre-build clean dicts.
    """
    if template_path is None:
        template_path = find_template()

    html = template_path.read_text(encoding="utf-8")
    for key, value in data.items():
        html = html.replace("{{" + key + "}}", value)

    remaining = re.findall(r"\{\{[A-Z_]+\}\}", html)
    if remaining:
        raise ValueError(f"RENDER_UNREPLACED_PLACEHOLDERS {sorted(set(remaining))}")

    out = pathlib.Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return str(out)


def render_from_payload(payload: dict, output_path: str,
                        template_path: pathlib.Path | None = None) -> str:
    """Sanitise an agent-authored payload and write the rendered HTML.

    This is the public entry point. `main()` uses it; new callers should too.
    """
    clean = sanitise_payload(payload, output_path)
    return _render_clean(clean, output_path, template_path=template_path)


def main():
    if len(sys.argv) != 2:
        print("Usage: echo '{...}' | render_report.py OUTPUT_PATH", file=sys.stderr)
        sys.exit(1)

    raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"ERROR:RENDER_INVALID_JSON {e}", file=sys.stderr)
        sys.exit(1)

    missing = EXPECTED_KEYS - set(data.keys())
    if missing:
        print(f"ERROR:RENDER_MISSING_KEYS {sorted(missing)}", file=sys.stderr)
        sys.exit(1)

    empty = [k for k in REQUIRED_NONEMPTY if not str(data.get(k, "")).strip()]
    if empty:
        print(f"ERROR:RENDER_EMPTY_CONTENT empty/whitespace keys: {empty}", file=sys.stderr)
        sys.exit(1)

    try:
        output_path = validate_output_path(sys.argv[1])
        result = render_from_payload(data, str(output_path))
    except RenderValidationError as e:
        print(f"ERROR:{e.code} {e.detail}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError as e:
        print(f"ERROR:RENDER_TEMPLATE_NOT_FOUND {e}", file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(f"ERROR:{e}", file=sys.stderr)
        sys.exit(1)

    print(f"Rendered → {result}")


if __name__ == "__main__":
    main()
