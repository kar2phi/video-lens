#!/usr/bin/env python3
"""Render an HTML report by substituting JSON values into template.html.

Usage:
    echo '{"VIDEO_ID": "...", ...}' | python3 render_report.py OUTPUT_PATH
    echo '{"VIDEO_ID": "...", ...}' | python3 render_report.py --output-dir DIR
    python3 render_report.py --payload-file payload.json --output-dir DIR
    python3 render_report.py --payload-file payload.json --replace EXISTING.html

Reads JSON from stdin, or from `--payload-file PATH` (use the file form when
the payload contains double quotes — shells/heredocs mangle them). Required keys:
    VIDEO_ID, VIDEO_TITLE, VIDEO_URL, SUMMARY,
    KEY_POINTS, TAKEAWAY, OUTLINE, DESCRIPTION_SECTION

KEY_POINTS and OUTLINE are JSON arrays of objects (025-R1):
    KEY_POINTS: [{"point": "…", "why": "…", "detail": "…"}]   **bold**, *italic*, `code`
    OUTLINE:    [{"t": 754, "title": "…", "detail": "…"}]     t in seconds (or "12:34")
The renderer escapes their text and builds the same HTML a model used to write by
hand, links and timestamps included. An HTML string (the older contract) still works.

Renderer builds VIDEO_LENS_META from agent-authored content. Optional fields:
    META_LINE (auto-composed from CHANNEL/DURATION/PUBLISH_DATE/VIEWS if omitted),
    TAGS (list), CHANNEL, CHANNEL_ID, DURATION, PUBLISH_DATE, VIEWS, GENERATION_DATE,
    GENERATION_DURATION_SECONDS, GENERATION_START_EPOCH, AGENT_MODEL,
    SLUG_HINT (ascii slug used for filename when title has no ascii letters).

With --output-dir, the renderer derives the filename
``YYYY-MM-DD-HHMMSS-video-lens_<VIDEO_ID>_<slug>.html`` from VIDEO_TITLE,
VIDEO_ID, and GENERATION_DATE. With --replace, a revision overwrites an existing
report for the same video; it keeps that report's generation date and time.

Discovers template.html via multi-agent path search.
"""
import argparse
import html as html_lib
import json
import os
import pathlib
import re
import sys
import time
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

EXPECTED_KEYS = {
    "VIDEO_ID", "VIDEO_TITLE", "VIDEO_URL", "SUMMARY",
    "KEY_POINTS", "TAKEAWAY", "OUTLINE", "DESCRIPTION_SECTION",
}

REQUIRED_NONEMPTY = (
    "SUMMARY", "KEY_POINTS", "OUTLINE", "TAKEAWAY",
    "VIDEO_ID", "VIDEO_TITLE",
)


def _schema_help() -> str:
    return (
        "EXPECTED_KEYS=" + ",".join(sorted(EXPECTED_KEYS))
        + " REQUIRED_NONEMPTY=" + ",".join(REQUIRED_NONEMPTY)
        + ' KEY_POINTS=[{"point","why","detail"}] OUTLINE=[{"t" (seconds),"title","detail"}]'
        + " GENERATION_DATE optional (YYYY-MM-DD; defaults to today with --output-dir)"
    )

PLAINTEXT_KEYS = ("VIDEO_TITLE", "META_LINE", "SUMMARY", "TAKEAWAY")
HTML_KEYS = ("KEY_POINTS", "OUTLINE", "DESCRIPTION_SECTION")

