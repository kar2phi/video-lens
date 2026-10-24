"""Google Takeout import for video-lens-recs: subscriptions only (026 §5.2).

Takeout names folders and files in the account's language ("YouTube und YouTube Music/
Abos/Abos.csv"), so files are recognised by content shape, not by name: a CSV with a column
of `UC…` channel IDs, the older JSON list of `snippet.resourceId.channelId`, or an HTML page
of `/channel/UC…` links. Watch history is never imported. A history file in the archive is
recognised (by name, or by peeking at its first bytes) and reported as ignored; its content
is not parsed.
"""
import csv
import datetime
import html
import io
import json
import pathlib
import re
import tarfile
import zipfile

CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
CHANNEL_LINK_RE = re.compile(
    r'<a[^>]+href="https?://(?:www\.)?youtube\.com/channel/(UC[A-Za-z0-9_-]{22})"[^>]*>(.*?)</a>',
    re.S | re.I)
HISTORY_NAME_RE = re.compile(
    r"(watch[-_ ]?history|search[-_ ]?history|wiedergabeverlauf|suchverlauf|historial|"
    r"historique|cronologia|histórico|geschiedenis)", re.I)
TEXT_SUFFIXES = (".csv", ".json", ".html", ".htm")


class TakeoutError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8-sig", errors="replace")


def parse_csv(text: str) -> list[dict]:
    """Rows of a subscriptions CSV, whatever the header language. [] when not that shape."""
    rows = [r for r in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        return []
    width = max(len(r) for r in rows)
    body = rows[1:]

    def share(col, pred):
        vals = [r[col].strip() for r in body if col < len(r)]
        return sum(1 for v in vals if pred(v)) / max(len(vals), 1)

    id_col = next((c for c in range(width) if share(c, CHANNEL_ID_RE.fullmatch) >= 0.8), None)
    if id_col is None:
        return []
    url_col = next((c for c in range(width) if c != id_col and share(c, lambda v: v.startswith("http")) >= 0.8), None)
    title_col = next((c for c in range(width) if c not in (id_col, url_col)), None)
    out = []
    for r in body:
        if id_col >= len(r) or not CHANNEL_ID_RE.fullmatch(r[id_col].strip()):
            continue
        cid = r[id_col].strip()
        out.append({
            "id": cid,
            "title": r[title_col].strip() if title_col is not None and title_col < len(r) else "",
            "url": r[url_col].strip() if url_col is not None and url_col < len(r) else
                   f"https://www.youtube.com/channel/{cid}",
        })
    return out


def parse_json(text: str) -> list[dict]:
    """The pre-2020 Takeout subscriptions.json (Data API subscription resources)."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        snippet = item.get("snippet") if isinstance(item, dict) else None
        if not isinstance(snippet, dict):
            continue
        cid = (snippet.get("resourceId") or {}).get("channelId", "")
        if CHANNEL_ID_RE.fullmatch(cid or ""):
            out.append({"id": cid, "title": snippet.get("title", ""),
                        "url": f"https://www.youtube.com/channel/{cid}"})
    return out


def parse_html(text: str) -> list[dict]:
    out, seen = [], set()
    for cid, label in CHANNEL_LINK_RE.findall(text):
        if cid in seen:
            continue
        seen.add(cid)
        title = html.unescape(re.sub(r"<[^>]+>", "", label)).strip()
        out.append({"id": cid, "title": title, "url": f"https://www.youtube.com/channel/{cid}"})
    return out


def looks_like_history(name: str, head: bytes) -> bool:
    """A watch or search history file: by name in any language, or by its first bytes."""
    if HISTORY_NAME_RE.search(pathlib.PurePath(name).name):
        return True
    sample = head[:4096].decode("utf-8", errors="ignore")
    return '"titleUrl"' in sample and "watch?v=" in sample


def parse_member(name: str, raw: bytes) -> list[dict]:
    text = _decode(raw)
    suffix = pathlib.PurePath(name).suffix.lower()
    if suffix == ".csv":
        return parse_csv(text)
    if suffix == ".json":
        return parse_json(text)
    return parse_html(text)


def _iter_members(path: pathlib.Path):
    """Yield (name, opener, mtime) for every text file in a zip, tar, folder or single file.

    `opener(n)` returns the first n bytes, or everything when n is None, so history files are
    only ever peeked at, never read whole.
    """
    if path.is_dir():
        for p in sorted(path.rglob("*")):
            if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
                yield str(p.relative_to(path)), (lambda n, p=p: p.read_bytes() if n is None else p.open("rb").read(n)), p.stat().st_mtime
        return
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            for info in zf.infolist():
                if info.is_dir() or pathlib.PurePath(info.filename).suffix.lower() not in TEXT_SUFFIXES:
                    continue
                def opener(n, info=info):
                    with zf.open(info) as f:
                        return f.read() if n is None else f.read(n)
                yield info.filename, opener, datetime.datetime(*info.date_time).timestamp()
        return
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as tf:
            for m in tf.getmembers():
                if not m.isfile() or pathlib.PurePath(m.name).suffix.lower() not in TEXT_SUFFIXES:
                    continue
                def opener(n, m=m):
                    f = tf.extractfile(m)
                    return f.read() if n is None else f.read(n)
                yield m.name, opener, float(m.mtime)
        return
    if path.is_file():
        yield path.name, (lambda n: path.read_bytes() if n is None else path.open("rb").read(n)), path.stat().st_mtime
        return
    raise TakeoutError("TAKEOUT_NOT_FOUND", f"{path} does not exist")


def import_takeout(path) -> dict:
    """Find the subscriptions in a Takeout export. Returns
    {"channels": [...], "source_file": name, "export_date": "YYYY-MM-DD", "ignored": [names]}.
    """
    path = pathlib.Path(path).expanduser()
    if not path.exists():
        raise TakeoutError("TAKEOUT_NOT_FOUND", f"{path} does not exist")
    best, best_name, ignored, newest = [], "", [], 0.0
    for name, opener, mtime in _iter_members(path):
        if looks_like_history(name, opener(4096)):
            ignored.append(name)
            continue
        channels = parse_member(name, opener(None))
        newest = max(newest, mtime)
        if len(channels) > len(best):
            best, best_name = channels, name
    if not best:
        raise TakeoutError(
            "TAKEOUT_NO_SUBSCRIPTIONS",
            f"no subscriptions file found in {path}: export 'YouTube and YouTube Music' with "
            "'subscriptions' ticked (see references/setup.md)")
    seen, channels = set(), []
    for c in best:
        if c["id"] not in seen:
            seen.add(c["id"])
            channels.append(c)
    export_date = datetime.date.fromtimestamp(newest).isoformat() if newest else ""
    return {"channels": channels, "source_file": best_name, "export_date": export_date,
            "ignored": ignored}
