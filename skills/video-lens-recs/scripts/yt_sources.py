"""YouTube data sources for video-lens-recs: listings, RSS, search, the personal feeds and the
optional Data API (026 §4, §5).

Every network call goes through `_ytdlp` or `_http`, which add three things:

- a 6-hour JSON cache for public fetches (never for the cookie feeds);
- replay: with VIDEO_LENS_RECS_REPLAY=DIR every call is answered from DIR/<key>.json, so
  tests and evals run offline and deterministically;
- record: with VIDEO_LENS_RECS_RECORD=DIR live public responses are also written there.
  Cookie feeds are never recorded. With both set, a replay miss is fetched live and
  recorded, which extends a fixture when the code starts asking for more.

Cookies are only ever passed as `--cookies-from-browser BROWSER` to the three personal feeds
(subscriptions, recent watches, home feed). Public fetches never carry them.
"""
import concurrent.futures
import datetime
import hashlib
import json
import os
import pathlib
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
REPLAY_ENV = "VIDEO_LENS_RECS_REPLAY"
RECORD_ENV = "VIDEO_LENS_RECS_RECORD"
NOW_ENV = "VIDEO_LENS_RECS_NOW"
CACHE_TTL = 6 * 3600
YTDLP_TIMEOUT = 90
HTTP_TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (video-lens-recs)"
API_BASE = "https://www.googleapis.com/youtube/v3/"
# Search "upload date" filter: today / this week / this month / this year, videos only.
SEARCH_SP = ((1, "EgQIAhAB"), (7, "EgQIAxAB"), (31, "EgQIBBAB"), (366, "EgQIBRAB"))


class SourceError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code} {detail}".strip())
        self.code = code
        self.detail = detail


def now() -> float:
    """The run's clock. Replay pins it to the recording time, so ages never drift."""
    return float(os.environ.get(NOW_ENV) or time.time())


# ---------- cache + replay transport ----------

def _key_file(directory, key: str) -> pathlib.Path:
    slug = re.sub(r"[^A-Za-z0-9_.@-]+", "_", key)[:80]
    return pathlib.Path(directory) / f"{slug}.{hashlib.sha256(key.encode()).hexdigest()[:8]}.json"


def _strip(obj):
    """Drop thumbnail lists (most of a listing's bytes) before caching or recording."""
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in ("thumbnails", "formats", "http_headers")}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


class Cache:
    """Small JSON-per-key cache. `ttl=None` on get means 'any age'."""

    def __init__(self, directory):
        self.dir = pathlib.Path(directory) if directory else None

    def get(self, key, ttl=CACHE_TTL):
        if not self.dir or os.environ.get(REPLAY_ENV):
            return None
        p = _key_file(self.dir, key)
        try:
            if ttl is not None and time.time() - p.stat().st_mtime > ttl:
                return None
            return json.loads(p.read_text(encoding="utf-8"))["data"]
        except (OSError, ValueError, KeyError):
            return None

    def put(self, key, data):
        if not self.dir or os.environ.get(REPLAY_ENV):
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            _key_file(self.dir, key).write_text(json.dumps({"key": key, "data": data}, ensure_ascii=False),
                                                encoding="utf-8")
        except OSError:
            pass


def _replay(key):
    directory = os.environ.get(REPLAY_ENV)
    if not directory:
        return None
    p = _key_file(directory, key)
    if not p.exists():
        if os.environ.get(RECORD_ENV) and not key.startswith("personal:"):
            return None
        raise SourceError("REPLAY_MISS", key)
    rec = json.loads(p.read_text(encoding="utf-8"))
    if "error" in rec:
        raise SourceError(rec["error"], rec.get("detail", ""))
    return rec["data"]


def _record(key, data, personal: bool):
    directory = os.environ.get(RECORD_ENV)
    if not directory or personal:
        return
    p = _key_file(directory, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"key": key, "data": data}, ensure_ascii=False), encoding="utf-8")


def classify_ytdlp_error(stderr: str) -> str:
    s = stderr.lower()
    if "could not find" in s and "cookies database" in s or "operation not permitted" in s \
            or "permission denied" in s and "cookies" in s:
        return "COOKIES_UNREADABLE"
    if "sign in to confirm" in s or "not a bot" in s:
        return "BOT_CHECK"
    if "login required" in s or "sign in" in s or "authentication" in s or "cookies are no longer valid" in s:
        return "SIGNED_OUT"
    if "http error 404" in s or "does not exist" in s or "this channel does not exist" in s:
        return "NOT_FOUND"
    if "http error 429" in s or "too many requests" in s:
        return "RATE_LIMITED"
    return "YTDLP_FAILED"