ALLOWED_TAGS_BY_KEY = {
    "KEY_POINTS": {
        "li": set(),
        "p": set(),
        "strong": set(),
        "em": set(),
        "code": set(),
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
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
# Written by fetch_metadata.py; the channel id comes from there unless the payload has one.
METADATA_DIR = (
    pathlib.Path(os.environ.get("XDG_CACHE_HOME") or (pathlib.Path.home() / ".cache"))
    / "video-lens" / "metadata"
)
DATA_T_RE = re.compile(r"^\d{1,6}$")
ALLOWED_OUTPUT_ROOT = pathlib.Path.home() / "Downloads" / "video-lens" / "reports"
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
YOUTUBE_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}

AGENT_DIRS = ("agents", "claude", "copilot", "gemini", "cursor", "windsurf", "opencode", "codex")

SUMMARY_TRUNCATE_AT = 300

META_BLOCK_RE = re.compile(r'id="video-lens-meta">(.*?)</script>', re.S)


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
    if parsed.scheme not in {"http", "https"}:
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


META_LINE_FIELDS = ("CHANNEL", "DURATION", "PUBLISH_DATE", "VIEWS")


def _maybe_compose_meta_line(payload: dict) -> str:
    existing = str(payload.get("META_LINE", "")).strip()
    if existing:
        return existing
    parts = [str(payload.get(k, "")).strip() for k in META_LINE_FIELDS]
    return " · ".join(p for p in parts if p)


def _clean_agent_model(value) -> str:
    """Drop harness decoration such as the `[1m]` context-window suffix.

    `claude-opus-5[1m]` and `claude-opus-5` are one model; the gallery groups
    re-runs by this field, so the suffix would split them.
    """
    return re.sub(r"\s*\[[^\]]*\]", "", str(value)).strip()


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


def _normalize_tags(tags: list) -> list:
    """Fold trivial tag variants: lowercase, hyphen→space, collapse whitespace,
    dedupe (first-seen order). Non-str entries are dropped. Kept byte-identical to
    `preflight._normalize_tags` and `build_index._normalize_tags` so a new report
    embeds the same tag shape the feedback loop counts and the gallery folds.
    """
    seen = set()
    out = []
    for tag in tags:
        if not isinstance(tag, str):
            continue
        norm = " ".join(tag.replace("-", " ").lower().split())
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def _channel_id(raw_payload: dict) -> str:
    """CHANNEL_ID from the payload, else from fetch_metadata.py's sidecar; '' if neither
    is a valid UC… id. Never fails the render."""
    value = str(raw_payload.get("CHANNEL_ID", "")).strip()
    if CHANNEL_ID_RE.fullmatch(value):
        return value
    video_id = str(raw_payload.get("VIDEO_ID", ""))
    if not VIDEO_ID_RE.fullmatch(video_id):
        return ""
    try:
        sidecar = json.loads((METADATA_DIR / f"{video_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    value = str(sidecar.get("channelId", "")) if isinstance(sidecar, dict) else ""
    return value if CHANNEL_ID_RE.fullmatch(value) else ""


def _build_meta_dict(raw_payload: dict, clean_key_points: str, output_path: str) -> dict:
    """Build the VIDEO_LENS_META dict from agent-authored payload + clean KEY_POINTS."""
    tags_raw = raw_payload.get("TAGS")
    if tags_raw is None:
        tags: list = []
    elif isinstance(tags_raw, list):
        tags = _normalize_tags(tags_raw)
    else:
        raise RenderValidationError("RENDER_INVALID_META_JSON", "TAGS must be a JSON array")

    if raw_payload.get("GENERATION_DURATION_SECONDS") in (None, ""):
        start_epoch = raw_payload.get("GENERATION_START_EPOCH")
        if start_epoch not in (None, ""):
            try:
                se = int(start_epoch)
                if se < 0:
                    raise ValueError
            except (TypeError, ValueError):
                raise RenderValidationError(
                    "RENDER_INVALID_META_JSON",
                    "GENERATION_START_EPOCH must be a non-negative integer",
                )
            raw_payload = {
                **raw_payload,
                "GENERATION_DURATION_SECONDS": max(0, int(time.time()) - se),
            }

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
        "agentModel":     _clean_agent_model(raw_payload.get("AGENT_MODEL", "")),
        "generatedAt":    datetime.now(timezone.utc)
                                  .isoformat(timespec="seconds")
                                  .replace("+00:00", "Z"),
    }
    if duration_seconds is not None:
        meta["durationSeconds"] = duration_seconds
    channel_id = _channel_id(raw_payload)
    if channel_id:
        meta["channelId"] = channel_id
    return meta


def _serialize_meta(meta: dict) -> str:
    return json.dumps(meta, ensure_ascii=True).replace("</", "<\\/")


ITEM_FIELDS = {"KEY_POINTS": ("point", "why", "detail"), "OUTLINE": ("t", "title", "detail")}
CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
BOLD_RE = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
ITALIC_RE = re.compile(r"\*(?=\S)(.+?)(?<=\S)\*")
CLOCK_RE = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})")
# Inline tags a model used to the HTML-string contract may still type; read as their markers.
OLD_INLINE_TAGS = {"strong": "**", "b": "**", "em": "*", "i": "*", "code": "`"}
OLD_INLINE_TAG_RE = re.compile(r"<(strong|b|em|i|code)>(.*?)</\1>", re.I | re.S)


