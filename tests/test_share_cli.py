"""033 §6 (P3): share_report.py against the fake share service.

Every test runs with HOME, XDG_CONFIG_HOME and XDG_DATA_HOME in a temp dir, a report
rendered from the golden payload into <HOME>/Downloads/video-lens/reports/, and
VIDEO_LENS_SHARE_URL pointing at tests/fake_share_service.py. All stdout and stderr is
collected, and at teardown no manage key from the registry may appear in it.
"""
import json
import os
import stat
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "skills" / "video-lens" / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_report as rr  # noqa: E402
import share_report as sr  # noqa: E402
from fake_share_service import CONTRACT, FakeShareService  # noqa: E402

TERMS = CONTRACT["terms"]
GOLDEN = REPO_ROOT / "tests" / "golden"


@pytest.fixture(scope="module")
def service():
    with FakeShareService() as fake:
        yield fake


@pytest.fixture
def fake(service):
    with service.state.lock:
        service.state.reset()
    return service


class Env:
    def __init__(self, home: Path, fake, capsys):
        self.home = home
        self.fake = fake
        self.capsys = capsys
        self.outputs: list[str] = []
        self.reports = home / "Downloads" / "video-lens" / "reports"
        self.reports.mkdir(parents=True)

    def run(self, *argv):
        code = sr.main([str(a) for a in argv])
        cap = self.capsys.readouterr()
        self.outputs += [cap.out, cap.err]
        return code, cap.out, cap.err

    def report(self, name="2026-01-01-video-lens-bjdBVZa66oU.html", **overrides) -> Path:
        payload = json.loads((GOLDEN / "share_payload.json").read_text(encoding="utf-8"))
        payload.update(overrides)
        path = self.reports / name
        rr.render_from_payload(payload, str(path))
        return path

    def config(self) -> dict:
        return json.loads(sr.config_path().read_text(encoding="utf-8"))

    def registry(self) -> list:
        return json.loads(sr.registry_path().read_text(encoding="utf-8"))["shares"]

    def accept(self):
        assert self.run("terms", "--accept")[0] == 0

    def api_log(self) -> list:
        with self.fake.state.lock:
            return [f"{e['method']} {e['path']} {e['status']}" for e in self.fake.state.log]

    def fault(self, **spec):
        with self.fake.state.lock:
            self.fake.state.faults.append({"times": 1, "match": "", **spec})


@pytest.fixture
def env(tmp_path, monkeypatch, fake, capsys):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    monkeypatch.setenv("VIDEO_LENS_SHARE_URL", fake.url)
    monkeypatch.setattr(rr, "METADATA_DIR", tmp_path / "metadata")
    monkeypatch.setattr(sr.time, "sleep", lambda _s: None)
    e = Env(home, fake, capsys)
    yield e
    keys = [s.get("manageKey") for s in (e.registry() if sr.registry_path().exists() else [])]
    with fake.state.lock:
        keys += [k for k in getattr(fake, "_issued", [])]
    text = "".join(e.outputs)
    for key in filter(None, keys):
        assert key not in text, "a manage key reached the output"


@pytest.fixture(autouse=True)
def record_issued_keys(monkeypatch, fake):
    """Keep every manage key the fake hands out, so deleted shares are checked too."""
    fake._issued = []
    real = sr._once

    def spy(method, url, data, headers, timeout):
        resp = real(method, url, data, headers, timeout)
        if isinstance(resp.body.get("manageKey"), str):
            fake._issued.append(resp.body["manageKey"])
        return resp

    monkeypatch.setattr(sr, "_once", spy)


def lines(text: str, prefix: str) -> list[str]:
    return [line[len(prefix):].strip() for line in text.splitlines() if line.startswith(prefix)]


# ── share, re-share, --new-link ──────────────────────────────────────────────

def test_share_creates_a_link(env):
    env.accept()
    path = env.report()
    code, out, err = env.run("report", path)
    assert code == 0, err
    (url,), (share_id,) = lines(out, "SHARE_URL:"), lines(out, "SHARE_ID:")
    assert url == f"{env.fake.url}/s/{share_id}/"
    assert share_id in env.fake.state.shares
    (entry,) = env.registry()
    assert entry["id"] == share_id and entry["url"] == url
    assert entry["source"] == os.path.realpath(path)
    assert entry["payload_sha"] == env.fake.state.shares[share_id]["sha"]
    assert {"manageKey", "created", "updated"} <= set(entry)
    assert stat.S_IMODE(sr.registry_path().stat().st_mode) == 0o600
    assert stat.S_IMODE(sr.config_path().stat().st_mode) == 0o600


