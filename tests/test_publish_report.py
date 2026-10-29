"""publish_report.py: the opt-in share step. No network: a fake opener stands in
for deed.page."""
import io
import json
import stat
import sys
import urllib.error
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent.parent / "skills" / "video-lens" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import publish_report as pr  # noqa: E402

REPORT_NAME = "2026-10-27-101500-video-lens_dQw4w9WgXcQ_never-gonna.html"
FAKE_TOKEN = "deed_tok_synthetic_not_a_real_token"


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.error:
            raise self.error
        return FakeResp(json.dumps(self.payload).encode())


def ok(slug, token=None):
    d = {"ok": True, "url": f"https://{slug}.deed.page/", "slug": slug}
    if token:
        d["token"] = token
    return d


@pytest.fixture
def report(tmp_path):
    p = tmp_path / REPORT_NAME
    p.write_text("<!doctype html><title>r</title>", encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def no_env_token(monkeypatch):
    monkeypatch.delenv("DEEDPAGE_TOKEN", raising=False)


def test_default_slug_uses_the_video_id_and_is_valid(report):
    slug = pr.default_slug(report)
    assert slug.startswith("video-lens-dqw4w9wgxcq-")
    assert pr.SLUG_RE.match(slug)
    assert pr.SLUG_RE.match(pr.default_slug("/x/unexpected name.html"))


def test_first_publish_saves_token_0600_and_never_prints_it(report, tmp_path, capsys):
    token_file = tmp_path / "cfg" / "deed-page" / "token"
    opener = FakeOpener(ok("video-lens-abc", FAKE_TOKEN))
    rc = pr.main([str(report), "--slug", "video-lens-abc", "--token-file", str(token_file)],
                 opener=opener)
    out = capsys.readouterr()
    assert rc == 0
    assert "PUBLIC_URL: https://video-lens-abc.deed.page/" in out.out
    assert FAKE_TOKEN not in out.out + out.err
    assert token_file.read_text().strip() == FAKE_TOKEN
    assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
    req = opener.requests[0]
    assert req.get_method() == "PUT"
    assert req.full_url == "https://deed.page/v1/sites?slug=video-lens-abc"
    assert req.get_header("Authorization") is None
    assert req.get_header("X-client") == "video-lens"
    assert req.data == report.read_bytes()


def test_saved_token_is_reused_and_not_overwritten(report, tmp_path, capsys):
    token_file = tmp_path / "token"
    token_file.write_text(FAKE_TOKEN + "\n")
    opener = FakeOpener(ok("video-lens-abc"))
    assert pr.main([str(report), "--slug", "video-lens-abc", "--token-file", str(token_file)],
                   opener=opener) == 0
    assert opener.requests[0].get_header("Authorization") == f"Bearer {FAKE_TOKEN}"
    assert token_file.read_text().strip() == FAKE_TOKEN
    assert FAKE_TOKEN not in capsys.readouterr().out


def test_host_limit_message_is_passed_through(report, tmp_path, capsys):
    body = json.dumps({"ok": False, "error": "site_limit",
                       "user_message": "Free plan allows 25 sites. Upgrade: https://deed.page/pricing"})
    err = urllib.error.HTTPError("u", 402, "Payment Required", {}, io.BytesIO(body.encode()))
    rc = pr.main([str(report), "--token-file", str(tmp_path / "t")], opener=FakeOpener(error=err))
    assert rc == 1
    assert ("ERROR:PUBLISH_REJECTED Free plan allows 25 sites. Upgrade: https://deed.page/pricing"
            in capsys.readouterr().err)


def test_invalid_slug_and_missing_report_fail_before_any_request(report, tmp_path, capsys):
    opener = FakeOpener(ok("x"))
    assert pr.main([str(report), "--slug", "Bad_Slug", "--token-file", str(tmp_path / "t")],
                   opener=opener) == 1
    assert pr.main([str(tmp_path / "missing.html"), "--token-file", str(tmp_path / "t")],
                   opener=opener) == 1
    err = capsys.readouterr().err
    assert "ERROR:PUBLISH_INVALID_SLUG" in err
    assert "ERROR:PUBLISH_REPORT_NOT_FOUND" in err
    assert opener.requests == []
