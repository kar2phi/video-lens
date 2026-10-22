"""Fast tests for fetch_transcript.py (024-T1): track selection and the error contract,
against fake transcript lists shaped like what youtube-transcript-api returned for the
fixture videos in evals/fixtures.json. No network."""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "skills" / "video-lens" / "scripts"))
import fetch_transcript  # noqa: E402

from youtube_transcript_api import (  # noqa: E402
    IpBlocked, NoTranscriptFound, RequestBlocked, TranscriptsDisabled, YouTubeRequestFailed,
)


class Track:
    def __init__(self, code, variant=None, generated=True, fetch_error=None):
        self.language_code = code
        self.is_generated = generated
        self._url = "https://www.youtube.com/api/timedtext?v=x&kind=asr&lang=" + code
        if variant:
            self._url += "&variant=" + variant
        self._fetch_error = fetch_error

    def fetch(self):
        if self._fetch_error:
            raise self._fetch_error
        return [{"text": f"hallo {i}", "start": i * 5.0} for i in range(3)]


DUB = "timing-optimized"
# Ds-Q8hTuxdU: a German video whose auto-dubbed English track is listed first.
AUTO_DUB = [Track("en-US", DUB), Track("de")]
# qOvc9IUKEIc: English original plus auto-dubs, the German one only as de-DE.
REGION = [Track("en", "gemini"), Track("fr-FR", DUB), Track("de-DE", DUB), Track("pt-BR", DUB)]
# The lang-request fixture: manual en and de, then an auto-generated de.
MANUAL = [Track("en", generated=False), Track("de", generated=False), Track("de")]


def pick(tracks, lang=""):
    t, warn = fetch_transcript.pick_transcript(tracks, lang)
    return t.language_code, t.is_generated, warn


def test_default_pick_skips_an_auto_dub_listed_first():
    assert pick(AUTO_DUB) == ("de", True, None)


def test_default_pick_is_the_first_track_when_nothing_is_dubbed():
    assert pick(MANUAL)[:2] == ("en", False)


def test_a_requested_language_matches_its_region_subtag_without_a_warning():
    assert pick(REGION, "de") == ("de-DE", True, None)


def test_a_regional_request_matches_the_bare_code():
    assert pick(AUTO_DUB, "de-AT") == ("de", True, None)


def test_an_exact_match_beats_a_subtag_match():
    assert pick([Track("pt-BR"), Track("pt")], "pt")[0] == "pt"


def test_the_first_exact_match_wins_so_manual_tracks_come_first():
    assert pick(MANUAL, "de")[:2] == ("de", False)


def test_a_dub_is_still_used_when_it_is_the_only_match():
    assert pick(AUTO_DUB, "en")[0] == "en-US"


def test_an_unavailable_language_warns_and_falls_back_to_the_original():
    code, _, warn = pick(AUTO_DUB, "ja")
    assert code == "de"
    assert warn == 'LANG_WARN: Requested language "ja" not available; using de'


def test_tracks_without_a_url_are_treated_as_originals():
    t = Track("en")
    del t._url
    assert pick([t]) == ("en", True, None)


@pytest.mark.parametrize("exc, code", [
    (IpBlocked("v"), "ERROR:IP_BLOCKED"),            # subclass of RequestBlocked: order matters
    (RequestBlocked("v"), "ERROR:REQUEST_BLOCKED"),
    (TranscriptsDisabled("v"), "ERROR:CAPTIONS_DISABLED"),
    (NoTranscriptFound("v", ["de"], None), "ERROR:NO_TRANSCRIPT"),
    (YouTubeRequestFailed("v", Exception("boom")), "ERROR:NETWORK_ERROR"),
    (ValueError("odd"), "ERROR:TRANSCRIPT_FETCH_FAILED"),
])
def test_error_codes(exc, code):
    assert fetch_transcript.error_code(exc) == code


def run_main(monkeypatch, capsys, tracks, *args):
    monkeypatch.setattr(fetch_transcript, "_fetch_html_metadata", lambda v: ("T", "C", "", "", ""))
    monkeypatch.setattr(fetch_transcript, "list_transcripts", lambda v: tracks)
    monkeypatch.setattr(sys, "argv", ["fetch_transcript.py", "vid", *args])
    try:
        fetch_transcript.main()
        status = 0
    except SystemExit as e:
        status = e.code
    out = capsys.readouterr()
    return status, out.out, out.err


def test_an_ip_block_during_the_download_is_reported_as_ip_blocked(monkeypatch, capsys):
    # The list call can succeed and the timedtext download still be blocked; the skill
    # offers the local fallback only on IP_BLOCKED, and reads it from stdout.
    status, out, _ = run_main(monkeypatch, capsys, [Track("en", fetch_error=IpBlocked("vid"))])
    assert status == 1
    assert out.startswith("ERROR:IP_BLOCKED")


def test_a_successful_fetch_prints_headers_then_timestamped_lines(monkeypatch, capsys):
    status, out, _ = run_main(monkeypatch, capsys, REGION, "de")
    assert status == 0
    lines = out.splitlines()
    assert lines[0] == "TITLE: T"
    assert "LANG: de-DE" in lines
    assert not any(l.startswith("LANG_WARN:") for l in lines)
    assert lines[-3:] == ["[0:00] hallo 0", "[0:05] hallo 1", "[0:10] hallo 2"]


def test_a_list_failure_keeps_its_mapped_code(monkeypatch, capsys):
    def blocked(v):
        raise TranscriptsDisabled(v)
    monkeypatch.setattr(fetch_transcript, "_fetch_html_metadata", lambda v: ("", "", "", "", ""))
    monkeypatch.setattr(fetch_transcript, "list_transcripts", blocked)
    monkeypatch.setattr(sys, "argv", ["fetch_transcript.py", "vid"])
    with pytest.raises(SystemExit):
        fetch_transcript.main()
    assert capsys.readouterr().out.startswith("ERROR:CAPTIONS_DISABLED")