def _as_markers(text: str) -> str:
    return OLD_INLINE_TAG_RE.sub(lambda m: f"{OLD_INLINE_TAGS[m.group(1).lower()]}{m.group(2)}"
                                           f"{OLD_INLINE_TAGS[m.group(1).lower()]}", text)


def _inline_html(text: str, bold: bool = True) -> str:
    """Escape text, then turn **bold**, *italic* and `code` into tags; nothing else
    becomes markup. bold=False drops the ** markers (for a headline that is bold already)."""
    out = []
    for i, part in enumerate(CODE_SPAN_RE.split(_as_markers(text))):
        escaped = html_lib.escape(part, quote=False)
        if i % 2:
            out.append(f"<code>{escaped}</code>")
            continue
        escaped = BOLD_RE.sub(r"<strong>\1</strong>" if bold else r"\1", escaped)
        out.append(ITALIC_RE.sub(r"<em>\1</em>", escaped))
    return "".join(out)


def _plain_html(text: str) -> str:
    """Escape text and drop inline markers: outline spans allow no inline tags."""
    text = ITALIC_RE.sub(r"\1", BOLD_RE.sub(r"\1", CODE_SPAN_RE.sub(r"\1", _as_markers(text))))
    return html_lib.escape(text, quote=False)


def _clock(seconds: int) -> str:
    """The transcript's own timestamp format: M:SS, or H:MM:SS from one hour on."""
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _item_error(key: str, detail: str) -> RenderValidationError:
    shape = ", ".join(ITEM_FIELDS[key])
    return RenderValidationError(
        "RENDER_INVALID_ITEM",
        f"{detail}. Each {key} item is an object with {shape}; fix that item, re-Write the payload and retry.",
    )


def _item_text(key: str, i: int, item: dict, field: str, required: bool = False) -> str:
    value = item.get(field, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise _item_error(key, f"{key}[{i}].{field} must be a string, got {type(value).__name__}")
    if required and not value.strip():
        raise _item_error(key, f'{key}[{i}] needs a non-empty "{field}"')
    return value.strip()


def _item_seconds(i: int, value) -> int:
    """Outline start time: seconds as a number, a digit string, or an M:SS / H:MM:SS clock."""
    seconds = None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        seconds = int(value)
    elif isinstance(value, str):
        text = value.strip().strip("[]▶ ")
        clock = CLOCK_RE.fullmatch(text)
        if text.isdigit():
            seconds = int(text)
        elif clock:
            h, m, s = clock.groups()
            seconds = int(h or 0) * 3600 + int(m) * 60 + int(s)
    if seconds is None or seconds >= 10 ** 6:
        raise _item_error("OUTLINE", f"OUTLINE[{i}].t must be the start in seconds, e.g. 754, got {value!r}")
    return seconds


def _key_point_html(i: int, item: dict) -> str:
    point = _item_text("KEY_POINTS", i, item, "point", required=True)
    why = _item_text("KEY_POINTS", i, item, "why")
    detail = _item_text("KEY_POINTS", i, item, "detail")
    li = f"<li><strong>{_inline_html(point, bold=False)}</strong>"
    if why:
        li += f" — {_inline_html(why)}"
    if detail:
        li += f"<p>{_inline_html(detail)}</p>"
    return li + "</li>"


def _outline_html(i: int, item: dict, video_id: str) -> str:
    if "t" not in item:
        raise _item_error("OUTLINE", f"OUTLINE[{i}].t is missing")
    t = _item_seconds(i, item["t"])
    title = _item_text("OUTLINE", i, item, "title", required=True)
    detail = _item_text("OUTLINE", i, item, "detail")
    li = (f'<li><a class="ts" data-t="{t}" href="{_canonical_video_url(video_id)}&amp;t={t}" '
          f'target="_blank" rel="noopener noreferrer">▶ {_clock(t)}</a> — '
          f'<span class="outline-title">{_plain_html(title)}</span>')
    if detail:
        li += f'<span class="outline-detail">{_plain_html(detail)}</span>'
    return li + "</li>"


def items_to_html(key: str, items: list, video_id: str) -> str:
    """025-R1: build the KEY_POINTS or OUTLINE HTML string from a JSON array.

    Objects become exactly the markup a model writes by hand, which then goes
    through the same sanitiser. A list of HTML strings (the old contract, written
    as an array) is joined.
    """
    if not items:
        raise RenderValidationError("RENDER_PAYLOAD_INVALID", f"empty_keys=['{key}']")
    if all(isinstance(item, str) and item.lstrip().lower().startswith("<li") for item in items):
        return "".join(items)
    if any(isinstance(item, dict) for item in items) and any(isinstance(item, str) for item in items):
        raise _item_error(key, f"{key} mixes strings and objects")
    parts = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise _item_error(key, f"{key}[{i}] is {type(item).__name__}, not an object")
        unknown = sorted(set(item) - set(ITEM_FIELDS[key]))
        if unknown:
            raise _item_error(key, f"{key}[{i}] has unknown key {unknown[0]!r}")
        parts.append(_key_point_html(i, item) if key == "KEY_POINTS" else _outline_html(i, item, video_id))
    return "".join(parts)


LINT_MARKER = ".render-lint"   # in the payload's per-run directory: the lint has stopped once
DURATION_RE = re.compile(r"(?:(\d+)h\s*)?(\d+)\s*m(?:in)?")


class _TopLevelItems(HTMLParser):
    """For each top-level <li>: whether it holds a <p> (a Key Point's detail)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.has_p: list[bool] = []

    def handle_starttag(self, tag, _attrs):
        if tag == "li":
            self.depth += 1
            if self.depth == 1:
                self.has_p.append(False)
        elif tag == "p" and self.depth >= 1:
            self.has_p[-1] = True

    def handle_endtag(self, tag):
        if tag == "li" and self.depth:
            self.depth -= 1


def _video_seconds_limit(duration: str) -> int | None:
    """First second past the video's end, from DURATION ("12 min", "1h 36m": floored to
    the minute by the fetchers, so the video can run to the end of that minute)."""
    text = duration.strip()
    clock = CLOCK_RE.fullmatch(text)
    if clock:
        h, m, s = clock.groups()
        return int(h or 0) * 3600 + int(m) * 60 + int(s) + 1
    match = DURATION_RE.fullmatch(text)
    if match:
        return (int(match.group(1) or 0) * 60 + int(match.group(2)) + 1) * 60
    return None


def _trigram_overlap(a: str, b: str) -> float:
    """Share of a's word trigrams that also occur in b (1.0 = a restates b)."""
    def trigrams(text):
        words = re.findall(r"\w+", text.lower())
        return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}
    ta = trigrams(a)
    return len(ta & trigrams(b)) / len(ta) if ta else 0.0


