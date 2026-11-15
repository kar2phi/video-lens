#!/usr/bin/env python3
"""Share a video-lens report as an unlisted link (stdlib only).

    share_report.py report PATH [--new-link]            create, or update the existing link
    share_report.py list                                own shares with visitors and loads, from the service
    share_report.py revoke (ID | URL | PATH)
    share_report.py terms [--accept]                    show the terms; record acceptance
    share_report.py offer (on | off)                    the closing offer line in the skill

This is the only video-lens script that sends report content off the machine, and it does so
only when the user asks. Output on stdout: `SHARE_URL: <url>`, `SHARE_ID: <id>`,
`REVOKED: <id>`, `SHARE: <id> <visitors> <loads> <updated> <state> <title>`, where visitors are the
distinct visitors and loads the page loads (bots and link previews are not counted), state is `current`,
`outdated` (the report changed since), `removed:<reason>` (taken down by the operator, with one of
the service's fixed reason codes) or `gone` (the service no longer knows the link).
Errors on stderr: `ERROR:SHARE_<CODE>: <message>`; exit 2 for SHARE_TERMS, else 1.

Local state:
  config   $XDG_CONFIG_HOME/video-lens/share.json   {"service_url", "terms_accepted", "offer", "install"}
  registry $XDG_DATA_HOME/video-lens/share/registry.json   one entry per share; the only place
           manage keys are kept. A manage key is never printed.
"""
import argparse
import base64
import http.client
import json
import os
import re
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from share_payload import TEXT_LIMITED, SchemaError, validate_payload  # noqa: E402

DEFAULT_SERVICE_URL = "https://video-lens.org"
BODY_LIMIT = 64 * 1024  # the contract's bodyLimit (041 F1.1)
REQUIRED_KEYS = ("v", "videoId", "title", "summary", "takeaway", "keyPoints", "outline")
RETRIES = 3
BACKOFF = 0.5
TIMEOUT = 20
LIST_PACE_FROM = 15   # 051 F2: `list` sends one GET per share; the WAF allows 20 per 10 s
LIST_PACE = 0.6
EDGE_WAIT = 10        # a 429 from Cloudflare itself (the WAF, Workers Free 1027) carries no JSON error

META_RE = re.compile(r'<script type="application/json" id="video-lens-meta">(.*?)</script>', re.S)
DATA_RE = re.compile(r'<script type="application/json" id="video-lens-data">(.*?)</script>', re.S)
ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
URL_ID_RE = re.compile(r"/s/([A-Za-z0-9_-]{22})/?(?:[?#].*)?$")
REASON_RE = re.compile(r"[a-z][a-z_]{0,31}")
VERSION_RE = re.compile(r'^\s*version:\s*"?([^"\s]+)"?\s*$', re.M)

TERMS_EXIT = 2
# 044 W11: over the body limit, the same way forward as a field over its limit.
TOO_LARGE = ("the report is too large to share (64 KiB limit). Shorten the summary, key points or outline "
             "(a revision with --replace), then share again.")


class ShareError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ── paths and state ──────────────────────────────────────────────────────────

def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


def config_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "video-lens" / "share.json"


def registry_path() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "video-lens" / "share" / "registry.json"