def test_share_sends_install_header_and_user_agent(env, monkeypatch):
    env.accept()
    seen = []
    real = sr._once
    monkeypatch.setattr(sr, "_once", lambda m, u, d, h, t: (seen.append((m, h, d)), real(m, u, d, h, t))[1])
    env.run("report", env.report())
    method, headers, data = seen[-1]
    install = env.config()["install"]
    assert method == "POST"
    assert headers["X-VL-Install"] == install
    assert "install" not in json.loads(data)
    assert json.loads(data)["terms"] == TERMS
    assert headers["User-Agent"] == f"video-lens-share/{sr.skill_version()}"
    assert sr.skill_version() not in ("", "0")


def test_reshare_keeps_the_id_and_updates(env):
    env.accept()
    path = env.report()
    _, out1, _ = env.run("report", path)
    first = lines(out1, "SHARE_ID:")[0]
    old_sha = env.fake.state.shares[first]["sha"]

    code, out2, err = env.run("report", path)          # unchanged: PUT, same ID
    assert code == 0, err
    assert lines(out2, "SHARE_ID:") == [first]

    env.report(TAKEAWAY="A different takeaway.")        # same file, new content
    code, out3, err = env.run("report", path)
    assert code == 0, err
    assert lines(out3, "SHARE_ID:") == [first]
    assert env.fake.state.shares[first]["sha"] != old_sha
    assert env.registry()[0]["payload_sha"] == env.fake.state.shares[first]["sha"]
    assert len(env.fake.state.shares) == 1 and len(env.registry()) == 1
    assert [x.split()[0] for x in env.api_log() if "/shares" in x] == ["POST", "PUT", "PUT"]


def test_new_link_creates_a_fresh_share_and_deletes_the_old(env):
    env.accept()
    path = env.report()
    _, out1, _ = env.run("report", path)
    old = lines(out1, "SHARE_ID:")[0]
    code, out2, err = env.run("report", path, "--new-link")
    assert code == 0, err
    new = lines(out2, "SHARE_ID:")[0]
    assert new != old
    assert set(env.fake.state.shares) == {new}
    assert [s["id"] for s in env.registry()] == [new]


def test_two_reports_get_two_links(env):
    env.accept()
    a = lines(env.run("report", env.report("a.html"))[1], "SHARE_ID:")
    b = lines(env.run("report", env.report("b.html"))[1], "SHARE_ID:")
    assert a != b and len(env.registry()) == 2


# ── install ID ───────────────────────────────────────────────────────────────

def test_install_id_is_created_once_at_the_first_upload(env):
    env.accept()
    assert "install" not in env.config()
    env.run("report", env.report("a.html"))
    install = env.config()["install"]
    assert sr.ID_RE.fullmatch(install)
    env.run("report", env.report("b.html"))
    env.run("report", env.report("a.html"))
    env.run("offer", "off")
    assert env.config()["install"] == install
    assert {s["install"] for s in env.fake.state.shares.values()} == {install}


def test_deleting_the_config_gives_a_new_install_id(env):
    env.accept()
    env.run("report", env.report())
    first = env.config()["install"]
    sr.config_path().unlink()
    env.accept()
    env.run("report", env.report("b.html"))
    assert env.config()["install"] != first


# ── revoke and list ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("by", ["id", "url", "path"])
def test_revoke(env, by):
    env.accept()
    path = env.report()
    _, out, _ = env.run("report", path)
    share_id, url = lines(out, "SHARE_ID:")[0], lines(out, "SHARE_URL:")[0]
    target = {"id": share_id, "url": url, "path": str(path)}[by]
    code, out, err = env.run("revoke", target)
    assert code == 0, err
    assert lines(out, "REVOKED:") == [share_id]
    assert share_id not in env.fake.state.shares
    assert env.registry() == []


def test_revoke_an_id_that_starts_with_a_dash(env):
    env.accept()
    path = env.report()
    old = lines(env.run("report", path)[1], "SHARE_ID:")[0]
    dash_id = "-" + old[1:]
    with env.fake.state.lock:
        env.fake.state.shares[dash_id] = env.fake.state.shares.pop(old)
    shares = env.registry()
    shares[0]["id"] = dash_id
    sr.save_registry(shares)
    code, out, err = env.run("revoke", dash_id)
    assert code == 0, err
    assert out.strip() == f"REVOKED: {dash_id}"
    assert env.fake.state.shares == {}


