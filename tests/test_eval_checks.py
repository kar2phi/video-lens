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


FOCUS = r"akku|reichweite|batter"


def test_focus_gates_and_the_control_metric(tmp_path):
    """027-E1: a focus request must show up in the report without crowding out the rest."""
    fx = {**FIXTURE, "request": "in German, focus on the battery",
          "expect": {"lang": "en", "focus": FOCUS}}
    focused = render(tmp_path, SUMMARY=EN + " The battery gets the most attention.", KEY_POINTS=(
        "<li><strong>Battery</strong> — 600 Wh.<p>Range is about 80 km.</p></li>"
        "<li><strong>Weight</strong> — under 20 kg.</li>"
        "<li><strong>Price</strong> — expensive.</li>"))
    preflight = ("Bash", {"command": "python3 /s/preflight.py -- 'URL in German, focus on the battery'"},
                 "VIDEO_ID: x\nLANG_CODE: de\nEXTRA_REQUEST: in German, focus on the battery\n")
    gates = checks.gates(fx, _claude_trace(preflight), focused, 1)
    assert gates["extra_request_seen"] and gates["focus_reflected"] and gates["focus_rest_covered"]
    assert checks.report_metrics(focused, focus=FOCUS)["focus_kp_share"] == 0.33

    # The control fixture computes the metric without gating on it.
    plain = render(tmp_path)
    control = {**FIXTURE, "expect": {"lang": "en", "focus_control": FOCUS}}
    assert "focus_reflected" not in checks.gates(control, None, plain, 1)
    assert checks.report_metrics(plain, focus=FOCUS)["focus_kp_share"] == 0.0

    gates = checks.gates(fx, _claude_trace(), plain, 1)
    assert gates["extra_request_seen"] is False and gates["focus_reflected"] is False
    only_focus = render(tmp_path, KEY_POINTS="".join(
        f"<li><strong>Battery {i}</strong> — the Akku.</li>" for i in range(3)))
    assert checks.gates(fx, None, only_focus, 1)["focus_rest_covered"] is False


def _report_file(tmp_path, name, **overrides):
    render(tmp_path, **overrides)
    path = tmp_path / name
    (tmp_path / "report.html").rename(path)
    return path


def test_revision_gates(tmp_path):
    """027-E1: a revision replaces its report in place, keeps the date, changes the takeaway."""
    name = f"2026-05-17-101500-video-lens_{VIDEO}_what-are-skills.html"
    before = checks.parse_report(_report_file(tmp_path, name, GENERATION_DATE="2026-05-17").read_text())
    after_path = _report_file(tmp_path, name, GENERATION_DATE="2026-05-17", TAKEAWAY="Package it once.")
    after = checks.parse_report(after_path.read_text())
    replaced = _claude_trace(
        ("Write", {"file_path": "/tmp/payload-1/payload.json"}, "ok"),
        ("Bash", {"command": f"python3 /s/render_report.py --payload-file p.json --replace /r/{name}"},
         f"OUTPUT_PATH: /r/{name}"))
    gates = checks.revision_gates(before, name, after, [name], replaced)
    assert all(gates.values()), gates
    assert checks.revision_metrics(before, after) == {"revision_summary_kept": True}

    second_file = name.replace("101500", "101900")
    new_render = _claude_trace(
        ("Bash", {"command": "python3 /s/render_report.py --payload-file p.json --output-dir /r"},
         f"OUTPUT_PATH: /r/{second_file}"))
    gates = checks.revision_gates(before, name, after, [name, second_file], new_render)
    assert gates["revision_one_file"] is False and gates["revision_used_replace"] is False

    hand_edit = _claude_trace(("Bash", {"command": f"sed -i '' 's/old/new/' /r/{name}"}, ""))
    gates = checks.revision_gates(before, name, before, [name], hand_edit)
    assert gates["revision_no_html_edit"] is False and gates["revision_takeaway_changed"] is False
    redated = checks.parse_report(_report_file(tmp_path, name, GENERATION_DATE="2026-05-18").read_text())
    assert checks.revision_gates(before, name, redated, [name], replaced)["revision_date_kept"] is False
    assert checks.revision_gates(None, None, None, [], replaced) == {"revision_ran": False}


def test_merge_traces_keeps_order_and_sums_costs():
    first = _claude_trace(("Bash", {"command": "a"}, "x"), final="Report ready.")
    second = _claude_trace(("Bash", {"command": "b"}, "y"), final="Revised.", denials=[{"tool_name": "Edit"}])
    merged = checks.merge_traces(first, second)
    assert [c["target"] for c in merged["calls"]] == ["a", "b"]
    assert merged["final"] == "Revised." and merged["cost_usd"] == 0.2
    assert merged["permission_denials"] == [{"tool_name": "Edit"}] and merged["turns"] == 2


