#!/usr/bin/env python3
"""Publish one rendered report to a public deed.page URL — only on request.

Usage:
    python3 publish_report.py REPORT.html
    python3 publish_report.py REPORT.html --slug SLUG   # update the same URL

Opt-in follow-up, never part of Steps 1-6: run it only when the user asks for a
link to share a report. It uploads that one HTML file, as index.html, to
deed.page (https://deed.page/docs), a third-party static host that needs no
account. The page is public. Served over HTTPS, the embedded YouTube player
works there just as it does on localhost:8765.

The first publish returns an owner token. It is saved to
~/.config/deed-page/token (mode 0600) and reused for later publishes, so a
revision can update the same URL. The token is never printed. DEEDPAGE_TOKEN
in the environment takes precedence over the file.

Prints on success:
    PUBLIC_URL: https://<slug>.deed.page/
    PUBLIC_SLUG: <slug>
Prints ERROR:PUBLISH_* to stderr and exits 1 on failure. A host-side limit
error carries the host's own message, to show the user verbatim.

Stdlib only. Network calls: one request to deed.page.
"""
import argparse
import json
import os
import pathlib
import re
import secrets
import sys
import urllib.error
import urllib.request

API = "https://deed.page/v1/sites"
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
DEFAULT_TOKEN_FILE = pathlib.Path.home() / ".config" / "deed-page" / "token"
MAX_BYTES = 4 * 1024 * 1024  # deed.page's single-request body cap


class PublishError(Exception):
    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def default_slug(report):
    """video-lens-<video id>-<4 random chars>, from the renderer's filename
    YYYY-MM-DD-HHMMSS-video-lens_<VIDEO_ID>_<slug>.html."""
    m = re.search(r"video-lens_([A-Za-z0-9_-]{6,})_", pathlib.Path(report).name)
    vid = re.sub(r"[^a-z0-9]+", "-", (m.group(1) if m else "report").lower()).strip("-")
    return f"video-lens-{vid[:30].strip('-') or 'report'}-{secrets.token_hex(2)}"


def load_token(token_file):
    env = os.environ.get("DEEDPAGE_TOKEN", "").strip()
    if env:
        return env
    try:
        return pathlib.Path(token_file).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def save_token(token_file, token):
    path = pathlib.Path(token_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token + "\n")
    os.chmod(path, 0o600)


def publish(report, slug, token=None, ttl=None, opener=urllib.request.urlopen):
    if not SLUG_RE.match(slug):
        raise PublishError("PUBLISH_INVALID_SLUG",
                           f"{slug!r}: use lowercase letters, digits and hyphens")
    body = pathlib.Path(report).read_bytes()
    if len(body) > MAX_BYTES:
        raise PublishError("PUBLISH_TOO_LARGE", f"{len(body)} bytes exceeds the 4 MB request cap")
    headers = {"Content-Type": "text/html; charset=utf-8", "X-Client": "video-lens"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if ttl:
        headers["X-Ttl"] = str(int(ttl))
    req = urllib.request.Request(f"{API}?slug={slug}", data=body, headers=headers, method="PUT")
    try:
        with opener(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))
        except (ValueError, OSError):
            err = {}
        msg = err.get("user_message") or err.get("message") or err.get("error") or f"HTTP {e.code}"
        raise PublishError("PUBLISH_REJECTED", msg) from None
    except (urllib.error.URLError, OSError) as e:
        raise PublishError("PUBLISH_NETWORK_ERROR", str(e)) from None
    if not data.get("ok") or not data.get("url"):
        raise PublishError("PUBLISH_REJECTED", data.get("user_message") or "unexpected response")
    return data


def main(argv=None, opener=urllib.request.urlopen):
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("report")
    ap.add_argument("--slug")
    ap.add_argument("--token-file", default=str(DEFAULT_TOKEN_FILE))
    ap.add_argument("--ttl", type=int, help=argparse.SUPPRESS)  # seconds; for tests
    args = ap.parse_args(argv)
    if not pathlib.Path(args.report).is_file():
        print(f"ERROR:PUBLISH_REPORT_NOT_FOUND {args.report}", file=sys.stderr)
        return 1
    token = load_token(args.token_file)
    try:
        data = publish(args.report, args.slug or default_slug(args.report),
                       token=token, ttl=args.ttl, opener=opener)
    except PublishError as e:
        print(f"ERROR:{e.code} {e.detail}", file=sys.stderr)
        return 1
    if data.get("token") and not token:
        save_token(args.token_file, data["token"])
    print(f"PUBLIC_URL: {data['url']}")
    print(f"PUBLIC_SLUG: {data['slug']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
