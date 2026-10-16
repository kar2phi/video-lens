"""Fast tests for evals/checks.py: the eval's gates must catch what they claim to catch."""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "evals"))
sys.path.insert(0, str(REPO_ROOT / "skills" / "video-lens" / "scripts"))
import checks  # noqa: E402
from render_report import render_from_payload  # noqa: E402

VIDEO = "bjdBVZa66oU"
FIXTURE = {"name": "smoke", "video": VIDEO, "expect": {"lang": "en", "chapters": 2}}
CHAPTERS = [{"start_time": 0.0, "title": "Intro"}, {"start_time": 65.0, "title": "Why skills"}]
EN = ("Skills are folders of instructions that the agent loads only when they are relevant, "
      "which keeps the context small and the behaviour consistent. The speaker argues that this "
      "is the way to share procedures with a team.")


def _entry(t, display=None, video=VIDEO, title="Intro"):
    display = display or f"{t // 60}:{t % 60:02d}"
    return (f'<li><a class="ts" data-t="{t}" href="https://www.youtube.com/watch?v={video}&t={t}" '
            f'target="_blank" rel="noopener noreferrer">▶ {display}</a> — '
            f'<span class="outline-title">{title}</span><span class="outline-detail">Detail.</span></li>')


def render(tmp_path, **overrides):
    payload = {
        "VIDEO_ID": VIDEO, "VIDEO_TITLE": "What are skills?",
        "VIDEO_URL": f"https://www.youtube.com/watch?v={VIDEO}",
        "SUMMARY": EN, "TAKEAWAY": "Package a repeated procedure once and let the agent load it on demand.",
        "KEY_POINTS": ("<li><strong>Progressive disclosure</strong> — only names load.<p>Bodies load later.</p></li>"
                       "<li><strong>Scripts</strong> — deterministic steps.</li>"
                       "<li><strong>Sharing</strong> — teams reuse them.<p>One folder per skill.</p></li>"),
        "OUTLINE": _entry(0) + _entry(65, title="Why skills"),
        "DESCRIPTION_SECTION": "", "TAGS": ["ai", "agents", "tools"],
        "META_LINE": "Anthropic · 2 min",
    }
    payload.update(overrides)
    out = tmp_path / "report.html"
    render_from_payload(payload, str(out))
    return checks.parse_report(out.read_text(encoding="utf-8"))


def test_parse_report_reads_back_what_the_renderer_wrote(tmp_path):
    rep = render(tmp_path)
    assert rep["title"] == "What are skills?"
    assert rep["summary"] == EN
    assert [k["headline"] for k in rep["key_points"]] == ["Progressive disclosure", "Scripts", "Sharing"]
    assert [o["t"] for o in rep["outline"]] == [0, 65]
    assert rep["outline"][1] == {"t": 65, "href_video": VIDEO, "href_t": 65, "display_t": 65,
                                 "title": "Why skills", "detail": "Detail."}
    assert rep["meta"]["videoId"] == VIDEO and rep["unreplaced"] == []

    m = checks.report_metrics(rep, duration_s=174, chapters=CHAPTERS, existing_tags=["ai", "llm"])
    assert m["kp_paragraph_share"] == 0.67
    assert m["ts_mismatches"] == 0 and m["outline_monotonic"]
    assert m["chapter_t_match"] == m["chapter_title_match"] == 1.0
    assert m["tags_reused_share"] == 0.33 and m["band"] == "short"
    gates = checks.gates(FIXTURE, None, rep, 1, chapters=CHAPTERS)
    assert all(gates.values()), gates


def test_gates_catch_broken_outlines(tmp_path):
    rep = render(tmp_path, OUTLINE=_entry(0) + _entry(65, display="1:08"))
    m = checks.report_metrics(rep, duration_s=174, chapters=CHAPTERS)
    assert m["ts_mismatches"] == 1                       # displayed 1:08 for data-t 65
    # The renderer rejects foreign-video links today; the gate backstops a sanitiser regression.
    rep["outline"][1]["href_video"] = "dQw4w9WgXcQ"
    assert checks.gates(FIXTURE, None, rep, 1, chapters=CHAPTERS)["outline_links_own_video"] is False