def test_revoke_unknown_target(env):
    code, _, err = env.run("revoke", "A" * 22)
    assert code == 1 and err.startswith("ERROR:SHARE_INPUT:")


def test_revoke_when_the_service_already_deleted_it(env):
    env.accept()
    share_id = lines(env.run("report", env.report())[1], "SHARE_ID:")[0]
    del env.fake.state.shares[share_id]
    code, out, _ = env.run("revoke", share_id)
    assert code == 0 and lines(out, "REVOKED:") == [share_id]
    assert env.registry() == []


def test_list_states(env):
    env.accept()
    a, b, c = env.report("a.html"), env.report("b.html"), env.report("c.html")
    ids = [lines(env.run("report", p)[1], "SHARE_ID:")[0] for p in (a, b, c)]
    env.fake.state.shares[ids[0]]["views"] = 7
    with b.open("a", encoding="utf-8") as f:
        f.write("\n")
    with env.fake.state.lock:
        env.fake.state.op("takedown", {"id": ids[2], "reason": "spam"})

    code, out, err = env.run("list")
    assert code == 0, err
    rows = {r.split()[0]: r.split(maxsplit=4) for r in lines(out, "SHARE:")}
    assert rows[ids[0]][1:4] == ["7", rows[ids[0]][2], "current"]
    assert rows[ids[0]][4] == 'What are skills? & <why> "quotes"'
    assert len(rows[ids[0]][2]) == 10 and rows[ids[0]][2][4] == "-"
    assert rows[ids[1]][3] == "outdated"
    assert rows[ids[2]][3] == "removed:spam"


def test_list_shows_the_takedown_reason_and_gone(env):
    env.accept()
    a, b = env.report("a.html"), env.report("b.html")
    ids = [lines(env.run("report", p)[1], "SHARE_ID:")[0] for p in (a, b)]
    with env.fake.state.lock:
        env.fake.state.op("takedown", {"id": ids[0], "reason": "copyright"})
    del env.fake.state.shares[ids[1]]   # deleted elsewhere: the service answers 401
    code, out, err = env.run("list")
    assert code == 0, err
    rows = {r.split()[0]: r.split(maxsplit=4) for r in lines(out, "SHARE:")}
    assert rows[ids[0]][3] == "removed:copyright"
    assert rows[ids[1]][3] == "gone"


def test_list_empty(env):
    code, out, _ = env.run("list")
    assert code == 0 and out.strip() == "SHARES: none"


# ── terms flow ───────────────────────────────────────────────────────────────

def test_terms_flow(env):
    path = env.report()
    code, out, err = env.run("report", path)
    assert code == 2 and out == ""
    assert err.startswith("ERROR:SHARE_TERMS:")
    assert f"{env.fake.url}/legal/terms" in err
    assert env.fake.state.shares == {}

    code, out, _ = env.run("terms")
    assert code == 0
    assert lines(out, "TERMS_URL:") == [f"{env.fake.url}/legal/terms"]
    assert lines(out, "TERMS_VERSION:") == [TERMS]
    assert lines(out, "TERMS_ACCEPTED:") == ["no"]

    code, out, _ = env.run("terms", "--accept")
    assert code == 0 and lines(out, "TERMS_ACCEPTED:") == ["yes"]
    assert env.config()["terms_accepted"] == TERMS

    code, out, err = env.run("report", path)
    assert code == 0, err
    assert lines(out, "SHARE_URL:")


def test_changed_terms_ask_again(env):
    sr.save_config({"terms_accepted": "2000-01-01"})
    code, _, err = env.run("report", env.report())
    assert code == 2 and err.startswith("ERROR:SHARE_TERMS:")
    assert lines(env.run("terms")[1], "TERMS_ACCEPTED:") == ["no"]


# ── offer ─────────────────────────────────────────────────────────

def test_offer_on_off(env):
    assert sr.load_config()["offer"] is True                # default without a config
    code, out, _ = env.run("offer", "off")
    assert code == 0 and out.strip() == "OFFER: off"
    assert env.config()["offer"] is False
    env.run("offer", "on")
    assert env.config()["offer"] is True


def test_service_url_from_config_and_default(env, monkeypatch):
    monkeypatch.delenv("VIDEO_LENS_SHARE_URL")
    assert sr.service_url(sr.load_config()) == sr.DEFAULT_SERVICE_URL
    sr.save_config({"service_url": "https://example.org/"})
    assert sr.service_url(sr.load_config()) == "https://example.org"


