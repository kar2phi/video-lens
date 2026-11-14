#!/usr/bin/env python3
"""Share payload v1: the one Python copy of the share service's validator (stdlib only).

The Worker (video-lens-core `service/src/schema.ts`) is the authority. This module is its Python
form, used by
  - render_report.py   cleans the fields that come from YouTube and warns when a report is not
                       shareable as is (`RENDER_WARN: not shareable as is: …`);
  - share_report.py    checks a report before it is uploaded and names field, size and limit;
  - tests/fake_share_service.py   the fake service's schema check.
The contract tests (tests/test_share_contract.py, and the Worker's own against
tests/share_contract.json) keep the two equal.

    validate_payload(p) -> the normalised payload in canonical key order, or SchemaError
    SchemaError.field   the field name the Worker reports ("summary", "keyPoints", …)
    SchemaError.detail  a sentence for a person: "summary has 6412 of 6000 characters"
"""
import re
import unicodedata

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/ -]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NOTES = {"lang-fallback", "local-transcript"}
# C0 and C1 controls (tab and newline allowed), bidi embeddings and overrides (U+202A–U+202E),
# isolates (U+2066–U+2069), lone surrogates (which JSON can carry but UTF-8 cannot), and invisible
# characters (041 F12): U+061C, U+200B, U+200E/F, U+2028/9, U+2060–U+2064, U+FEFF. Not U+200C/D
# (ZWNJ, ZWJ): Persian words and emoji need them.
FORBIDDEN_RE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200b\u200e\u200f\u2028\u2029"
                          "\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\ud800-\udfff]")

# key: (min length, max length, required); lengths in code points after NFC
TEXT_FIELDS = {
    "title": (1, 300, True), "channel": (0, 200, False), "duration": (0, 40, False),
    "published": (0, 40, False), "summary": (1, 6000, True), "takeaway": (1, 2000, True),
    "model": (0, 80, False),
}
KEY_ORDER = ["v", "videoId", "title", "channel", "channelId", "duration", "durationS", "published",
             "lang", "tags", "summary", "takeaway", "keyPoints", "outline", "model", "notes", "created"]
REQUIRED = ("v", "videoId", "title", "summary", "takeaway", "keyPoints", "outline")
KP_FIELDS = {"point": (1, 600), "why": (0, 1500), "detail": (0, 4000)}
OL_FIELDS = {"title": (1, 300), "detail": (0, 1500)}
KP_COUNT = (1, 20)
OL_COUNT = (0, 100)
TEXT_LIMITED = {"summary", "takeaway", "keyPoints", "outline"}   # the model's own text


def share_tag_ok(tag: str) -> bool:
    """Share tag pattern (033 §5.1, O7), the Python form of the Worker's
    /^[\\p{Ll}\\p{Lo}\\p{Lm}\\p{Nd}][\\p{Ll}\\p{Lo}\\p{Lm}\\p{Nd}\\p{Mn}\\p{Mc} +#.-]{0,29}$/u."""
    if not isinstance(tag, str) or not 1 <= len(tag) <= 30:
        return False
    first = {"Ll", "Lo", "Lm", "Nd"}
    rest = first | {"Mn", "Mc"}
    return unicodedata.category(tag[0]) in first and all(
        c in " +#.-" or unicodedata.category(c) in rest for c in tag[1:])


def clean_text(value: str) -> str:
    """NFC, with the characters the service refuses removed. For text that comes from YouTube
    (title, channel), not from the model: the visible page keeps the original, escaped."""
    return FORBIDDEN_RE.sub("", unicodedata.normalize("NFC", str(value)))


class SchemaError(Exception):
    def __init__(self, field: str, detail: str | None = None):
        super().__init__(field)
        self.field = field
        self.detail = detail or f"{field} is not valid"


def _int(value, lo, hi):
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


def _text(value, lo, hi, field, where=None):
    where = where or field
    if not isinstance(value, str):
        raise SchemaError(field, f"{where} is not text")
    value = unicodedata.normalize("NFC", value)
    if FORBIDDEN_RE.search(value):
        raise SchemaError(field, f"{where} contains a control, invisible or text-direction character")
    if len(value) > hi:
        raise SchemaError(field, f"{where} has {len(value)} of {hi} characters")
    if len(value) < lo:
        raise SchemaError(field, f"{where} is empty")
    return value


