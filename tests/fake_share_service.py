#!/usr/bin/env python3
"""A stdlib fake of the video-lens share service (033 §7, §12.1).

It implements tests/share_contract.json with an in-memory store, so the client
(share_report.py) and the evals run without the real service. Control routes under
/__fake/ (never on the real service):

    POST /__fake/op      {"op": "takedown|pause|unpause|ban|set_cap|video_gone|reset", "args": {...}}
    POST /__fake/fault   {"status": 429, "error": "rate", "retryAfter": 60, "field": null,
                          "times": 1, "match": "POST /api/v1/shares"}   # next matching requests fail
    POST /__fake/fail_every  {"n": 3}        # every Nth API request answers 500 (0 turns it off)
    GET  /__fake/log     the API requests so far: [{"method", "path", "status"}]

Run standalone:  python3 tests/fake_share_service.py [PORT]   (prints FAKE_URL: http://127.0.0.1:PORT)
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import sys
import threading
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONTRACT = json.loads((Path(__file__).resolve().parent / "share_contract.json").read_text(encoding="utf-8"))
TERMS = CONTRACT["terms"]
BODY_LIMIT = CONTRACT["bodyLimit"]
ERRORS = CONTRACT["errors"]
REASONS = set(CONTRACT["reasons"])
VERSION = "fake-1"

ID_RE = re.compile(r"^[A-Za-z0-9_-]{22}$")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
MODEL_RE = re.compile(r"^[A-Za-z0-9._:/ -]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NOTES = {"lang-fallback", "local-transcript"}
FORBIDDEN_RE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩\ud800-\udfff]")

# key: (min length, max length, required); every string is checked by _text
TEXT_FIELDS = {
    "title": (1, 300, True), "channel": (0, 200, False), "duration": (0, 40, False),
    "published": (0, 40, False), "summary": (1, 6000, True), "takeaway": (1, 2000, True),
    "model": (0, 80, False),
}
KEY_ORDER = ["v", "videoId", "title", "channel", "channelId", "duration", "durationS", "published",
             "lang", "tags", "summary", "takeaway", "keyPoints", "outline", "model", "notes", "created"]
KP_FIELDS = {"point": (1, 600), "why": (0, 1500), "detail": (0, 4000)}
OL_FIELDS = {"title": (1, 300), "detail": (0, 1500)}


def share_tag_ok(tag: str) -> bool:
    """Share tag pattern (033 §5.1, O7), the Python form of the Worker's
    /^[\\p{Ll}\\p{Lo}\\p{Lm}\\p{Nd}][\\p{Ll}\\p{Lo}\\p{Lm}\\p{Nd}\\p{Mn}\\p{Mc} +#.-]{0,29}$/u."""
    if not isinstance(tag, str) or not 1 <= len(tag) <= 30:
        return False
    first = {"Ll", "Lo", "Lm", "Nd"}
    rest = first | {"Mn", "Mc"}
    return unicodedata.category(tag[0]) in first and all(
        c in " +#.-" or unicodedata.category(c) in rest for c in tag[1:])


class SchemaError(Exception):
    def __init__(self, field):
        super().__init__(field)
        self.field = field


def _int(value, lo, hi):
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


def _text(value, lo, hi, field):
    if not isinstance(value, str):
        raise SchemaError(field)
    value = unicodedata.normalize("NFC", value)
    if FORBIDDEN_RE.search(value) or not lo <= len(value) <= hi:
        raise SchemaError(field)
    return value


def validate_payload(p):
    """The validated, normalised payload in canonical key order, or SchemaError(field)."""
    if not isinstance(p, dict):
        raise SchemaError("payload")
    for key in p:
        if key not in KEY_ORDER:
            raise SchemaError(key)
    for key in ("v", "videoId", "title", "summary", "takeaway", "keyPoints", "outline"):
        if key not in p:
            raise SchemaError(key)
    out = {}
    if p["v"] != 1 or isinstance(p["v"], bool):
        raise SchemaError("v")
    out["v"] = 1
    if not isinstance(p["videoId"], str) or not VIDEO_ID_RE.fullmatch(p["videoId"]):
        raise SchemaError("videoId")
    out["videoId"] = p["videoId"]
    for key, (lo, hi, _required) in TEXT_FIELDS.items():
        out[key] = _text(p.get(key, ""), lo, hi, key)
    if not MODEL_RE.fullmatch(out["model"]):
        raise SchemaError("model")
    for key, pattern in (("channelId", CHANNEL_ID_RE), ("lang", LANG_RE), ("created", DATE_RE)):
        value = p.get(key, "")
        if not isinstance(value, str) or (value and not pattern.fullmatch(value)):
            raise SchemaError(key)
        out[key] = value
    duration_s = p.get("durationS")
    if duration_s is not None and not _int(duration_s, 0, 86400):
        raise SchemaError("durationS")
    out["durationS"] = duration_s
    tags = p.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 5 or not all(isinstance(t, str) and share_tag_ok(unicodedata.normalize("NFC", t)) for t in tags):
        raise SchemaError("tags")
    out["tags"] = [unicodedata.normalize("NFC", t) for t in tags]
    notes = p.get("notes", [])
    if not isinstance(notes, list) or len(notes) > 2 or len(set(notes)) != len(notes) or not set(notes) <= NOTES:
        raise SchemaError("notes")
    out["notes"] = list(notes)
    out["keyPoints"] = _items(p["keyPoints"], "keyPoints", 1, 20, KP_FIELDS)
    out["outline"] = _items(p["outline"], "outline", 0, 100, OL_FIELDS, timed=True)
    return {key: out[key] for key in KEY_ORDER}


def _items(items, field, lo, hi, fields, timed=False):
    if not isinstance(items, list) or not lo <= len(items) <= hi:
        raise SchemaError(field)
    out = []
    for item in items:
        if not isinstance(item, dict) or not set(item) <= set(fields) | ({"t"} if timed else set()):
            raise SchemaError(field)
        clean = {}
        if timed:
            if not _int(item.get("t"), 0, 86400):
                raise SchemaError(field)
            clean["t"] = item["t"]
        for name, (a, b) in fields.items():
            if a and name not in item:
                raise SchemaError(field)
            clean[name] = _text(item.get(name, ""), a, b, field)
        out.append(clean)
    return out


def payload_sha(payload):
    """Hex SHA-256 of JSON.stringify(payload): compact separators, non-ASCII kept."""
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _b64(n):
    return base64.urlsafe_b64encode(secrets.token_bytes(n)).rstrip(b"=").decode()


def _utc_day():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _seconds_to_midnight():
    now = datetime.now(timezone.utc)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))


