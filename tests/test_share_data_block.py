"""033 §5.2 (P1): new reports carry the share payload v1 in a `video-lens-data` block.

Golden test: apart from that block, a rendered report is byte-identical to the report the
renderer wrote before the block existed (tests/golden/share_report.html, generatedAt masked).
If a template change is intended, regenerate the golden file with that change and say so.
"""
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "video-lens" / "scripts"))
import render_report as rr  # noqa: E402

GOLDEN = REPO_ROOT / "tests" / "golden"
DATA_RE = re.compile(r'\n  <script type="application/json" id="video-lens-data">(.*?)</script>', re.S)
SHARE_KEYS = ["v", "videoId", "title", "channel", "channelId", "duration", "durationS", "published",
              "lang", "tags", "summary", "takeaway", "keyPoints", "outline", "model", "notes", "created"]


@pytest.fixture(autouse=True)
def no_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(rr, "METADATA_DIR", tmp_path / "metadata")
    return tmp_path / "metadata"


def golden_payload(**overrides):
    payload = json.loads((GOLDEN / "share_payload.json").read_text(encoding="utf-8"))
    payload.update(overrides)
    return payload


def render(tmp_path, payload) -> str:
    out = tmp_path / "r.html"
    rr.render_from_payload(payload, str(out))
    return re.sub(r'"generatedAt": "[^"]*"', '"generatedAt": "X"', out.read_text(encoding="utf-8"))


def block(html: str) -> dict | None:
    blocks = DATA_RE.findall(html)
    assert len(blocks) <= 1
    return json.loads(blocks[0]) if blocks else None


def test_golden_report_is_unchanged_apart_from_the_block(tmp_path):
    html = render(tmp_path, golden_payload())
    assert block(html) is not None
    assert DATA_RE.sub("", html) == (GOLDEN / "share_report.html").read_text(encoding="utf-8")


def test_block_holds_payload_v1(tmp_path):
    data = block(render(tmp_path, golden_payload()))
    assert list(data) == SHARE_KEYS
    assert data["v"] == 1 and data["videoId"] == "bjdBVZa66oU"
    assert data["title"] == 'What are skills? & <why> "quotes"'
    assert data["channelId"] == "UCaaaaaaaaaaaaaaaaaaaaaa"
    assert data["tags"] == ["ai", "agent skills", "claude code"]
    assert data["summary"].startswith("Skills load **on demand**.\n\n")
    assert data["keyPoints"][0] == {"point": "Progressive disclosure", "why": "Only names load up front.",
                                    "detail": "Bodies load *on demand*, so **context stays small**; see `SKILL.md`."}
    assert data["keyPoints"][1]["detail"] == ""
    assert [o["t"] for o in data["outline"]] == [0, 65, 600]
    assert data["outline"][1] == {"t": 65, "title": "Disclosure **model**", "detail": ""}
    assert data["model"] == "claude-opus-5-5"
    assert data["notes"] == ["local-transcript"]
    assert data["created"] == "2026-11-11"
    assert data["durationS"] is None and data["lang"] == ""


def test_script_end_tag_in_text_is_escaped(tmp_path):
    html = render(tmp_path, golden_payload())
    raw = DATA_RE.search(html).group(1)
    assert "</" not in raw
    assert "</script> text" in json.loads(raw)["summary"]


def test_sidecar_gives_duration_and_language(tmp_path, no_sidecar):
    no_sidecar.mkdir()
    (no_sidecar / "bjdBVZa66oU.json").write_text(json.dumps(
        {"videoId": "bjdBVZa66oU", "channelId": "", "durationS": 754, "lang": "en"}))
    data = block(render(tmp_path, golden_payload()))
    assert data["durationS"] == 754 and data["lang"] == "en"


def test_language_fallback_drops_lang(tmp_path, no_sidecar):
    no_sidecar.mkdir()
    (no_sidecar / "bjdBVZa66oU.json").write_text(json.dumps({"durationS": 754, "lang": "en"}))
    data = block(render(tmp_path, golden_payload(
        META_LINE="Anthropic · 12 min · ⚠ Requested language not available")))
    assert data["notes"] == ["lang-fallback"] and data["lang"] == ""


@pytest.mark.parametrize("sidecar", [{"durationS": True}, {"durationS": -1}, {"durationS": 90000},
                                     {"durationS": "754"}, {"lang": "english"}, "not a dict"])
def test_bad_sidecar_values_are_left_out(tmp_path, no_sidecar, sidecar):
    no_sidecar.mkdir()
    (no_sidecar / "bjdBVZa66oU.json").write_text(json.dumps(sidecar))
    data = block(render(tmp_path, golden_payload()))
    assert data["durationS"] is None and data["lang"] == ""


def test_tags_outside_the_share_pattern_are_dropped(tmp_path):
    tags = ["künstliche intelligenz", "人工知能", "x" * 31, "+ai", "a", "b", "c", "d"]
    data = block(render(tmp_path, golden_payload(TAGS=tags)))
    assert data["tags"] == ["künstliche intelligenz", "人工知能", "a", "b", "c"]


def test_odd_model_name_is_left_out(tmp_path):
    data = block(render(tmp_path, golden_payload(AGENT_MODEL="model <x>")))
    assert data["model"] == ""


@pytest.mark.parametrize("key", ["KEY_POINTS", "OUTLINE"])
def test_html_string_input_leaves_the_block_out(tmp_path, key):
    html_value = {
        "KEY_POINTS": "<li><strong>P</strong> — why</li>",
        "OUTLINE": ('<li><a class="ts" data-t="0" href="https://www.youtube.com/watch?v=bjdBVZa66oU&t=0" '
                    'target="_blank" rel="noopener noreferrer">▶ 0:00</a> — '
                    '<span class="outline-title">Intro</span></li>'),
    }[key]
    html = render(tmp_path, golden_payload(**{key: html_value}))
    assert block(html) is None
    assert 'id="video-lens-meta"' in html


def test_array_of_html_strings_leaves_the_block_out(tmp_path):
    html = render(tmp_path, golden_payload(KEY_POINTS=["<li><strong>P</strong> — why</li>"]))
    assert block(html) is None


def test_old_callers_without_the_key_still_render(tmp_path):
    clean = rr.sanitise_payload(golden_payload(), str(tmp_path / "r.html"))
    clean.pop("VIDEO_LENS_DATA")
    rr._render_clean(clean, str(tmp_path / "r.html"))
    assert block((tmp_path / "r.html").read_text(encoding="utf-8")) is None
