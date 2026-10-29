"""Fast tests for 025-R1: KEY_POINTS and OUTLINE as JSON arrays. The renderer builds the
same HTML a model writes by hand today, so everything downstream (template, Markdown
export, build_index, gallery) sees no difference."""
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "video-lens" / "scripts"))
from render_report import RenderValidationError, render_from_payload, sanitise_payload  # noqa: E402

VIDEO_ID = "bjdBVZa66oU"


def payload(**overrides):
    base = {
        "VIDEO_ID": VIDEO_ID, "VIDEO_TITLE": "What are skills?",
        "VIDEO_URL": f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "SUMMARY": "Summary.", "TAKEAWAY": "Takeaway.", "DESCRIPTION_SECTION": "",
        "TAGS": ["ai"], "GENERATION_DATE": "2026-05-17", "GENERATION_DURATION_SECONDS": 42,
        "KEY_POINTS": "<li><strong>P</strong> — why</li>",
        "OUTLINE": (f'<li><a class="ts" data-t="0" href="https://www.youtube.com/watch?v={VIDEO_ID}&t=0" '
                    'target="_blank" rel="noopener noreferrer">▶ 0:00</a> — '
                    '<span class="outline-title">Intro</span></li>'),
    }
    base.update(overrides)
    return base


def clean(**overrides):
    out = sanitise_payload(payload(**overrides), "/r/x.html")
    out["VIDEO_LENS_META"] = json.loads(out["VIDEO_LENS_META"].replace("<\\/", "</"))
    out["VIDEO_LENS_META"].pop("generatedAt")
    return out


def rejected(**overrides):
    with pytest.raises(RenderValidationError) as exc:
        sanitise_payload(payload(**overrides), "/r/x.html")
    return exc.value


KP_ARRAY = [
    {"point": "Progressive disclosure", "why": "Only names load up front.",
     "detail": "Bodies load *on demand*, so **context stays small**; see `SKILL.md`."},
    {"point": "Scripts", "why": "Deterministic steps."},
    {"point": "A & B <tags>", "why": 'Quotes "stay" & angle <brackets> are text.', "detail": "2 * 3 * 4 is not italic."},
]
KP_STRING = (
    "<li><strong>Progressive disclosure</strong> — Only names load up front."
    "<p>Bodies load <em>on demand</em>, so <strong>context stays small</strong>; see <code>SKILL.md</code>.</p></li>"
    "<li><strong>Scripts</strong> — Deterministic steps.</li>"
    "<li><strong>A &amp; B &lt;tags&gt;</strong> — Quotes \"stay\" &amp; angle &lt;brackets&gt; are text."
    "<p>2 * 3 * 4 is not italic.</p></li>"
)


def _outline_li(t, clock, title, detail=None):
    li = (f'<li><a class="ts" data-t="{t}" href="https://www.youtube.com/watch?v={VIDEO_ID}&t={t}" '
          f'target="_blank" rel="noopener noreferrer">▶ {clock}</a> — <span class="outline-title">{title}</span>')
    return li + (f'<span class="outline-detail">{detail}</span>' if detail else "") + "</li>"


OUTLINE_ARRAY = [
    {"t": 0, "title": "Intro", "detail": "Opening."},
    {"t": 754, "title": "Why it **fails**", "detail": "Context & *cause*."},
    {"t": 3725, "title": "Wrap-up"},
]
OUTLINE_STRING = (_outline_li(0, "0:00", "Intro", "Opening.")
                  + _outline_li(754, "12:34", "Why it fails", "Context &amp; cause.")
                  + _outline_li(3725, "1:02:05", "Wrap-up"))


def test_arrays_render_exactly_what_the_equivalent_strings_render():
    assert clean(KEY_POINTS=KP_ARRAY, OUTLINE=OUTLINE_ARRAY) == clean(KEY_POINTS=KP_STRING, OUTLINE=OUTLINE_STRING)


def test_array_key_points_feed_the_gallery_keywords():
    meta = clean(KEY_POINTS=KP_ARRAY)["VIDEO_LENS_META"]
    assert meta["keywords"] == ["Progressive disclosure", "Scripts", "A & B <tags>"]


def test_bold_in_a_headline_does_not_split_its_keyword():
    out = clean(KEY_POINTS=[{"point": "The **real** cost", "why": "x"}])
    assert out["KEY_POINTS"] == "<li><strong>The real cost</strong> — x</li>"
    assert out["VIDEO_LENS_META"]["keywords"] == ["The real cost"]


def test_outline_times_accept_clock_strings_and_numbers():
    entries = [{"t": "12:34", "title": "a"}, {"t": "1:02:05", "title": "b"}, {"t": "75", "title": "c"},
               {"t": 90.6, "title": "d"}]
    out = clean(OUTLINE=entries)["OUTLINE"]
    for t in (754, 3725, 75, 90):
        assert f'data-t="{t}"' in out and f"&amp;t={t}\"" in out