class ApiError(Exception):
    def __init__(self, code, **extra):
        super().__init__(code)
        self.code = code
        self.extra = extra


class FakeState:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.shares = {}
        self.counters = {}
        self.caps = {"install": 30, "ip": 60, "global": 1000}
        self.paused = False
        self.bans = set()
        self.gone = {CONTRACT["goneVideoId"]}
        self.faults = []
        self.fail_every = 0
        self.api_requests = 0
        self.log = []

    def count(self, key):
        day_key = (_utc_day(), key)
        self.counters[day_key] = self.counters.get(day_key, 0) + 1
        return self.counters[day_key]

    def op(self, name, args):
        if name == "reset":
            self.reset()
        elif name == "pause":
            self.paused = True
        elif name == "unpause":
            self.paused = False
        elif name == "ban":
            self.bans.add(args["install"])
        elif name == "set_cap":
            self.caps[args["name"]] = int(args["n"])
        elif name == "video_gone":
            self.gone.add(args["videoId"])
        elif name == "takedown":
            share = self.shares[args["id"]]
            if args["reason"] not in REASONS:
                raise ValueError("reason")
            share.update(status="removed", reason=args["reason"], payload=None)
        else:
            raise ValueError(name)


class Handler(BaseHTTPRequestHandler):
    server_version = "fake-share"
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    @property
    def state(self) -> FakeState:
        return self.server.state

    def _send(self, status, body, headers=None):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        for k, v in (headers or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(raw)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > BODY_LIMIT:
            self.close_connection = True
            raise ApiError("size")
        return self.rfile.read(length)

    def _route(self, method):
        path = self.path.split("?", 1)[0]
        if path.startswith("/__fake/"):
            return self._control(method, path)
        with self.state.lock:
            status, body, headers = self._api(method, path)
            self.state.log.append({"method": method, "path": path, "status": status})
        self._send(status, body, headers)

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")

    def do_PATCH(self):
        self._route("PATCH")

    def _control(self, method, path):
        st = self.state
        try:
            args = json.loads(self._read_body() or b"{}") if method == "POST" else {}
            with st.lock:
                if method == "GET" and path == "/__fake/log":
                    return self._send(200, st.log)
                if method == "POST" and path == "/__fake/op":
                    st.op(args["op"], args.get("args") or {})
                elif method == "POST" and path == "/__fake/fault":
                    st.faults.append({"times": 1, "match": "", **args})
                elif method == "POST" and path == "/__fake/fail_every":
                    st.fail_every = int(args["n"])
                else:
                    return self._send(404, {"error": "not_found"})
            self._send(200, {"ok": True})
        except (ValueError, KeyError) as e:
            self._send(400, {"error": f"control: {e}"})

    def _api(self, method, path):
        st = self.state
        st.api_requests += 1
        try:
            if st.fail_every and st.api_requests % st.fail_every == 0:
                return 500, {"error": "internal"}, {}
            for fault in st.faults:
                if fault["times"] > 0 and f"{method} {path}".startswith(fault["match"]):
                    fault["times"] -= 1
                    extra = {k: fault[k] for k in ("field", "reason") if fault.get(k)}
                    headers = {"Retry-After": fault["retryAfter"]} if fault.get("retryAfter") else {}
                    return fault["status"], {"error": fault["error"], **extra}, headers
            if method == "GET" and path == "/api/v1/health":
                return 200, {"ok": True, "version": VERSION, "terms": TERMS,
                             "uploads": "paused" if st.paused else "open"}, {}
            if method == "POST" and path == "/api/v1/shares":
                return self._write(None)
            m = re.fullmatch(r"/api/v1/shares/([^/]+)", path)
            if m and method in ("GET", "PUT", "DELETE"):
                share_id = m.group(1)
                share = self._authorised(share_id)
                if method == "GET":
                    out = {"id": share_id, "status": share["status"], "views": share["views"],
                           "created": share["created"], "updated": share["updated"]}
                    if share["reason"]:
                        out["reason"] = share["reason"]
                    return 200, out, {}
                if method == "DELETE":
                    del st.shares[share_id]
                    return 200, {"deleted": True}, {}
                if share["status"] == "removed":
                    raise ApiError("removed", reason=share["reason"])
                return self._write(share_id)
            raise ApiError("not_found")
        except ApiError as e:
            headers = {"Retry-After": _seconds_to_midnight()} if e.code == "rate" else {}
            return ERRORS[e.code], {"error": e.code, **e.extra}, headers

    def _authorised(self, share_id):
        share = self.state.shares.get(share_id)
        auth = self.headers.get("Authorization", "")
        key = auth[7:] if auth.startswith("Bearer ") else ""
        digest = hashlib.sha256(key.encode()).digest()
        if share is None or not key or not hmac.compare_digest(digest, share["manage_hash"]):
            raise ApiError("auth")
        return share

    def _write(self, share_id):
        st = self.state
        install = self.headers.get("X-VL-Install", "")
        if not ID_RE.fullmatch(install):
            raise ApiError("schema", field="install")
        # 033 §7.1 step 1: switch, ban and day counters before the body is read.
        if st.paused:
            raise ApiError("paused")
        if install in st.bans:
            raise ApiError("rate")
        ip = self.client_address[0]
        if st.count("g:w") > st.caps["global"]:
            raise ApiError("paused")
        if st.count(f"i:{install}") > st.caps["install"] or st.count(f"p:{ip}") > st.caps["ip"]:
            raise ApiError("rate")
        raw = self._read_body()
        if len(raw) > BODY_LIMIT:
            raise ApiError("size")
        try:
            body = json.loads(raw)
        except ValueError:
            raise ApiError("schema", field="body")
        if not isinstance(body, dict) or set(body) != {"terms", "install", "payload"}:
            raise ApiError("schema", field="body")
        if body["install"] != install:
            raise ApiError("schema", field="install")
        if body["terms"] != TERMS:
            raise ApiError("terms")
        try:
            payload = validate_payload(body["payload"])
        except SchemaError as e:
            raise ApiError("schema", field=e.field)
        if payload["videoId"] in st.gone:
            raise ApiError("video")
        sha = payload_sha(payload)
        now = int(time.time())
        base = f"http://{self.headers.get('Host')}"
        if share_id is None:
            share_id, key = _b64(16), _b64(32)
            st.shares[share_id] = {"payload": payload, "sha": sha, "install": install, "status": "live",
                                   "reason": None, "created": now, "updated": now, "views": 0,
                                   "manage_hash": hashlib.sha256(key.encode()).digest()}
            return 201, {"id": share_id, "url": f"{base}/s/{share_id}/", "manageKey": key, "sha": sha}, {}
        share = st.shares[share_id]
        if share["sha"] != sha:
            share.update(payload=payload, sha=sha, updated=now)
        return 200, {"id": share_id, "url": f"{base}/s/{share_id}/", "updated": share["updated"], "sha": sha}, {}


class FakeShareService:
    """Start with `with FakeShareService() as fake:`; `fake.url` is the base URL."""

    def __init__(self, port=0):
        self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.server.state = FakeState()
        self.state = self.server.state
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.02},
                                       daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_exc):
        self.server.shutdown()
        self.server.server_close()


if __name__ == "__main__":
    service = FakeShareService(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
    print(f"FAKE_URL: {service.url}", flush=True)
    try:
        service.server.serve_forever()
    except KeyboardInterrupt:
        pass
