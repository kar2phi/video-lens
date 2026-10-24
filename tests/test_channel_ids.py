"""channelId in the report meta block (026 §9.1, P5): fetch_metadata's sidecar, the
renderer, the preflight sweep and the gallery backfill. No network."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = REPO_ROOT / "skills" / "video-lens" / "scripts"
GALLERY_DIR = REPO_ROOT / "skills" / "video-lens-gallery" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

VIDEO_ID = "bjdBVZa66oU"
CHANNEL_ID = "UC" + "q" * 22


def _modules(tmp_path, monkeypatch):
    """Point both scripts' METADATA_DIR at a temp dir (no reload: other tests hold their classes)."""
    import fetch_metadata
    import render_report
    meta_dir = tmp_path / "cache" / "video-lens" / "metadata"
    monkeypatch.setattr(fetch_metadata, "METADATA_DIR", meta_dir)
    monkeypatch.setattr(render_report, "METADATA_DIR", meta_dir)
    return fetch_metadata, render_report


def payload(**kw):
    p = {"VIDEO_ID": VIDEO_ID, "VIDEO_TITLE": "T", "VIDEO_URL": f"https://www.youtube.com/watch?v={VIDEO_ID}",
         "SUMMARY": "S.", "TAKEAWAY": "T.", "KEY_POINTS": "<li><strong>K</strong> — x</li>",
         "OUTLINE": "", "DESCRIPTION_SECTION": "", "CHANNEL": "Chan"}
    p.update(kw)
    return p


def test_sidecar_feeds_the_meta_block(tmp_path, monkeypatch):
    fm, rr = _modules(tmp_path, monkeypatch)
    fm.write_sidecar(VIDEO_ID, {"channel_id": CHANNEL_ID, "channel": "Chan"})
    side = json.loads((tmp_path / "cache" / "video-lens" / "metadata" / f"{VIDEO_ID}.json").read_text())
    assert side["channelId"] == CHANNEL_ID
    meta = json.loads(rr.sanitise_payload(payload(), "/x/r.html")["VIDEO_LENS_META"].replace("<\\/", "</"))
    assert meta["channelId"] == CHANNEL_ID


def test_payload_channel_id_wins_and_invalid_ids_are_dropped(tmp_path, monkeypatch):
    fm, rr = _modules(tmp_path, monkeypatch)
    fm.write_sidecar(VIDEO_ID, {"channel_id": CHANNEL_ID})
    other = "UC" + "z" * 22
    meta = json.loads(rr.sanitise_payload(payload(CHANNEL_ID=other), "/x/r.html")["VIDEO_LENS_META"])
    assert meta["channelId"] == other
    fm.write_sidecar(VIDEO_ID, {"channel_id": "not-a-channel"})
    meta = json.loads(rr.sanitise_payload(payload(CHANNEL_ID="junk"), "/x/r.html")["VIDEO_LENS_META"])
    assert "channelId" not in meta


def test_no_sidecar_no_channel_id(tmp_path, monkeypatch):
    _, rr = _modules(tmp_path, monkeypatch)
    meta = json.loads(rr.sanitise_payload(payload(), "/x/r.html")["VIDEO_LENS_META"])
    assert "channelId" not in meta


def test_fetch_metadata_prints_the_channel_id_line():
    src = (SCRIPT_DIR / "fetch_metadata.py").read_text(encoding="utf-8")
    assert "YTDLP_CHANNEL_ID: " in src


def test_preflight_sweeps_old_sidecars(tmp_path):
    import preflight
    meta_dir = tmp_path / "metadata"
    meta_dir.mkdir()
    old, new = meta_dir / "old00000000.json", meta_dir / "new00000000.json"
    old.write_text("{}")
    new.write_text("{}")
    past = time.time() - preflight.PAYLOAD_TTL_SECONDS - 60
    os.utime(old, (past, past))
    preflight.sweep_stale_sidecars(meta_dir)
    assert not old.exists() and new.exists()


def _report(path: Path, video_id: str, channel: str, channel_id: str = ""):
    meta = {"videoId": video_id, "title": "t", "channel": channel, "tags": []}
    if channel_id:
        meta["channelId"] = channel_id
    path.write_text('<html><body><script type="application/json" id="video-lens-meta">'
                    + json.dumps(meta) + "</script></body></html>", encoding="utf-8")


def test_backfill_adds_channel_ids_by_name(tmp_path):
    reports = tmp_path / "lib" / "reports"
    reports.mkdir(parents=True)
    _report(reports / "2026-01-01-000000-video-lens_aaaaaaaaaaa_x.html", "aaaaaaaaaaa", "Known", CHANNEL_ID)
    _report(reports / "2026-01-02-000000-video-lens_bbbbbbbbbbb_x.html", "bbbbbbbbbbb", "Known")
    _report(reports / "2026-01-03-000000-video-lens_ccccccccccc_x.html", "ccccccccccc", "Subscribed One")
    _report(reports / "2026-01-04-000000-video-lens_ddddddddddd_x.html", "ddddddddddd", "Stranger")
    data = tmp_path / "data" / "video-lens" / "recs"
    data.mkdir(parents=True)
    sub_id = "UC" + "s" * 22
    (data / "subscriptions.json").write_text(json.dumps({"channels": [{"id": sub_id, "title": "Subscribed One"}]}))
    env = {**os.environ, "XDG_DATA_HOME": str(tmp_path / "data"), "XDG_CACHE_HOME": str(tmp_path / "cache")}
    r = subprocess.run([sys.executable, str(GALLERY_DIR / "backfill_meta.py"), "--dir", str(tmp_path / "lib"),
                        "--channel-ids"], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert "Channel ids: 2 added, 1 still unknown (rerun with --lookup to ask yt-dlp)." in r.stdout

    def meta(name):
        html = (reports / name).read_text()
        return json.loads(html.split('id="video-lens-meta">')[1].split("</script>")[0])

    assert meta("2026-01-02-000000-video-lens_bbbbbbbbbbb_x.html")["channelId"] == CHANNEL_ID
    assert meta("2026-01-03-000000-video-lens_ccccccccccc_x.html")["channelId"] == sub_id
    assert "channelId" not in meta("2026-01-04-000000-video-lens_ddddddddddd_x.html")