def _ytdlp(args, key, browser=None, mode="json", timeout=YTDLP_TIMEOUT):
    """Run yt-dlp. mode 'json' parses -J output; 'lines' returns stdout lines."""
    replayed = _replay(key)
    if replayed is not None:
        return replayed
    cmd = ["yt-dlp", "--quiet", "--no-warnings", "--ignore-config"]
    if browser:
        cmd += ["--cookies-from-browser", browser]
    cmd += list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise SourceError("YTDLP_MISSING", "yt-dlp not installed — brew install yt-dlp or pip install yt-dlp")
    except subprocess.TimeoutExpired:
        raise SourceError("TIMEOUT", f"yt-dlp took over {timeout}s")
    if mode == "lines":
        if r.returncode != 0 and not r.stdout.strip():
            raise SourceError(classify_ytdlp_error(r.stderr), r.stderr.strip()[-300:])
        data = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    else:
        if not r.stdout.strip():
            raise SourceError(classify_ytdlp_error(r.stderr), r.stderr.strip()[-300:])
        try:
            data = _strip(json.loads(r.stdout))
        except ValueError as e:
            raise SourceError("YTDLP_FAILED", f"bad JSON: {e}")
    _record(key, data, personal=bool(browser))
    return data


def _http(url, key, personal=False, timeout=HTTP_TIMEOUT) -> str:
    replayed = _replay(key)
    if replayed is not None:
        return replayed
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:2000] if e.fp else ""
        raise SourceError(f"HTTP_{e.code}", body)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SourceError("NETWORK_ERROR", str(e))
    _record(key, data, personal)
    return data


def fetch_many(fn, items, workers: int = 8) -> dict:
    """Run fn(item) in parallel; returns {item: result or SourceError}."""
    out = {}
    items = list(dict.fromkeys(items))
    if not items:
        return out
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        futures = {pool.submit(fn, it): it for it in items}
        for fut in concurrent.futures.as_completed(futures):
            it = futures[fut]
            try:
                out[it] = fut.result()
            except SourceError as e:
                out[it] = e
            except Exception as e:  # a parser bug in one source must not fail the run
                out[it] = SourceError("SOURCE_FAILED", repr(e))
    return out


# ---------- parsing ----------

def _entry(e: dict, channel_id="", channel="", subscribers=None, source="") -> dict | None:
    vid = e.get("id") or ""
    if not VIDEO_ID_RE.fullmatch(vid):
        return None
    url = e.get("url") or ""
    ts = e.get("timestamp") or e.get("release_timestamp")
    return {
        "videoId": vid,
        "title": e.get("title") or "",
        "channelId": e.get("channel_id") or channel_id or "",
        "channel": e.get("channel") or e.get("uploader") or channel or "",
        "duration": int(e["duration"]) if isinstance(e.get("duration"), (int, float)) else None,
        "views": int(e["view_count"]) if isinstance(e.get("view_count"), (int, float)) else None,
        "published": float(ts) if ts else None,
        "published_exact": False,
        "description": (e.get("description") or "")[:400],
        "live_status": e.get("live_status"),
        "availability": e.get("availability"),
        "is_short": "/shorts/" in url,
        "subscribers": subscribers,
        "source": source,
    }


def parse_listing(d: dict) -> dict:
    cid = d.get("channel_id") or (d.get("id") if CHANNEL_ID_RE.fullmatch(d.get("id") or "") else "")
    subs = d.get("channel_follower_count")
    channel = d.get("channel") or d.get("uploader") or re.sub(r"\s+-\s+Videos$", "", d.get("title") or "")
    entries = [x for x in (_entry(e, cid, channel, subs) for e in d.get("entries") or []) if x]
    return {"channelId": cid, "channel": channel, "handle": d.get("uploader_id") or "",
            "subscribers": subs, "entries": entries}


ATOM = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
        "media": "http://search.yahoo.com/mrss/"}