def validate_payload(p):
    """The validated, normalised payload in canonical key order, or SchemaError(field)."""
    if not isinstance(p, dict):
        raise SchemaError("payload", "the share data is not an object")
    for key in p:
        if key not in KEY_ORDER:
            raise SchemaError(key, f"{key} is not a field of the share data")
    for key in REQUIRED:
        if key not in p:
            raise SchemaError(key, f"{key} is missing")
    out = {}
    if p["v"] != 1 or isinstance(p["v"], bool):
        raise SchemaError("v", "v is not 1")
    out["v"] = 1
    if not isinstance(p["videoId"], str) or not VIDEO_ID_RE.fullmatch(p["videoId"]):
        raise SchemaError("videoId", "videoId is not a YouTube video ID")
    out["videoId"] = p["videoId"]
    for key, (lo, hi, _required) in TEXT_FIELDS.items():
        out[key] = _text(p.get(key, ""), lo, hi, key)
    if not MODEL_RE.fullmatch(out["model"]):
        raise SchemaError("model", "model has characters other than letters, digits and ._:/ -")
    for key, pattern in (("channelId", CHANNEL_ID_RE), ("lang", LANG_RE), ("created", DATE_RE)):
        value = p.get(key, "")
        if not isinstance(value, str) or (value and not pattern.fullmatch(value)):
            raise SchemaError(key, f"{key} is not in the expected form")
        out[key] = value
    duration_s = p.get("durationS")
    if duration_s is not None and not _int(duration_s, 0, 86400):
        raise SchemaError("durationS", "durationS is not 0–86400 seconds")
    out["durationS"] = duration_s
    tags = p.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 5 or not all(isinstance(t, str) and share_tag_ok(unicodedata.normalize("NFC", t)) for t in tags):
        raise SchemaError("tags", "tags are not up to five valid tags")
    out["tags"] = [unicodedata.normalize("NFC", t) for t in tags]
    notes = p.get("notes", [])
    if not isinstance(notes, list) or len(notes) > 2 or len(set(notes)) != len(notes) or not set(notes) <= NOTES:
        raise SchemaError("notes", "notes are not valid")
    out["notes"] = list(notes)
    out["keyPoints"] = _items(p["keyPoints"], "keyPoints", *KP_COUNT, KP_FIELDS, optional_t=True)
    out["outline"] = _items(p["outline"], "outline", *OL_COUNT, OL_FIELDS, timed=True)
    # D7: a key point's t must name one outline entry
    starts = {o["t"] for o in out["outline"]}
    if any("t" in k and k["t"] not in starts for k in out["keyPoints"]):
        raise SchemaError("keyPoints.t", "a key point's time is not the start of an outline entry")
    return {key: out[key] for key in KEY_ORDER}


def _items(items, field, lo, hi, fields, timed=False, optional_t=False):
    """`timed`: t is required (outline). `optional_t`: t may be left out (keyPoints, D7); it
    comes first in the normalised item, as in the Worker, because the payload is hashed."""
    if not isinstance(items, list):
        raise SchemaError(field, f"{field} is not a list")
    if not lo <= len(items) <= hi:
        raise SchemaError(field, f"{field} has {len(items)} entries; {lo}–{hi} are allowed")
    out = []
    for n, item in enumerate(items, 1):
        where = f"{field} {n}"
        if not isinstance(item, dict) or not set(item) <= set(fields) | ({"t"} if timed or optional_t else set()):
            raise SchemaError(field, f"{where} is not in the expected form")
        clean = {}
        if timed:
            if not _int(item.get("t"), 0, 86400):
                raise SchemaError(field, f"{where} has no valid time")
            clean["t"] = item["t"]
        elif optional_t and "t" in item:
            if not _int(item["t"], 0, 86400):
                raise SchemaError(field + ".t", f"{where} has no valid time")
            clean["t"] = item["t"]
        for name, (a, b) in fields.items():
            if a and name not in item:
                raise SchemaError(field, f"{where} has no {name}")
            clean[name] = _text(item.get(name, ""), a, b, field, f"{where} {name}")
        out.append(clean)
    return out
