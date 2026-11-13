"""033 §12 layer 2: tests/share_contract.json against the Python fake.

The Worker (video-lens-core service/) runs the same file with its own runner; keep the
interpretation here plain so the two runners stay easy to compare.
"""
import copy
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_share_service import FakeShareService, payload_sha, validate_payload  # noqa: E402

CONTRACT = json.loads((Path(__file__).resolve().parent / "share_contract.json").read_text(encoding="utf-8"))
INSTALL = "i" * 22
INSTALL2 = "j" * 22


@pytest.fixture
def fake():
    with FakeShareService() as service:
        yield service


def expand_patch_value(value):
    if isinstance(value, str) and value.startswith("@"):
        if value == "@21kp":
            return [{"point": "P"}] * 21
        if value == "@101ol":
            return [{"t": i, "title": "T"} for i in range(101)]
        return "x" * int(value[1:])
    return value


def patched(base, patch):
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if value == "#delete":
            out.pop(key, None)
        else:
            out[key] = expand_patch_value(value)
    return out


def request(base_url, method, path, body=None, raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(base_url + path, data=data, method=method, headers=headers or {})
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.headers), json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.loads(e.read() or b"null")


class Runner:
    def __init__(self, fake):
        self.fake = fake
        self.vars = {"terms": CONTRACT["terms"], "install": INSTALL, "install2": INSTALL2}

    def sub(self, value):
        """Replace placeholders; a whole-string placeholder may become an object."""
        if isinstance(value, dict):
            return {k: self.sub(v) for k, v in value.items()}
        if not isinstance(value, str):
            return value
        if value == "{payload}":
            return copy.deepcopy(CONTRACT["payload"])
        if value == "{minimalPayload}":
            return copy.deepcopy(CONTRACT["minimalPayload"])
        m = re.fullmatch(r"\{payload:(\{.*\})\}", value)
        if m:
            return patched(CONTRACT["payload"], json.loads(m.group(1)))
        return re.sub(r"\{(\w+)\}", lambda mm: str(self.vars.get(mm.group(1), mm.group(0))), value)

    def op(self, name, args):
        self.fake.state.op(name, self.sub(args or {}))

    def match(self, expected, actual, where):
        if isinstance(expected, dict):
            assert isinstance(actual, dict), where
            for key, value in expected.items():
                assert key in actual, f"{where}: missing {key!r} in {actual}"
                self.match(value, actual[key], f"{where}.{key}")
            return
        if isinstance(expected, str):
            if expected == "string":
                assert isinstance(actual, str), where
            elif expected == "int":
                assert isinstance(actual, int) or (isinstance(actual, str) and actual.isdigit()), where
            elif expected == "id":
                assert re.fullmatch(r"[A-Za-z0-9_-]{22}", actual), where
            elif expected == "key":
                assert re.fullmatch(r"[A-Za-z0-9_-]{43}", actual), where
            elif expected == "sha":
                assert re.fullmatch(r"[0-9a-f]{64}", actual), where
            elif expected.startswith("sha:"):
                assert actual == payload_sha(CONTRACT[expected[4:]]), where
            elif expected == "shareUrl":
                assert re.fullmatch(re.escape(self.fake.url) + r"/s/[A-Za-z0-9_-]{22}/", actual), where
            elif expected.startswith("!"):
                assert actual != self.sub(expected[1:]), where
            else:
                assert actual == self.sub(expected), f"{where}: {actual!r} != {self.sub(expected)!r}"
            return
        assert actual == expected, f"{where}: {actual!r} != {expected!r}"

    def step(self, i, step):
        if "op" in step:
            return self.op(step["op"], step.get("args"))
        req = step["request"]
        headers = {"X-VL-Install": INSTALL}
        if req.get("auth"):
            headers["Authorization"] = "Bearer " + self.sub(req["auth"])
        body = self.sub(req.get("body"))
        headers.update(self.sub(req.get("headers") or {}))
        raw = req.get("rawBody")
        if raw is not None:
            raw = ("x" * int(raw[1:]) if raw.startswith("@") else raw).encode()
        status, resp_headers, resp = request(self.fake.url, req["method"], self.sub(req["path"]),
                                             body=body, raw=raw, headers=headers)
        where = f"step {i} {req['method']} {req['path']}"
        expect = step["expect"]
        assert status == expect["status"], f"{where}: status {status} != {expect['status']} ({resp})"
        if "json" in expect:
            self.match(expect["json"], resp, where)
        for name, value in (expect.get("headers") or {}).items():
            self.match(value, resp_headers.get(name), f"{where} header {name}")
        for name, value in CONTRACT["responseHeaders"].items():
            assert resp_headers.get(name) == value, f"{where}: header {name}"
        for var, field in (step.get("save") or {}).items():
            self.vars[var] = resp[field]


@pytest.mark.parametrize("flow", CONTRACT["flows"], ids=[f["name"] for f in CONTRACT["flows"]])
def test_flow(fake, flow):
    runner = Runner(fake)
    for i, step in enumerate(flow["steps"]):
        runner.step(i, step)


def _create(fake, payload):
    body = {"terms": CONTRACT["terms"], "payload": payload}
    return request(fake.url, "POST", "/api/v1/shares", body=body, headers={"X-VL-Install": INSTALL})


@pytest.mark.parametrize("case", CONTRACT["validPatches"], ids=[c["name"] for c in CONTRACT["validPatches"]])
def test_valid_payload(fake, case):
    status, _, resp = _create(fake, patched(CONTRACT["payload"], case["patch"]))
    assert status == 201, resp


@pytest.mark.parametrize("case", CONTRACT["invalidPatches"], ids=[c["name"] for c in CONTRACT["invalidPatches"]])
def test_invalid_payload(fake, case):
    status, _, resp = _create(fake, patched(CONTRACT["payload"], case["patch"]))
    assert (status, resp) == (400, {"error": "schema", "field": case["field"]})


def test_minimal_payload_normalises_to_the_listed_object():
    assert validate_payload(CONTRACT["minimalPayload"]) == CONTRACT["minimalNormalised"]
    assert list(validate_payload(CONTRACT["payload"])) == list(CONTRACT["minimalNormalised"])


def test_nfc_is_applied_before_hashing(fake):
    status, _, resp = _create(fake, patched(CONTRACT["payload"], {"title": "Café"}))
    expected = patched(CONTRACT["payload"], {"title": "Café"})
    assert status == 201 and resp["sha"] == payload_sha(validate_payload(expected))


def test_sha_is_json_stringify_of_the_validated_object():
    # JSON.stringify: no spaces, non-ASCII as is. Pinned here so the Worker can compare.
    obj = {"a": "é", "b": [1, None], "c": "x\ny"}
    assert payload_sha(obj) == hashlib.sha256('{"a":"é","b":[1,null],"c":"x\\ny"}'.encode()).hexdigest()


def test_fault_injection_and_log(fake):
    request(fake.url, "POST", "/__fake/fault", body={"status": 429, "error": "rate", "retryAfter": 60,
                                                     "match": "POST /api/v1/shares"})
    status, headers, resp = _create(fake, CONTRACT["payload"])
    assert (status, resp, headers.get("Retry-After")) == (429, {"error": "rate"}, "60")
    assert _create(fake, CONTRACT["payload"])[0] == 201
    request(fake.url, "POST", "/__fake/fail_every", body={"n": 2})
    statuses = [request(fake.url, "GET", "/api/v1/health")[0] for _ in range(4)]
    assert statuses.count(500) == 2
    _, _, log = request(fake.url, "GET", "/__fake/log")
    assert [e["status"] for e in log[:2]] == [429, 201]