def test_follow_up_turns_resume_the_same_session(tmp_path):
    import run_eval
    skill = tmp_path / "skill"
    first = run_eval.agent_command("claude", skill, tmp_path, "URL", None, [], session="abc")
    again = run_eval.agent_command("claude", skill, tmp_path, "URL", None, [], session="abc",
                                   followup="Tighten the takeaway.")
    assert first[first.index("--session-id") + 1] == "abc" and first[-1] == "/video-lens URL"
    assert again[again.index("--resume") + 1] == "abc" and again[-1] == "Tighten the takeaway."
    assert "--session-id" not in again

    pi_dir = str(tmp_path / "sessions")
    first = run_eval.agent_command("pi", skill, tmp_path, "URL", "qwen", [], session=pi_dir)
    again = run_eval.agent_command("pi", skill, tmp_path, "URL", "qwen", [], session=pi_dir,
                                   followup="Tighten the takeaway.")
    assert "--no-session" not in first and first[first.index("--session-dir") + 1] == pi_dir
    assert "--continue" in again and "--continue" not in first
    assert again[-1] == "Tighten the takeaway."
    single = run_eval.agent_command("pi", skill, tmp_path, "URL", None, [])
    assert "--no-session" in single and "--session-dir" not in single


FAKE_CLAUDE = r'''#!/usr/bin/env python3
"""Stands in for `claude -p`: turn 1 writes a report, a --resume turn rewrites its takeaway."""
import json, os, pathlib, sys
argv = sys.argv[1:]
reports = pathlib.Path(os.environ["FAKE_LIBRARY"]) / "reports"
target = reports / os.environ["FAKE_NAME"]
html = pathlib.Path(os.environ["FAKE_REPORT"]).read_text(encoding="utf-8")
resume = "--resume" in argv
if resume:
    html = html.replace(os.environ["FAKE_TAKEAWAY"], "Package it once.")
target.write_text(html, encoding="utf-8")
render = "python3 /s/render_report.py --payload-file p.json " + (
    f"--replace {target}" if resume else f"--output-dir {reports}")
calls = [(render, f"OUTPUT_PATH: {target}"), (f"bash /s/serve_report.sh {target}", f"HTML_REPORT: {target}")]
print(json.dumps({"type": "system", "subtype": "init", "model": "fake", "argv": argv}))
for i, (cmd, out) in enumerate(calls):
    print(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": f"t{i}", "name": "Bash", "input": {"command": cmd}}]}}))
    print(json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": f"t{i}", "content": [{"type": "text", "text": out}]}]}}))
print(json.dumps({"type": "result", "result": "Report ready: http://localhost:8765/reports/x.html",
                  "permission_denials": [], "total_cost_usd": 0.01}))
'''


def test_a_revision_case_runs_two_turns_in_one_session(tmp_path, monkeypatch):
    import argparse
    import run_eval
    name = f"2026-05-17-101500-video-lens_{VIDEO}_what-are-skills.html"
    report = _report_file(tmp_path, "rendered.html", GENERATION_DATE="2026-05-17")
    bin_dir, library = tmp_path / "bin", tmp_path / "library"
    bin_dir.mkdir()
    (library / "reports").mkdir(parents=True)
    (bin_dir / "claude").write_text(FAKE_CLAUDE, encoding="utf-8")
    (bin_dir / "claude").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{__import__('os').environ['PATH']}")
    monkeypatch.setenv("FAKE_LIBRARY", str(library))
    monkeypatch.setenv("FAKE_NAME", name)
    monkeypatch.setenv("FAKE_REPORT", str(report))
    monkeypatch.setenv("FAKE_TAKEAWAY", checks.parse_report(report.read_text())["takeaway"])
    monkeypatch.setattr(run_eval, "LIBRARY", library)

    fixture = {"name": "revision", "video": VIDEO, "followup": "Tighten the takeaway.",
               "expect": {"lang": "en", "chapters": 5}}
    args = argparse.Namespace(agent="claude", model=None, agent_args=None, timeout=60, live=False)
    out = tmp_path / "run"
    result = run_eval.run_case(fixture, 1, args, {"path": str(tmp_path / "skill")}, out)

    case = out / "revision-1"
    first, second = (case / "command.txt").read_text().splitlines()
    session = first.split("--session-id ", 1)[1].split()[0]
    assert f"--resume {session}" in second and second.endswith("'Tighten the takeaway.'")
    assert (case / "trace-2.jsonl").exists() and (case / f"turn1-{name}").exists()
    assert result["reports"] == [name] and not list((library / "reports").iterdir())
    revision = {k: v for k, v in result["gates"].items() if k.startswith("revision_")}
    assert revision and all(revision.values()), revision
    assert result["gates"]["finished"] and result["metrics"]["cost_usd"] == 0.02


def test_trace_metrics_count_lint_stops_and_warnings():
    trace = _claude_trace(
        ("Bash", {"command": "python3 /s/render_report.py --payload-file p.json --output-dir /r"},
         "ERROR:RENDER_LINT 1 problem: (1) TAGS has 1; use 3–5."),
        ("Bash", {"command": "python3 /s/render_report.py --payload-file p.json --output-dir /r"},
         "RENDER_WARN: TAGS has 1; use 3–5\nOUTPUT_PATH: /r/x.html"))
    m = checks.trace_metrics(trace)
    assert (m["render_attempts"], m["lint_stops"], m["lint_warnings"]) == (2, 1, 1)
    assert checks.gates(FIXTURE, trace, None, 1)["render_ok_within_retry"] is True
