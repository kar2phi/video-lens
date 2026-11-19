"""fetch_metadata cuts a long video description at a line break, never mid-line. No network."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "video-lens" / "scripts"))

from fetch_metadata import DESC_LIMIT, _clip_description  # noqa: E402

CHAPTERS = "\n".join(f"{m // 60}:{m % 60:02d} Chapter number {m} of a long made-up talk" for m in range(200))


def test_short_description_is_unchanged():
    text = "Line one\nhttps://example.com/x\n\n0:00 Intro"
    assert _clip_description(text) == text


def test_description_at_the_limit_is_unchanged():
    text = "a" * DESC_LIMIT
    assert _clip_description(text) == text


def test_long_description_ends_on_a_whole_line():
    assert len(CHAPTERS) > DESC_LIMIT
    out = _clip_description(CHAPTERS)
    body, ellipsis = out.rsplit("\n", 1)
    assert ellipsis == "…"
    assert len(body) <= DESC_LIMIT
    assert CHAPTERS.startswith(body + "\n")          # cut lands exactly on a line break
    assert body.split("\n")[-1] in CHAPTERS.split("\n")


def test_line_break_right_after_the_limit_keeps_the_full_line():
    text = "x" * DESC_LIMIT + "\nnext line"
    assert _clip_description(text) == "x" * DESC_LIMIT + "\n…"


def test_trailing_blank_lines_before_the_cut_are_dropped():
    text = "x" * 2500 + "\n\n\n" + "y" * DESC_LIMIT
    assert _clip_description(text) == "x" * 2500 + "\n…"


def test_short_intro_then_one_long_paragraph_keeps_the_paragraph():
    text = "Intro line\n" + "word " * 1000
    out = _clip_description(text)
    assert out.startswith("Intro line\nword word")
    assert out.endswith(" …")
    assert DESC_LIMIT // 2 <= len(out) <= DESC_LIMIT + 2
    assert out[:-2].split(" ")[-1] == "word"


def test_early_line_break_and_no_late_space_cuts_at_the_limit():
    text = "Intro line\n" + "z" * DESC_LIMIT
    assert _clip_description(text) == text[:DESC_LIMIT] + " …"


def test_one_long_line_is_cut_at_a_space():
    text = "word " * 1000
    out = _clip_description(text)
    assert out.endswith(" …")
    assert len(out) <= DESC_LIMIT + 2
    assert out[:-2].split(" ")[-1] == "word"


def test_one_long_line_without_spaces_is_cut_at_the_limit():
    out = _clip_description("z" * (DESC_LIMIT + 50))
    assert out == "z" * DESC_LIMIT + " …"