def reports_dir() -> Path:
    return (Path.home() / "Downloads" / "video-lens" / "reports").resolve()


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> None:
    """Atomic write, file mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_config() -> dict:
    cfg = _read_json(config_path())
    return {
        "service_url": cfg.get("service_url") if isinstance(cfg.get("service_url"), str) else None,
        "terms_accepted": cfg.get("terms_accepted") if isinstance(cfg.get("terms_accepted"), str) else None,
        "offer": cfg.get("offer") is not False,
        "install": cfg.get("install") if isinstance(cfg.get("install"), str)
        and ID_RE.fullmatch(cfg["install"]) else None,
    }


def save_config(cfg: dict) -> None:
    _write_json(config_path(), {k: v for k, v in cfg.items() if v is not None})


def service_url(cfg: dict) -> str:
    url = os.environ.get("VIDEO_LENS_SHARE_URL") or cfg.get("service_url") or DEFAULT_SERVICE_URL
    return url.rstrip("/")


def terms_url(base: str) -> str:
    return f"{base}/legal/terms"


def ensure_install(cfg: dict) -> str:
    """16 random bytes as base64url, created once at the first upload."""
    if not cfg.get("install"):
        cfg["install"] = base64.urlsafe_b64encode(secrets.token_bytes(16)).rstrip(b"=").decode()
        save_config(cfg)
    return cfg["install"]


def load_registry() -> list:
    shares = _read_json(registry_path()).get("shares")
    return [s for s in shares if isinstance(s, dict) and isinstance(s.get("id"), str)] \
        if isinstance(shares, list) else []


def save_registry(shares: list) -> None:
    _write_json(registry_path(), {"shares": shares})


def skill_version() -> str:
    try:
        text = (Path(__file__).resolve().parent.parent / "SKILL.md").read_text(encoding="utf-8")
        m = VERSION_RE.search(text.split("\n---", 1)[0])
        return m.group(1) if m else "0"
    except OSError:
        return "0"


# ── HTTP ─────────────────────────────────────────────────────────────────────

class Response:
    def __init__(self, status: int, body, headers):
        self.status = status
        self.body = body if isinstance(body, dict) else {}
        self.headers = headers


def _once(method: str, url: str, data: bytes | None, headers: dict, timeout: float) -> Response:
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status, hdrs = r.read(), r.status, r.headers
    except urllib.error.HTTPError as e:
        raw, status, hdrs = e.read(), e.code, e.headers
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {}
    return Response(status, body, hdrs)


def request(method: str, url: str, body: dict | None = None, key: str | None = None,
            install: str | None = None, retries: int = RETRIES, timeout: float = TIMEOUT) -> Response:
    """Network errors and 5xx are retried with backoff; `paused` (503) and 4xx are not.

    A POST creates a share, so it is retried only when the request cannot have reached the
    service (urllib's URLError: DNS, refused, a failure while connecting or sending) or on a 5xx
    (the Worker writes in one atomic batch). When the answer is lost after the request was sent
    (a read timeout, a reset), the share may exist without its manage key here, and a second POST
    would make another one: stop and say so.
    """
    headers = {"User-Agent": f"video-lens-share/{skill_version()}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if install:
        headers["X-VL-Install"] = install
    for attempt in range(retries + 1):
        try:
            resp = _once(method, url, data, headers, timeout)
        except urllib.error.URLError:
            resp = None
        except (OSError, ValueError, http.client.HTTPException):
            resp = None
            if method == "POST":
                raise ShareError("SHARE_NETWORK", "the connection to the share service broke after the "
                                 "report was sent; a link may have been made that this machine cannot "
                                 "revoke (the notice form on the service's site can remove it). Try "
                                 "again later; a new attempt makes a new link")
        if resp is not None and not (resp.status >= 500 and resp.body.get("error") != "paused"):
            return resp
        if attempt < retries:
            time.sleep(BACKOFF * 2 ** attempt)
    if resp is None:
        raise ShareError("SHARE_NETWORK", f"the share service at {urllib.parse.urlsplit(url).netloc} "
                                          "cannot be reached; check the connection and try again later")
    raise ShareError("SHARE_HTTP", f"the share service answered HTTP {resp.status}; try again later")


def _wait_text(seconds) -> str:
    try:
        s = max(1, int(seconds))
    except (TypeError, ValueError):
        return "later"
    if s < 90:
        return f"in {s} seconds"
    if s < 90 * 60:
        return f"in {round(s / 60)} minutes"
    return f"in about {round(s / 3600)} hours"


def raise_for(resp: Response, base: str) -> None:
    """Map an API error to a ShareError (033 §6.2, §7)."""
    if resp.status < 400:
        return
    code = resp.body.get("error")
    if code == "schema":
        field = resp.body.get("field") or "payload"
        raise ShareError("SHARE_SCHEMA", f"{field}: the service rejected this field of the report")
    if code == "terms":
        raise ShareError("SHARE_TERMS", f"the terms of the share service changed; read {terms_url(base)} "
                                        "and accept them with `share_report.py terms --accept`")
    if code == "size":
        raise ShareError("SHARE_INPUT", TOO_LARGE)
    if code == "rate":
        raise ShareError("SHARE_RATE", f"share limit reached; try again {_wait_text(resp.headers.get('Retry-After'))}")
    if code == "paused":
        raise ShareError("SHARE_PAUSED", "new shares are paused on the service; try again later")
    if code == "removed":
        reason = resp.body.get("reason") or "other"
        raise ShareError("SHARE_REMOVED", f"{reason}: the operator removed this report from the service; "
                                          "it cannot be shared or updated again")
    if code == "blocked":
        raise ShareError("SHARE_BLOCKED", "the operator blocked sharing from this install; "
                                          f"see {terms_url(base)}")
    if code == "video":
        raise ShareError("SHARE_VIDEO", "YouTube says this video does not exist, so it cannot be shared")
    if code == "auth":
        raise ShareError("SHARE_AUTH", "the service does not accept the saved key for this share "
                                       "(it may have been deleted); use --new-link for a fresh link")
    if resp.status == 429:
        raise ShareError("SHARE_HTTP", "the share service is busy (HTTP 429); wait a minute and try again")
    raise ShareError("SHARE_HTTP", f"the share service answered HTTP {resp.status}")


def _edge_limited(resp: Response) -> bool:
    return resp.status == 429 and not resp.body.get("error")


# ── report input ─────────────────────────────────────────────────────────────

def resolve_report(path: str) -> Path:
    root = reports_dir()
    try:
        real = Path(os.path.realpath(os.path.expanduser(path)))
        real.relative_to(root)
    except (ValueError, OSError):
        raise ShareError("SHARE_INPUT", f"only reports under {root} can be shared")
    if not real.is_file():
        raise ShareError("SHARE_INPUT", f"no report at {real}")
    return real


def read_payload(path: Path) -> dict:
    try:
        html = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise ShareError("SHARE_INPUT", f"cannot read {path}")
    meta_m = META_RE.search(html)
    try:
        meta = json.loads(meta_m.group(1)) if meta_m else None
    except ValueError:
        meta = None
    if not isinstance(meta, dict):
        raise ShareError("SHARE_INPUT", f"{path.name} is not a video-lens report")
    data_m = DATA_RE.search(html)
    if not data_m:
        raise ShareError("SHARE_NO_DATA", "this report was made before sharing existed; "
                                          "run video-lens on the video again to share it")
    try:
        payload = json.loads(data_m.group(1))
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise ShareError("SHARE_NO_DATA", "the share data in this report is unreadable; "
                                          "run video-lens on the video again to share it")
    missing = [k for k in REQUIRED_KEYS if k not in payload]
    if missing:
        raise ShareError("SHARE_SCHEMA", f"{missing[0]}: missing from the report's share data")
    if payload.get("videoId") != meta.get("videoId"):
        raise ShareError("SHARE_INPUT", "the share data and the report are for different videos")
    return payload


def _stat(path: Path) -> tuple[float | None, int | None]:
    try:
        st = path.stat()
        return st.st_mtime, st.st_size
    except OSError:
        return None, None


# ── commands ─────────────────────────────────────────────────────────────────

def out(line: str) -> None:
    print(line, flush=True)


def cmd_report(args) -> int:
    cfg = load_config()
    base = service_url(cfg)
    path = resolve_report(args.path)
    payload = read_payload(path)
    try:
        validate_payload(payload)   # the service's own check, before anything is sent (038 B13)
    except SchemaError as e:
        hint = (" Shorten that part of the report (a revision with --replace), then share again."
                if e.field.split(".")[0] in TEXT_LIMITED else "")
        raise ShareError("SHARE_SCHEMA", f"{e.field}: {e.detail}; the share service does not accept it.{hint}")
    if not cfg["terms_accepted"]:
        raise ShareError("SHARE_TERMS", f"accept the terms first: read {terms_url(base)}, "
                                        "then run `share_report.py terms --accept`")
    install = ensure_install(cfg)
    body = {"terms": cfg["terms_accepted"], "payload": payload}
    if len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > BODY_LIMIT:
        raise ShareError("SHARE_INPUT", TOO_LARGE)

    shares = load_registry()
    source = str(path)
    existing = next((s for s in shares if s.get("source") == source), None)
    mtime, size = _stat(path)
    now = int(time.time())

    if existing and not args.new_link:
        resp = request("PUT", f"{base}/api/v1/shares/{existing['id']}", body,
                       key=existing.get("manageKey"), install=install)
        raise_for(resp, base)
        existing.update(url=resp.body.get("url") or existing.get("url"), payload_sha=resp.body.get("sha"),
                        updated=now, mtime=mtime, size=size, title=payload.get("title", ""))
        save_registry(shares)
        entry, action = existing, "updated"
    else:
        resp = request("POST", f"{base}/api/v1/shares", body, install=install)
        raise_for(resp, base)
        r = resp.body
        if not (isinstance(r.get("id"), str) and ID_RE.fullmatch(r["id"])
                and isinstance(r.get("url"), str) and isinstance(r.get("manageKey"), str)):
            raise ShareError("SHARE_HTTP", "the share service sent an unexpected answer")
        entry = {"id": r["id"], "url": r["url"], "manageKey": r["manageKey"], "source": source,
                 "payload_sha": r.get("sha"), "created": now, "updated": now, "mtime": mtime,
                 "size": size, "title": payload.get("title", "")}
        shares.append(entry)
        save_registry(shares)   # the new key is on disk before the old link goes
        action = "created"
        if existing:
            _delete_quietly(base, existing)
            shares = [s for s in load_registry() if s.get("id") != existing["id"]]
            save_registry(shares)
            action = "replaced"
    out(f"SHARE_URL: {entry['url']}")
    out(f"SHARE_ID: {entry['id']}")
    return 0


def _delete_quietly(base: str, share: dict) -> None:
    """Delete an old link after --new-link; a link the service no longer knows is fine."""
    try:
        resp = request("DELETE", f"{base}/api/v1/shares/{share['id']}", key=share.get("manageKey"))
    except ShareError as e:
        print(f"WARNING: the old link {share['id']} could not be deleted ({e.message}); "
              f"revoke it later", file=sys.stderr)
        return
    if resp.status >= 400 and resp.body.get("error") != "auth":
        print(f"WARNING: the old link {share['id']} could not be deleted "
              f"(HTTP {resp.status}); revoke it later", file=sys.stderr)


def _day(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d")
    return str(value) if value else "-"


def cmd_list(args) -> int:
    cfg = load_config()
    base = service_url(cfg)
    rows = []
    for i, s in enumerate(load_registry()):
        if i + 1 >= LIST_PACE_FROM:
            time.sleep(LIST_PACE)
        resp = request("GET", f"{base}/api/v1/shares/{s['id']}", key=s.get("manageKey"))
        if _edge_limited(resp):
            time.sleep(EDGE_WAIT)
            resp = request("GET", f"{base}/api/v1/shares/{s['id']}", key=s.get("manageKey"))
        if resp.status == 401:
            info = {"status": "gone", "reason": None, "views": {}, "updated": s.get("updated")}
        else:
            raise_for(resp, base)
            info = resp.body
        if info.get("status") == "gone":
            state = "gone"
        elif info.get("status") == "removed":
            reason = info.get("reason")
            state = "removed:" + (reason if isinstance(reason, str) and REASON_RE.fullmatch(reason) else "other")
        else:
            mtime, size = _stat(Path(s.get("source", "")))
            state = "current" if (mtime, size) == (s.get("mtime"), s.get("size")) else "outdated"
        views = info.get("views")
        views = views if isinstance(views, dict) else {"loads": views} if isinstance(views, int) else {}
        count = lambda k: views[k] if isinstance(views.get(k), int) and not isinstance(views.get(k), bool) else 0  # noqa: E731
        rows.append({"id": s["id"], "url": s.get("url", ""), "visitors": count("visitors"), "loads": count("loads"),
                     "updated": _day(info.get("updated") or s.get("updated")), "state": state,
                     "reason": info.get("reason"), "title": s.get("title", ""), "source": s.get("source", "")})
    for r in rows:
        title = " ".join(str(r["title"]).split())
        out(f"SHARE: {r['id']} {r['visitors']} {r['loads']} {r['updated']} {r['state']} {title}")
    if not rows:
        out("SHARES: none")
    return 0


def _find_share(target: str, shares: list) -> dict | None:
    if ID_RE.fullmatch(target):
        return next((s for s in shares if s["id"] == target), None)
    m = URL_ID_RE.search(target) if "://" in target else None
    if m:
        return next((s for s in shares if s["id"] == m.group(1)), None)
    try:
        real = os.path.realpath(os.path.expanduser(target))
    except (OSError, ValueError):
        return None
    return next((s for s in shares if s.get("source") == real), None)


def cmd_revoke(args) -> int:
    cfg = load_config()
    base = service_url(cfg)
    shares = load_registry()
    share = _find_share(args.target, shares)
    if share is None:
        raise ShareError("SHARE_INPUT", "no share made on this machine matches that ID, link or report")
    resp = request("DELETE", f"{base}/api/v1/shares/{share['id']}", key=share.get("manageKey"))
    if resp.status != 401:   # 401: the service no longer has it, so it is gone either way
        raise_for(resp, base)
    save_registry([s for s in load_registry() if s.get("id") != share["id"]])
    out(f"REVOKED: {share['id']}")
    return 0


def _health(base: str, retries: int = RETRIES, timeout: float = TIMEOUT) -> dict:
    resp = request("GET", f"{base}/api/v1/health", retries=retries, timeout=timeout)
    raise_for(resp, base)
    if not isinstance(resp.body.get("terms"), str):
        raise ShareError("SHARE_HTTP", "the share service sent an unexpected answer")
    return resp.body


def cmd_terms(args) -> int:
    cfg = load_config()
    base = service_url(cfg)
    current = _health(base)["terms"]
    if args.accept:
        cfg["terms_accepted"] = current
        save_config(cfg)
    out(f"TERMS_URL: {terms_url(base)}")
    out(f"TERMS_VERSION: {current}")
    out(f"TERMS_ACCEPTED: {'yes' if cfg['terms_accepted'] == current else 'no'}")
    return 0


def cmd_offer(args) -> int:
    cfg = load_config()
    cfg["offer"] = args.state == "on"
    save_config(cfg)
    out(f"OFFER: {args.state}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="share_report.py", description="Share a video-lens report as an unlisted link.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="create a link, or update the existing one")
    r.add_argument("path")
    r.add_argument("--new-link", action="store_true", help="make a fresh link and delete the old one")
    r.set_defaults(func=cmd_report)
    lst = sub.add_parser("list", help="own shares with visitors and loads")
    lst.set_defaults(func=cmd_list)
    rv = sub.add_parser("revoke", help="delete a link (ID, URL or report path)")
    rv.add_argument("target")
    rv.set_defaults(func=cmd_revoke)
    t = sub.add_parser("terms", help="show the terms; --accept records acceptance")
    t.add_argument("--accept", action="store_true")
    t.set_defaults(func=cmd_terms)
    o = sub.add_parser("offer", help="turn the offer line on or off")
    o.add_argument("state", choices=["on", "off"])
    o.set_defaults(func=cmd_offer)
    return p


def _protect_ids(argv: list[str]) -> list[str]:
    """A share ID is base64url and may start with "-"; keep argparse from reading it as a flag."""
    if not argv or argv[0] != "revoke":
        return argv
    flags = [a for a in argv[1:] if a in ("-h", "--help")]
    rest = [a for a in argv[1:] if a not in flags and a != "--"]
    return ["revoke", *flags, "--", *rest] if rest else argv


def main(argv: list[str] | None = None) -> int:
    argv = _protect_ids(list(sys.argv[1:] if argv is None else argv))
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ShareError as e:
        print(f"ERROR:{e.code}: {e.message}", file=sys.stderr, flush=True)
        return TERMS_EXIT if e.code == "SHARE_TERMS" else 1
    except OSError as e:
        print(f"ERROR:SHARE_INPUT: local file error: {e.strerror or e}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