def _iso_epoch(s: str) -> float | None:
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def parse_rss(xml_text: str) -> dict:
    root = ET.fromstring(xml_text)
    channel = (root.findtext("a:title", default="", namespaces=ATOM) or "").strip()
    entries = []
    for e in root.findall("a:entry", ATOM):
        vid = e.findtext("yt:videoId", default="", namespaces=ATOM)
        if not VIDEO_ID_RE.fullmatch(vid or ""):
            continue
        stats = e.find("media:group/media:community/media:statistics", ATOM)
        views = stats.get("views") if stats is not None else None
        link = e.find("a:link", ATOM)
        entries.append({
            "videoId": vid,
            "title": e.findtext("a:title", default="", namespaces=ATOM),
            "channelId": e.findtext("yt:channelId", default="", namespaces=ATOM),
            "channel": e.findtext("a:author/a:name", default=channel, namespaces=ATOM),
            "published": _iso_epoch(e.findtext("a:published", default="", namespaces=ATOM)),
            "published_exact": True,
            "views": int(views) if views and views.isdigit() else None,
            "description": (e.findtext("media:group/media:description", default="", namespaces=ATOM) or "")[:400],
            "is_short": "/shorts/" in (link.get("href", "") if link is not None else ""),
        })
    return {"channel": channel, "entries": entries}


# ---------- public sources ----------

def channel_listing(channel: str, cache: Cache | None = None, limit: int = 30) -> dict:
    """A channel's last `limit` uploads from its /videos tab (no Shorts, no lives).

    `channel` is a UC… id, an @handle or a channel URL.
    """
    if CHANNEL_ID_RE.fullmatch(channel):
        url = f"https://www.youtube.com/channel/{channel}/videos"
    elif channel.startswith("@"):
        url = f"https://www.youtube.com/{channel}/videos"
    else:
        url = channel.rstrip("/")
        if not url.endswith("/videos"):
            url += "/videos"
    key = f"listing:{channel}:{limit}"
    if cache and (hit := cache.get(key)) is not None:
        return hit
    raw = _ytdlp(["--flat-playlist", "-J", "--playlist-end", str(limit),
                  "--extractor-args", "youtubetab:approximate_date", url], key)
    data = parse_listing(raw)
    if cache:
        cache.put(key, data)
    return data


def channel_rss(channel_id: str, cache: Cache | None = None, long_form_only: bool = True) -> dict:
    """Exact dates, exact views and descriptions of the last 15 uploads. `UULF…` is the
    long-form-only uploads playlist; it falls back to the channel feed."""
    key = f"rss:{channel_id}"
    if cache and (hit := cache.get(key)) is not None:
        return hit
    urls = []
    if long_form_only and CHANNEL_ID_RE.fullmatch(channel_id):
        urls.append(f"https://www.youtube.com/feeds/videos.xml?playlist_id=UULF{channel_id[2:]}")
    urls.append(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}")
    last = None
    for i, url in enumerate(urls):
        try:
            data = parse_rss(_http(url, f"{key}:{i}"))
            for e in data["entries"]:
                e["channelId"] = e["channelId"] or channel_id
            if cache:
                cache.put(key, data)
            return data
        except SourceError as e:
            last = e
        except ET.ParseError as e:
            last = SourceError("RSS_PARSE", str(e))
    raise last


def search_sp(window_days: int) -> str:
    return next((sp for days, sp in SEARCH_SP if window_days <= days), SEARCH_SP[-1][1])


def search(query: str, window_days: int, cache: Cache | None = None, limit: int = 20) -> list[dict]:
    sp = search_sp(window_days)
    key = f"search:{sp}:{limit}:{query.lower()}"
    if cache and (hit := cache.get(key)) is not None:
        return hit
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": query, "sp": sp})
    raw = _ytdlp(["--flat-playlist", "-J", "--playlist-end", str(limit), url], key)
    entries = [x for x in (_entry(e, source="search") for e in raw.get("entries") or []) if x]
    for e in entries:
        e["query"] = query
    if cache:
        cache.put(key, entries)
    return entries


def video_channel(video_id: str, cache: Cache | None = None) -> dict:
    """Channel id and name of one video (2–3 s of full extraction; cached for good)."""
    key = f"video_channel:{video_id}"
    if cache and (hit := cache.get(key, ttl=None)) is not None:
        return hit
    lines = _ytdlp(["--skip-download", "--print", "%(channel_id)s\t%(channel)s",
                    f"https://www.youtube.com/watch?v={video_id}"], key, mode="lines")
    cid, _, name = (lines[0] if lines else "").partition("\t")
    if not CHANNEL_ID_RE.fullmatch(cid):
        raise SourceError("NOT_FOUND", f"no channel for {video_id}")
    data = {"channelId": cid, "channel": name}
    if cache:
        cache.put(key, data)
    return data


# ---------- personal feeds (cookies; live mode only; never cached or recorded) ----------