# ── input errors ─────────────────────────────────────────────────────────────

def test_path_outside_reports_is_rejected(env, tmp_path):
    env.accept()
    outside = tmp_path / "elsewhere.html"
    rr.render_from_payload(json.loads((GOLDEN / "share_payload.json").read_text()), str(outside))
    code, _, err = env.run("report", outside)
    assert code == 1 and err.startswith("ERROR:SHARE_INPUT:")
    link = env.reports / "link.html"
    link.symlink_to(outside)
    code, _, err = env.run("report", link)
    assert code == 1 and err.startswith("ERROR:SHARE_INPUT:")
    code, _, err = env.run("report", env.reports / ".." / ".." / "x.html")
    assert code == 1 and err.startswith("ERROR:SHARE_INPUT:")
    assert env.fake.state.shares == {}


def test_missing_file_and_non_report(env):
    env.accept()
    assert env.run("report", env.reports / "nope.html")[2].startswith("ERROR:SHARE_INPUT:")
    (env.reports / "plain.html").write_text("<html></html>")
    assert env.run("report", env.reports / "plain.html")[2].startswith("ERROR:SHARE_INPUT:")


def test_report_without_data_block(env):
    env.accept()
    path = env.report()
    html = path.read_text(encoding="utf-8")
    path.write_text(sr.DATA_RE.sub("", html), encoding="utf-8")
    code, _, err = env.run("report", path)
    assert code == 1 and err.startswith("ERROR:SHARE_NO_DATA:")


def test_video_id_mismatch_and_missing_keys(env):
    env.accept()
    path = env.report()
    html = path.read_text(encoding="utf-8")
    path.write_text(html.replace('"videoId": "bjdBVZa66oU"', '"videoId": "BBBBBBBBBBB"', 1), encoding="utf-8")
    assert env.run("report", path)[2].startswith("ERROR:SHARE_INPUT:")
    data = json.loads(sr.DATA_RE.search(html).group(1))
    del data["takeaway"]
    path.write_text(sr.DATA_RE.sub(lambda m: m.group(0).replace(m.group(1), json.dumps(data).replace("</", "<\\/")), html),
                    encoding="utf-8")
    code, _, err = env.run("report", path)
    assert code == 1 and err.startswith("ERROR:SHARE_SCHEMA: takeaway")


def test_body_over_128_kib_is_rejected_locally(env, monkeypatch):
    env.accept()
    monkeypatch.setattr(sr, "BODY_LIMIT", 100)
    code, _, err = env.run("report", env.report())
    assert code == 1 and err.startswith("ERROR:SHARE_INPUT:")
    assert env.api_log() == ["GET /api/v1/health 200"]


# ── service errors and retries ───────────────────────────────────────────────

@pytest.mark.parametrize("fault,code_prefix", [
    ({"status": 400, "error": "schema", "field": "title"}, "ERROR:SHARE_SCHEMA: title"),
    ({"status": 400, "error": "video"}, "ERROR:SHARE_VIDEO:"),
    ({"status": 413, "error": "size"}, "ERROR:SHARE_INPUT:"),
    ({"status": 503, "error": "paused"}, "ERROR:SHARE_PAUSED:"),
    ({"status": 429, "error": "rate", "retryAfter": 3600}, "ERROR:SHARE_RATE:"),
    ({"status": 418, "error": "teapot"}, "ERROR:SHARE_HTTP:"),
])
def test_service_errors_are_not_retried(env, fault, code_prefix):
    env.accept()
    env.fault(match="POST /api/v1/shares", times=5, **fault)
    code, out, err = env.run("report", env.report())
    assert code == 1 and out == ""
    assert err.startswith(code_prefix)
    assert sum(1 for x in env.api_log() if x.startswith("POST")) == 1
    assert not sr.registry_path().exists() or env.registry() == []


def test_rate_says_how_long_to_wait(env):
    env.accept()
    env.fault(match="POST /api/v1/shares", status=429, error="rate", retryAfter=7200)
    assert "in about 2 hours" in env.run("report", env.report())[2]


def test_removed_share_cannot_be_updated(env):
    env.accept()
    path = env.report()
    share_id = lines(env.run("report", path)[1], "SHARE_ID:")[0]
    with env.fake.state.lock:
        env.fake.state.op("takedown", {"id": share_id, "reason": "copyright"})
    code, _, err = env.run("report", path)
    assert code == 1 and err.startswith("ERROR:SHARE_REMOVED: copyright")