def lint_payload(data: dict, clean: dict) -> list[str]:
    """025-R5: deterministic quality checks on a payload that already passed the
    sanitiser. Each problem names its fix. Works on the clean HTML, so the older
    HTML-string payloads are checked the same way as arrays."""
    problems = []
    scan = _TopLevelItems()
    scan.feed(clean["KEY_POINTS"])
    scan.close()
    n = len(scan.has_p)
    if not 3 <= n <= 8:
        problems.append(f"KEY_POINTS has {n} item{'' if n == 1 else 's'}; write 3–8")
    with_detail = sum(scan.has_p)
    if n and with_detail * 2 < n:
        problems.append(f"detail on {with_detail} of {n} Key Points; give most of them "
                        "the 2–4 sentence analytical paragraph")

    times = [int(t) for t in re.findall(r'data-t="(\d+)"', clean["OUTLINE"])]
    out_of_order = [f"OUTLINE[{i}].t is {t}, after {prev}" for i, (prev, t) in enumerate(zip(times, times[1:]), 1)
                    if t <= prev]
    if out_of_order:
        problems.append("; ".join(out_of_order[:3]) + "; start times must increase")
    limit = _video_seconds_limit(str(data.get("DURATION", "")))
    beyond = [f"OUTLINE[{i}].t is {t}" for i, t in enumerate(times) if limit is not None and t >= limit]
    if beyond:
        problems.append("; ".join(beyond[:3]) + f", beyond the video's {str(data['DURATION']).strip()}; "
                        "take start times from the transcript's [M:SS] stamps")

    tags = data.get("TAGS")
    tag_count = len(_normalize_tags(tags)) if isinstance(tags, list) else 0
    if not 3 <= tag_count <= 5:
        problems.append(f"TAGS has {tag_count}; use 3–5")

    overlap = _trigram_overlap(str(data.get("TAKEAWAY", "")), str(data.get("SUMMARY", "")))
    if overlap > 0.5:
        problems.append(f"TAKEAWAY repeats the SUMMARY ({overlap:.0%} of its phrases); "
                        "say something the Summary does not")
    return problems


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

    data = {**data, "META_LINE": _maybe_compose_meta_line(data)}
    for key in ITEM_FIELDS:
        if isinstance(data.get(key), list):
            data[key] = items_to_html(key, data[key], video_id)

    clean = {}
    clean["VIDEO_ID"] = video_id
    clean["VIDEO_URL"] = _canonical_video_url(video_id)

    for key in (*PLAINTEXT_KEYS, *HTML_KEYS):
        value = data.get(key, "")
        if not isinstance(value, str):
            kind = "an HTML string" if key in HTML_KEYS else "plain text, one string"
            raise RenderValidationError(
                "RENDER_INVALID_TYPE",
                f"key={key} expected string, got {type(value).__name__}. {key} is {kind}; "
                "fix it, re-Write the payload and retry.",
            )

    for key in PLAINTEXT_KEYS:
        clean[key] = html_lib.escape(data.get(key, ""), quote=False)

    for key in HTML_KEYS:
        try:
            clean[key] = sanitise_html(key, data.get(key, ""), video_id)
        except _Disallowed as e:
            if key in ITEM_FIELDS:
                fix = (f"Write {key} as an array of objects ({', '.join(ITEM_FIELDS[key])}): their text "
                       "is never read as HTML. In a string, text in angle brackets like <branch-name> "
                       "is read as a tag; rephrase it without < >.")
            else:
                fix = 'Put YTDLP_DESC_HTML inside the wrapper unchanged, or set DESCRIPTION_SECTION to "".'
            raise RenderValidationError(
                "RENDER_DISALLOWED_HTML",
                f"key={key} reason={e}. {fix} Re-Write the payload and retry.",
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

    # Collect the template's own placeholders *before* substituting: agent content
    # may legitimately quote a `{{TOKEN}}` (videos about Jinja, Handlebars, GitHub
    # Actions), and a rescan after substitution would mistake it for a template slot.
    missing = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", html)) - set(data))
    if missing:
        raise ValueError(
            "RENDER_UNREPLACED_PLACEHOLDERS "
            f"{['{{' + k + '}}' for k in missing]}"
        )

    # Single pass: re.sub never re-examines the text it inserted, so injected
    # content cannot re-introduce a placeholder for a later key.
    html = re.sub(r"\{\{([A-Z_]+)\}\}", lambda m: data[m.group(1)], html)

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


def _slug(raw: str) -> str:
    """Normalize to ascii [a-z0-9_]{0,60}; empty when no usable chars."""
    return re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")[:60]


def _derived_filename(payload: dict) -> str:
    slug = (
        _slug(str(payload.get("SLUG_HINT", "")))
        or _slug(str(payload.get("VIDEO_TITLE", "")))
        or "video"
    )
    hhmmss = datetime.now().strftime("%H%M%S")
    return (
        f"{payload.get('GENERATION_DATE', '')}-{hhmmss}-video-lens_"
        f"{payload.get('VIDEO_ID', '')}_{slug}.html"
    )


def _read_report_meta(path: pathlib.Path) -> dict:
    """The meta block of a rendered report, or {} when it has none."""
    match = META_BLOCK_RE.search(path.read_text(encoding="utf-8", errors="replace"))
    if not match:
        return {}
    try:
        meta = json.loads(match.group(1))
    except ValueError:
        return {}
    return meta if isinstance(meta, dict) else {}


def _prepare_replace(data: dict, target: str) -> None:
    """Check a --replace target and carry its generation date and time into `data`.

    A revision replaces its report (025 S8), so the target must already exist and
    be a report of the same video. The gallery measures how long a model took to
    write the report; the time the user spent before asking for the revision is
    not part of that, so the original figure is kept.
    """
    path = validate_output_path(target)
    if not path.is_file():
        raise RenderValidationError(
            "RENDER_INVALID_OUTPUT_PATH", f"--replace target does not exist: {path}",
        )
    meta = _read_report_meta(path)
    video_id = str(data.get("VIDEO_ID", ""))
    report_id = meta.get("videoId")
    if report_id is None:
        same_video = f"_{video_id}_" in path.name
    else:
        same_video = report_id == video_id
    if not same_video:
        raise RenderValidationError(
            "RENDER_REPLACE_MISMATCH",
            f"{path.name} is not a report of {video_id!r}",
        )
    if not str(data.get("GENERATION_DATE", "")).strip() and meta.get("generationDate"):
        data["GENERATION_DATE"] = meta["generationDate"]
    if data.get("GENERATION_DURATION_SECONDS") in (None, "") and "durationSeconds" in meta:
        data["GENERATION_DURATION_SECONDS"] = meta["durationSeconds"]


def main():
    parser = argparse.ArgumentParser(
        description="Render a video-lens HTML report.",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print expected payload schema and exit.",
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("path", nargs="?", help="Output file path (legacy form).")
    group.add_argument(
        "--output-dir",
        help="Directory to write the report into; filename is derived from payload.",
    )
    group.add_argument(
        "--replace",
        metavar="REPORT",
        help="Overwrite this existing report of the same video (a revision).",
    )
    parser.add_argument(
        "--payload-file",
        help="Read JSON payload from this path instead of stdin. Use this when the "
             "payload contains double quotes — shells/heredocs mangle them.",
    )
    args = parser.parse_args()

    if args.schema:
        print(_schema_help())
        sys.exit(0)

    if args.path is None and args.output_dir is None and args.replace is None:
        parser.error("one of path, --output-dir or --replace is required")

    # SKILL.md allows one fixed retry, so the lint (025-R5) may stop a run only while
    # nothing else has: any rejection leaves a marker in the per-run payload directory,
    # and with the marker present the lint only warns. Only the skill's own form of the
    # call (--payload-file with --output-dir or --replace) is ever stopped by it.
    lint_marker = None
    if args.payload_file and args.path is None:
        lint_marker = pathlib.Path(args.payload_file).expanduser().parent / LINT_MARKER

    def reject(message: str):
        if lint_marker is not None:
            try:
                lint_marker.touch()
            except OSError:
                pass
        print(message, file=sys.stderr)
        sys.exit(1)

    if args.payload_file:
        try:
            raw = pathlib.Path(args.payload_file).expanduser().read_text(encoding="utf-8")
        except OSError as e:
            reject(f"ERROR:RENDER_PAYLOAD_FILE_UNREADABLE {e}")
    else:
        raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        reject(f"ERROR:RENDER_INVALID_JSON {e}")

    problems: list[str] = []

    missing = EXPECTED_KEYS - set(data.keys())
    if missing:
        problems.append(f"missing_keys={sorted(missing)}")

    empty = [k for k in REQUIRED_NONEMPTY if not str(data.get(k, "")).strip()]
    if empty:
        problems.append(f"empty_keys={empty}")

    gen_date = str(data.get("GENERATION_DATE", "")).strip()
    if args.output_dir is not None and not gen_date:
        # Default to today rather than rejecting: the filename's HHMMSS already
        # comes from datetime.now(), so deriving the date from the same clock is
        # both simpler and more correct when a run crosses midnight. --replace
        # takes the report's own date instead (_prepare_replace).
        data["GENERATION_DATE"] = date.today().isoformat()
    elif args.path is None and gen_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", gen_date):
        problems.append(f"bad_format_keys=['GENERATION_DATE'] (got {gen_date!r}, expected YYYY-MM-DD)")

    if problems:
        reject("ERROR:RENDER_PAYLOAD_INVALID " + " ".join(problems) + " " + _schema_help())

    if args.output_dir is not None:
        target = str(pathlib.Path(args.output_dir).expanduser() / _derived_filename(data))
    elif args.replace is not None:
        target = args.replace
    else:
        target = args.path

    try:
        if args.replace is not None:
            _prepare_replace(data, target)
        output_path = validate_output_path(target)
        clean = sanitise_payload(data, str(output_path))
        lint = lint_payload(data, clean) if args.path is None else []
        if lint and lint_marker is not None and not lint_marker.exists() and lint_marker.parent.is_dir():
            numbered = " ".join(f"({i}) {p}." for i, p in enumerate(lint, 1))
            raise RenderValidationError(
                "RENDER_LINT",
                f"{len(lint)} problem{'' if len(lint) == 1 else 's'}: {numbered} Fix "
                f"{'it' if len(lint) == 1 else 'them'}, re-Write the payload and render again; "
                "the next render saves the report and only warns.",
            )
        for problem in lint:
            print(f"RENDER_WARN: {problem}", file=sys.stderr)
        result = _render_clean(clean, str(output_path))
        if lint_marker is not None:
            lint_marker.unlink(missing_ok=True)
    except RenderValidationError as e:
        reject(f"ERROR:{e.code} {e.detail}")
    except FileNotFoundError as e:
        reject(f"ERROR:RENDER_TEMPLATE_NOT_FOUND {e}")
    except ValueError as e:
        reject(f"ERROR:{e}")

    print(f"OUTPUT_PATH: {result}")


if __name__ == "__main__":
    main()