def subscriptions_live(browser: str) -> list[dict]:
    raw = _ytdlp(["--flat-playlist", "-J", "https://www.youtube.com/feed/channels"],
                 "personal:subscriptions", browser=browser)
    out, seen = [], set()
    for e in raw.get("entries") or []:
        cid = e.get("channel_id") or e.get("id") or ""
        if not CHANNEL_ID_RE.fullmatch(cid):
            m = re.search(r"/channel/(UC[A-Za-z0-9_-]{22})", e.get("url") or "")
            cid = m.group(1) if m else ""
        if not cid or cid in seen:
            continue
        seen.add(cid)
        out.append({"id": cid, "title": e.get("channel") or e.get("title") or "",
                    "url": f"https://www.youtube.com/channel/{cid}",
                    "subscribers": e.get("channel_follower_count")})
    if not out:
        raise SourceError("SIGNED_OUT", "the subscriptions feed came back empty")
    return out


def recent_watch_ids(browser: str, depth: int) -> list[str]:
    """IDs of the last `depth` history entries, newest first. The caller keeps them in
    memory only (026 §5.6); nothing here caches or records them."""
    lines = _ytdlp(["--flat-playlist", "--print", "id", "--playlist-end", str(depth), ":ythistory"],
                   "personal:history", browser=browser, mode="lines", timeout=180)
    return [l for l in lines if VIDEO_ID_RE.fullmatch(l)]


def home_feed(browser: str, limit: int = 100) -> list[dict]:
    raw = _ytdlp(["--flat-playlist", "-J", "--playlist-end", str(limit), ":ytrec"],
                 "personal:home", browser=browser)
    entries = [x for x in (_entry(e, source="home") for e in raw.get("entries") or []) if x]
    return entries


# ---------- YouTube Data API (optional key) ----------

def _iso_duration(s: str) -> int | None:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def _api(path: str, params: dict, key: str, cache_key: str) -> dict:
    url = API_BASE + path + "?" + urllib.parse.urlencode({**params, "key": key})
    try:
        return json.loads(_http(url, cache_key))
    except SourceError as e:
        reason = ""
        try:
            reason = json.loads(e.detail)["error"]["errors"][0]["reason"]
        except (ValueError, KeyError, IndexError, TypeError):
            pass
        if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
            raise SourceError("API_QUOTA", reason)
        if reason in ("keyInvalid", "badRequest", "forbidden", "accessNotConfigured") or e.code in ("HTTP_400", "HTTP_403"):
            raise SourceError("API_KEY", reason or e.code)
        raise


def api_search(query: str, window_days: int, key: str, lang: str = "", limit: int = 20) -> list[str]:
    after = datetime.datetime.fromtimestamp(now() - window_days * 86400, datetime.timezone.utc)
    params = {"part": "id", "type": "video", "q": query, "maxResults": limit, "order": "relevance",
              "publishedAfter": after.strftime("%Y-%m-%dT%H:%M:%SZ")}
    if lang:
        params["relevanceLanguage"] = lang
    data = _api("search", params, key, f"api_search:{window_days}:{lang}:{query.lower()}")
    return [it["id"]["videoId"] for it in data.get("items", []) if it.get("id", {}).get("videoId")]


def api_videos(ids, key: str) -> dict:
    out = {}
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        data = _api("videos", {"part": "snippet,contentDetails,statistics", "id": ",".join(chunk)},
                    key, "api_videos:" + ",".join(chunk))
        for it in data.get("items", []):
            sn, st, cd = it.get("snippet", {}), it.get("statistics", {}), it.get("contentDetails", {})
            out[it["id"]] = {
                "videoId": it["id"], "title": sn.get("title", ""),
                "channelId": sn.get("channelId", ""), "channel": sn.get("channelTitle", ""),
                "published": _iso_epoch(sn.get("publishedAt", "")), "published_exact": True,
                "views": int(st["viewCount"]) if st.get("viewCount", "").isdigit() else None,
                "duration": _iso_duration(cd.get("duration", "")),
                "description": (sn.get("description") or "")[:400],
                "live_status": "is_upcoming" if sn.get("liveBroadcastContent") == "upcoming"
                               else "is_live" if sn.get("liveBroadcastContent") == "live" else None,
                "language": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage") or "",
            }
    return out


def api_channels(ids, key: str) -> dict:
    out = {}
    ids = list(dict.fromkeys(ids))
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        data = _api("channels", {"part": "statistics", "id": ",".join(chunk)}, key,
                    "api_channels:" + ",".join(chunk))
        for it in data.get("items", []):
            n = it.get("statistics", {}).get("subscriberCount", "")
            out[it["id"]] = int(n) if n.isdigit() else None
    return out