def test_language_gate_and_detection(tmp_path):
    de = ("Die Autoindustrie steckt in einer tiefen Krise, und BMW investiert ausgerechnet jetzt "
          "Milliarden in eine neue Plattform. Der Sprecher fragt, ob das mutig ist oder nicht, "
          "und wie sich die Strategie auf den Markt auswirken wird.")
    assert checks.detect_lang(EN) == "en"
    assert checks.detect_lang(de) == "de"
    assert checks.detect_lang("Too short to tell.") is None
    rep = render(tmp_path, SUMMARY=de)
    assert checks.gates({**FIXTURE, "expect": {"lang": "de-DE"}}, None, rep, 1)["language"] is True
    assert checks.gates(FIXTURE, None, render(tmp_path), 1)["language"] is True


def _claude_trace(*calls, final="Report ready.\nhttp://localhost:8765/reports/x.html", denials=()):
    lines = [{"type": "system", "subtype": "init", "model": "claude-test"}]
    for i, (name, inp, out) in enumerate(calls):
        lines.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": f"t{i}", "name": name, "input": inp}]}})
        lines.append({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": [{"type": "text", "text": out}]}]}})
    lines.append({"type": "result", "result": final, "permission_denials": list(denials), "total_cost_usd": 0.1})
    return checks.load_trace([json.dumps(l) for l in lines], "claude")


def test_claude_trace_gates(tmp_path):
    rep = render(tmp_path)
    good = _claude_trace(
        ("Bash", {"command": "python3 /s/render_report.py --payload-file p.json"}, "ERROR:RENDER_DISALLOWED_HTML x"),
        ("Bash", {"command": "python3 /s/render_report.py --payload-file p.json"}, "OUTPUT_PATH: /r/x.html"),
        ("Bash", {"command": "bash /s/serve_report.sh /r/x.html ~/Downloads/video-lens"}, "HTML_REPORT: /r/x.html"),
    )
    assert good["model"] == "claude-test" and good["cost_usd"] == 0.1
    gates = checks.gates(FIXTURE, good, rep, 1, chapters=CHAPTERS)
    assert all(gates.values()), gates
    assert checks.trace_metrics(good)["render_attempts"] == 2

    bad = _claude_trace(
        ("Read", {"file_path": "/s/../template.html"}, "<html>"),
        ("Write", {"file_path": "/r/report.html"}, "ok"),
        denials=[{"tool_name": "Write"}],
    )
    gates = checks.gates(FIXTURE, bad, rep, 1)
    for name in ("no_template_read", "no_hand_written_html", "no_permission_denials",
                 "no_false_success", "html_report_seen", "render_ok_within_retry"):
        assert gates[name] is False, name


def test_pi_trace_and_the_ask_first_fallback_gate():
    fx = {"name": "no-captions", "video": "TOmb5UTIUU8", "expect": {"error": "CAPTIONS_DISABLED"}}

    def pi_trace(cmds, final):
        lines = []
        for i, (cmd, out) in enumerate(cmds):
            lines.append({"type": "message_update", "assistantMessageEvent": {"type": "toolcall_delta"}})
            lines.append({"type": "message_end", "message": {"role": "assistant", "model": "qwen3.6:27b",
                          "content": [{"type": "toolCall", "id": f"c{i}", "name": "bash", "arguments": {"command": cmd}}]}})
            lines.append({"type": "message_end", "message": {"role": "toolResult", "toolCallId": f"c{i}",
                          "content": [{"type": "text", "text": out}], "isError": False}})
        lines.append({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": final}]}})
        return checks.load_trace([json.dumps(l) for l in lines], "pi")

    fetch = ("python3 /s/fetch_transcript.py -- TOmb5UTIUU8", "ERROR:CAPTIONS_DISABLED: no captions")
    asked = pi_trace([fetch], "Captions are disabled. I can transcribe it locally with Whisper (~3 min). Proceed?")
    assert asked["model"] == "qwen3.6:27b" and len(asked["calls"]) == 1
    assert all(checks.gates(fx, asked, None, 0).values())

    ran = pi_trace([fetch, ("python3 /s/transcribe_local.py -- TOmb5UTIUU8", "...")], "Done.")
    gates = checks.gates(fx, ran, None, 0)
    assert gates["fallback_not_run"] is False and gates["fallback_offered"] is False


def test_library_summary_counts_by_model_family(tmp_path):
    render(tmp_path)
    (tmp_path / "report.html").rename(tmp_path / "a.html")
    summary = checks.summarise_library([tmp_path / "a.html"])
    assert summary["unknown"]["reports"] == 1
    assert summary["unknown"]["kp_zero_paragraphs"] == 0