def test_put_with_an_unknown_share_is_auth(env):
    env.accept()
    path = env.report()
    share_id = lines(env.run("report", path)[1], "SHARE_ID:")[0]
    del env.fake.state.shares[share_id]
    code, _, err = env.run("report", path)
    assert code == 1 and err.startswith("ERROR:SHARE_AUTH:") and "--new-link" in err
    code, out, _ = env.run("report", path, "--new-link")
    assert code == 0 and lines(out, "SHARE_ID:") != [share_id]
    assert len(env.registry()) == 1


def test_5xx_is_retried(env):
    env.accept()
    env.fault(match="POST /api/v1/shares", status=500, error="internal", times=2)
    code, out, err = env.run("report", env.report())
    assert code == 0, err
    assert [x for x in env.api_log() if x.startswith("POST")] == [
        "POST /api/v1/shares 500", "POST /api/v1/shares 500", "POST /api/v1/shares 201"]


def test_5xx_gives_up_after_three_retries(env):
    env.accept()
    env.fault(match="POST /api/v1/shares", status=502, error="internal", times=10)
    code, _, err = env.run("report", env.report())
    assert code == 1 and err.startswith("ERROR:SHARE_HTTP:")
    assert sum(1 for x in env.api_log() if x.startswith("POST")) == 1 + sr.RETRIES


def test_every_third_request_failing_still_works(env):
    env.accept()
    with env.fake.state.lock:
        env.fake.state.fail_every = 3
    path = env.report()
    for _ in range(3):
        assert env.run("report", path)[0] == 0
    assert env.run("list")[0] == 0
    assert len(env.fake.state.shares) == 1


def test_post_is_not_retried_when_the_answer_is_lost_after_sending(env, monkeypatch):
    env.accept()
    real = sr._once

    def lost(method, url, data, headers, timeout):
        resp = real(method, url, data, headers, timeout)   # the service commits the share
        if method == "POST":
            raise TimeoutError("timed out")
        return resp

    monkeypatch.setattr(sr, "_once", lost)
    code, _, err = env.run("report", env.report())
    assert code == 1 and err.startswith("ERROR:SHARE_NETWORK:")
    assert "cannot revoke" in err
    assert [x for x in env.api_log() if x.startswith("POST")] == ["POST /api/v1/shares 201"]
    assert not sr.registry_path().exists() or env.registry() == []


def test_post_is_retried_when_the_request_never_left(env, monkeypatch):
    env.accept()
    real = sr._once
    calls = []

    def refused_once(method, url, data, headers, timeout):
        calls.append(method)
        if len(calls) == 1:
            raise urllib.error.URLError(ConnectionRefusedError(61, "refused"))
        return real(method, url, data, headers, timeout)

    monkeypatch.setattr(sr, "_once", refused_once)
    code, out, err = env.run("report", env.report())
    assert code == 0, err
    assert calls[:2] == ["POST", "POST"] and len(env.fake.state.shares) == 1


def test_paused_post_is_not_retried(env):
    env.accept()
    env.fault(match="POST /api/v1/shares", status=503, error="paused", times=10)
    code, _, err = env.run("report", env.report())
    assert code == 1 and err.startswith("ERROR:SHARE_PAUSED:")
    assert sum(1 for x in env.api_log() if x.startswith("POST")) == 1


def test_network_error(env, monkeypatch):
    env.accept()
    monkeypatch.setenv("VIDEO_LENS_SHARE_URL", "http://127.0.0.1:9")
    code, _, err = env.run("report", env.report())
    assert code == 1 and err.startswith("ERROR:SHARE_NETWORK:")


# ── standalone ───────────────────────────────────────────────────────────────

def test_runs_as_a_script_with_the_stdlib_only(env, tmp_path):
    """Run with -I (no user site, no cwd on sys.path) as the skill does."""
    environ = {**os.environ}
    proc = subprocess.run([sys.executable, "-I", str(SCRIPTS / "share_report.py"), "offer", "on"],
                          capture_output=True, text=True, env=environ, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "OFFER: on"
    imports = {line.split()[1].split(".")[0] for line in (SCRIPTS / "share_report.py").read_text().splitlines()
               if line.startswith(("import ", "from "))}
    assert imports <= set(sys.stdlib_module_names)