def test_a_list_of_html_strings_is_joined_instead_of_rejected():
    """Under the string contract, an array was the most common rejection (RENDER_INVALID_TYPE)."""
    items = ["<li><strong>P</strong> — a</li>", "<li><strong>Q</strong> — b</li>"]
    assert clean(KEY_POINTS=items)["KEY_POINTS"] == clean(KEY_POINTS="".join(items))["KEY_POINTS"]
    # The joined string still goes through the sanitiser.
    assert rejected(KEY_POINTS=["<li><script>x</script></li>"]).code == "RENDER_DISALLOWED_HTML"


def test_array_text_is_escaped_never_parsed():
    out = clean(KEY_POINTS=[{"point": "<script>alert(1)</script>", "why": "git push origin <branch-name>"}])
    assert "<script>" not in out["KEY_POINTS"]
    assert "&lt;branch-name&gt;" in out["KEY_POINTS"]
    title = clean(OUTLINE=[{"t": 1, "title": '<img src=x onerror="y">'}])["OUTLINE"]
    assert "<img" not in title and "&lt;img" in title


@pytest.mark.parametrize("key,value,needle", [
    ("KEY_POINTS", [], "empty_keys=['KEY_POINTS']"),
    ("KEY_POINTS", [{"why": "no headline"}], "KEY_POINTS[0] needs a non-empty \"point\""),
    ("KEY_POINTS", [{"point": "P", "paragraph": "misnamed"}], "KEY_POINTS[0] has unknown key 'paragraph'"),
    ("KEY_POINTS", ["<li>a</li>", {"point": "P"}], "KEY_POINTS mixes strings and objects"),
    ("KEY_POINTS", [{"point": ["a"]}], "KEY_POINTS[0].point must be a string"),
    ("OUTLINE", [{"title": "No time"}], "OUTLINE[0].t"),
    ("OUTLINE", [{"t": "soon", "title": "x"}], "OUTLINE[0].t must be"),
    ("OUTLINE", [{"t": True, "title": "x"}], "OUTLINE[0].t must be"),
    ("OUTLINE", [{"t": -5, "title": "x"}], "OUTLINE[0].t must be"),
    ("OUTLINE", [{"t": 10, "title": " "}], "OUTLINE[0] needs a non-empty \"title\""),
    ("OUTLINE", ["text"], "OUTLINE[0]"),
])
def test_bad_items_name_the_item_and_the_fix(key, value, needle):
    err = rejected(**{key: value})
    assert err.code in ("RENDER_INVALID_ITEM", "RENDER_PAYLOAD_INVALID")
    assert needle in err.detail
    if err.code == "RENDER_INVALID_ITEM":
        assert ("point, why, detail" if key == "KEY_POINTS" else "t, title, detail") in err.detail


def test_other_fields_still_must_be_strings():
    err = rejected(SUMMARY=["a", "b"])
    assert err.code == "RENDER_INVALID_TYPE" and "key=SUMMARY" in err.detail


def test_an_array_payload_renders_end_to_end(tmp_path):
    out = tmp_path / "r.html"
    render_from_payload(payload(KEY_POINTS=KP_ARRAY, OUTLINE=OUTLINE_ARRAY), str(out))
    html = out.read_text(encoding="utf-8")
    assert "<strong>context stays small</strong>" in html and 'data-t="3725"' in html


def test_skill_md_documents_the_fields_the_renderer_accepts():
    import render_report
    skill = (REPO_ROOT / "skills" / "video-lens" / "SKILL.md").read_text(encoding="utf-8")
    for key, fields in render_report.ITEM_FIELDS.items():
        row = next(line for line in skill.splitlines() if line.startswith(f"| `{key}` |"))
        assert all(f'"{field}"' in row for field in fields), key
    # The hand-written HTML contract is gone from the prompt.
    assert "HTML string" not in skill and "<li>" not in skill and "data-t" not in skill


def test_inline_tags_from_the_old_contract_become_emphasis_not_literal_text():
    out = clean(KEY_POINTS=[{"point": "<strong>P</strong>", "why": "an <em>odd</em> <b>habit</b>",
                             "detail": "<i>a</i> <code>x</code> <span>kept as text</span>"}])["KEY_POINTS"]
    assert out == ("<li><strong>P</strong> — an <em>odd</em> <strong>habit</strong>"
                   "<p><em>a</em> <code>x</code> &lt;span&gt;kept as text&lt;/span&gt;</p></li>")
    title = clean(OUTLINE=[{"t": 1, "title": "<em>Intro</em>"}])["OUTLINE"]
    assert '<span class="outline-title">Intro</span>' in title
