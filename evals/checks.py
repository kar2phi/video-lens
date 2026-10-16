#!/usr/bin/env python3
"""Deterministic checks for video-lens runs: report parsing, quality metrics, trace gates.

Shared by evals/run_eval.py and the tests. Run directly to score saved reports:

    python3 evals/checks.py ~/Downloads/video-lens/reports     # per-model-family summary
    python3 evals/checks.py REPORT.html [REPORT.html ...] --json

Gates are pass/fail properties a run must hold (025 §12 regression gate). Metrics are
numbers compared across arms; they never fail a run on their own. Stdlib only.
"""
import argparse
import html as html_lib
import json
import pathlib
import re
import statistics
import sys
from collections import defaultdict
from urllib.parse import parse_qs, urlparse

TEMPLATE_TOKENS = ("VIDEO_ID", "VIDEO_TITLE", "VIDEO_URL", "META_LINE", "SUMMARY",
                   "TAKEAWAY", "KEY_POINTS", "OUTLINE", "DESCRIPTION_SECTION", "VIDEO_LENS_META")

# Function words only: frequent, topic-neutral, and rarely shared between these languages.
STOPWORDS = {
    "en": set("the and of to is that it for with on as this are be not you they by from was have but what which".split()),
    "de": set("der die das und ist nicht ein eine zu mit den auf für sich auch von dem des im wird sind werden oder aber wie".split()),
    "es": set("el la los las que y en un una es por con para se del no lo como más pero".split()),
    "fr": set("le la les et des est un une que en pour dans pas du qui sur au avec ce sont".split()),
    "it": set("il di che è la per un una non sono con del della gli anche come più".split()),
    "pt": set("o os de que e do da em um uma para com não se por mais como dos".split()),
    "nl": set("de het een en van is dat niet op te zijn met voor ook maar als wat".split()),
}


# ---------- report parsing ----------

def _text(fragment: str) -> str:
    return " ".join(html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment or "")).split())


def _grab(pattern: str, text: str) -> str:
    m = re.search(pattern, text, re.S)
    return m.group(1) if m else ""


def ts_to_seconds(display: str):
    """'▶ 2:03' or '1:02:03' → seconds; None when the text holds no time."""
    m = re.search(r"(?<![\d:])(?:(\d+):)?(\d{1,2}):(\d{2})(?![\d:])", display)
    if not m:
        return None
    h, mins, s = m.groups()
    return int(h or 0) * 3600 + int(mins) * 60 + int(s)


def parse_report(html: str) -> dict:
    meta_raw = _grab(r'<script type="application/json" id="video-lens-meta">(.*?)</script>', html)
    try:
        meta = json.loads(meta_raw.replace("<\\/", "</"))
    except ValueError:
        meta = None

    key_points = []
    kp_html = _grab(r'<section id="key-points">.*?<ul>(.*?)</ul>\s*</section>', html)
    for li in re.findall(r"<li>(.*?)</li>", kp_html, re.S):
        key_points.append({
            "headline": _text(_grab(r"<strong>(.*?)</strong>", li)),
            "paragraph": _text(" ".join(re.findall(r"<p>(.*?)</p>", li, re.S))),
            "text": _text(li),
        })

    outline = []
    for li in re.findall(r"<li>(.*?)</li>", _grab(r'<ol class="topics">(.*?)</ol>', html), re.S):
        a = re.search(r"<a\b([^>]*)>(.*?)</a>", li, re.S)
        attrs = a.group(1) if a else ""
        data_t = re.search(r'data-t="(\d+)"', attrs)
        href = html_lib.unescape(_grab(r'href="([^"]*)"', attrs))
        query = parse_qs(urlparse(href).query)
        href_t = (query.get("t") or [""])[0].rstrip("s")
        outline.append({
            "t": int(data_t.group(1)) if data_t else None,
            "href_video": (query.get("v") or [""])[0],
            "href_t": int(href_t) if href_t.isdigit() else None,
            "display_t": ts_to_seconds(_text(a.group(2))) if a else None,
            "title": _text(_grab(r'<span class="outline-title">(.*?)</span>', li)),
            "detail": _text(_grab(r'<span class="outline-detail">(.*?)</span>', li)),
        })

    return {
        "title": _text(_grab(r"<h1>(.*?)</h1>", html)),
        "meta_line": _text(_grab(r'<span class="meta-facts">(.*?)</span>', html)),
        "summary": _text(_grab(r'<section id="summary">\s*<h2>[^<]*</h2>\s*<p>(.*?)</p>', html)),
        "takeaway": _text(_grab(r'<section id="takeaway">\s*<h2>[^<]*</h2>\s*<p>(.*?)</p>', html)),
        "has_description": 'class="description-details"' in html,
        "key_points": key_points,
        "outline": outline,
        "meta": meta,
        "unreplaced": [t for t in TEMPLATE_TOKENS if "{{" + t + "}}" in html],
    }


# ---------- text heuristics ----------

def detect_lang(text: str):
    """Primary language code by function-word counts; None when too short or ambiguous."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    if len(words) < 20:
        return None
    scores = sorted(((sum(w in sw for w in words), lang) for lang, sw in STOPWORDS.items()), reverse=True)
    (best, lang), (second, _) = scores[0], scores[1]
    return lang if best >= 5 and best >= 1.5 * second else None


def primary_lang(code: str) -> str:
    return (code or "").split("-")[0].split("_")[0].lower()


def count_sentences(text: str) -> int:
    return len(re.findall(r"[^.!?…]+[.!?…]+(?=\s|$)", text)) or (1 if text.strip() else 0)


def _trigrams(text: str) -> set:
    w = re.findall(r"\w+", text.lower())
    return {tuple(w[i:i + 3]) for i in range(len(w) - 2)}


def overlap(a: str, b: str) -> float:
    """Share of a's word trigrams that also occur in b (1.0 = a restates b)."""
    ta = _trigrams(a)
    return round(len(ta & _trigrams(b)) / len(ta), 2) if ta else 0.0


def length_band(duration_s):
    """SKILL.md 'Length adjustments': (summary sentences, outline entries) per band."""
    if not duration_s:
        return None
    minutes = duration_s / 60
    if minutes < 10:
        return {"band": "short", "summary": (2, 2), "outline": (3, 6)}
    if minutes < 45:
        return {"band": "medium", "summary": (2, 3), "outline": (5, 12)}
    if minutes < 90:
        return {"band": "long", "summary": (3, 4), "outline": (8, 15)}
    return {"band": "very long", "summary": (3, 4), "outline": (10, 20)}


# ---------- metrics ----------

def report_metrics(rep: dict, duration_s=None, chapters=None, existing_tags=None) -> dict:
    kps, outline = rep["key_points"], rep["outline"]
    tags = (rep["meta"] or {}).get("tags") or []
    times = [o["t"] for o in outline]
    m = {
        "kp_count": len(kps),
        "kp_in_range": 3 <= len(kps) <= 8,
        "kp_paragraph_share": round(sum(bool(k["paragraph"]) for k in kps) / len(kps), 2) if kps else 0.0,
        "outline_count": len(outline),
        "ts_mismatches": sum(1 for o in outline
                             if o["t"] is None or not (o["t"] == o["href_t"] == o["display_t"])),
        "outline_monotonic": all(a is not None and b is not None and a < b for a, b in zip(times, times[1:])),
        "outline_details_share": round(sum(bool(o["detail"]) for o in outline) / len(outline), 2) if outline else 0.0,
        "summary_sentences": count_sentences(rep["summary"]),
        "takeaway_overlap": overlap(rep["takeaway"], rep["summary"]),
        "tags_count": len(tags),
        "tags_in_range": 3 <= len(tags) <= 5,
    }
    band = length_band(duration_s)
    if band:
        m["band"] = band["band"]
        lo, hi = band["summary"]
        m["summary_in_band"] = lo <= m["summary_sentences"] <= hi
        if not chapters:  # with chapters the outline count is the chapter count, not a band
            lo, hi = band["outline"]
            m["outline_in_band"] = lo <= len(outline) <= hi
        m["outline_within_duration"] = all(t is not None and t <= duration_s for t in times)
    if chapters:
        by_t = {o["t"]: o for o in outline if o["t"] is not None}
        def near(start):
            return next((by_t[t] for t in by_t if abs(t - int(start)) <= 1), None)
        hits = [near(c["start_time"]) for c in chapters]
        m["chapter_t_match"] = round(sum(h is not None for h in hits) / len(chapters), 2)
        m["chapter_title_match"] = round(sum(
            h is not None and h["title"] == " ".join(c["title"].split()) for h, c in zip(hits, chapters)
        ) / len(chapters), 2)
    if existing_tags is not None and tags:
        known = set(existing_tags)
        m["tags_reused_share"] = round(sum(t in known for t in tags) / len(tags), 2)
    return m


# ---------- agent traces ----------

def _block_text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict))


def _call_target(name: str, args: dict) -> str:
    """The string a gate inspects: the command for bash, the path for file tools."""
    args = args or {}
    if name == "bash":
        return str(args.get("command", ""))
    return str(args.get("file_path") or args.get("path") or args.get("filePath") or "")


def load_trace(lines, agent: str) -> dict:
    """Normalise a claude stream-json or pi --mode json event stream.

    Returns {"calls": [{"name", "target", "output", "is_error"}], "final", "model",
    "permission_denials", "cost_usd", "turns"}; tool names are lowercased.
    """
    calls, by_id = [], {}
    trace = {"calls": calls, "final": "", "model": "", "permission_denials": [],
             "cost_usd": None, "turns": 0}

    def add_call(cid, name, args):
        call = {"name": name.lower(), "target": _call_target(name.lower(), args),
                "output": "", "is_error": False}
        calls.append(call)
        by_id[cid] = call

    def set_result(cid, text, is_error):
        if cid in by_id:
            by_id[cid]["output"] = text
            by_id[cid]["is_error"] = bool(is_error)

    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if agent == "claude":
            if e.get("type") == "system" and e.get("subtype") == "init":
                trace["model"] = e.get("model", "")
            elif e.get("type") == "assistant":
                trace["turns"] += 1
                for b in e.get("message", {}).get("content", []):
                    if b.get("type") == "tool_use":
                        add_call(b.get("id"), b.get("name", ""), b.get("input"))
                    elif b.get("type") == "text" and b.get("text", "").strip():
                        trace["final"] = b["text"]
            elif e.get("type") == "user":
                content = e.get("message", {}).get("content", [])
                for b in content if isinstance(content, list) else []:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        set_result(b.get("tool_use_id"), _block_text(b.get("content")), b.get("is_error"))
            elif e.get("type") == "result":
                trace["final"] = e.get("result") or trace["final"]
                trace["permission_denials"] = e.get("permission_denials") or []
                trace["cost_usd"] = e.get("total_cost_usd")
        elif agent == "pi" and e.get("type") == "message_end":
            msg = e.get("message", {})
            if msg.get("role") == "assistant":
                trace["turns"] += 1
                trace["model"] = msg.get("model") or trace["model"]
                for b in msg.get("content", []):
                    if b.get("type") == "toolCall":
                        add_call(b.get("id"), b.get("name", ""), b.get("arguments"))
                    elif b.get("type") == "text" and b.get("text", "").strip():
                        trace["final"] = b["text"]
            elif msg.get("role") == "toolResult":
                set_result(msg.get("toolCallId"), _block_text(msg.get("content")), msg.get("isError"))
    return trace


def trace_metrics(trace: dict) -> dict:
    calls = trace["calls"]
    renders = [c for c in calls if c["name"] == "bash" and "render_report.py" in c["target"]
               and "--schema" not in c["target"]]
    return {
        "tool_calls": len(calls),
        "bash_calls": sum(c["name"] == "bash" for c in calls),
        "render_attempts": len(renders),
        "turns": trace["turns"],
        "cost_usd": trace["cost_usd"],
        "final_has_url": bool(re.search(r"http://localhost:\d+/reports/\S+\.html", trace["final"])),
    }


# ---------- gates ----------

SUCCESS_RE = re.compile(r"report ready|http://localhost:\d+/reports/", re.I)
FALLBACK_RE = re.compile(r"whisper|local(ly)?\s+transcri|transcri\w*\s+(it\s+)?local|lokal", re.I)


def gates(fixture: dict, trace, report, report_count: int, chapters=None) -> dict:
    """Pass/fail properties for one run. A gate is None when its input is unavailable."""
    expect, video = fixture["expect"], fixture["video"]
    calls = trace["calls"] if trace else []
    bash = [c for c in calls if c["name"] == "bash"]
    served = any("HTML_REPORT:" in c["output"] for c in bash)
    g = {}
    if trace is not None:
        g["no_template_read"] = not any("template.html" in c["target"] for c in calls)
        g["no_hand_written_html"] = not any(
            c["name"] in ("write", "edit") and c["target"].endswith(".html") for c in calls)
        g["no_permission_denials"] = not trace["permission_denials"]
        g["no_false_success"] = served or not SUCCESS_RE.search(trace["final"])

    if "error" in expect:  # the run must stop and ask
        g["no_report_written"] = report_count == 0
        if trace is not None:
            g["error_seen"] = any(f"ERROR:{expect['error']}" in c["output"] for c in bash)
            g["fallback_not_run"] = not any("transcribe_local.py" in c["target"] for c in bash)
            g["fallback_offered"] = bool(FALLBACK_RE.search(trace["final"]))
        return g

    g["report_written"] = report_count > 0
    if trace is not None:
        g["html_report_seen"] = served
        renders = [c for c in bash if "render_report.py" in c["target"] and "--schema" not in c["target"]]
        accepted = [i for i, c in enumerate(renders) if "OUTPUT_PATH:" in c["output"]]
        g["render_ok_within_retry"] = bool(accepted) and accepted[0] <= 1
    if report is None:
        return g
    meta = report["meta"] or {}
    g["structure"] = bool(report["summary"] and report["takeaway"] and report["key_points"]
                          and report["outline"] and meta.get("videoId") == video
                          and not report["unreplaced"])
    g["outline_links_own_video"] = bool(report["outline"]) and all(
        o["href_video"] == video for o in report["outline"])
    body = " ".join([report["summary"], report["takeaway"]] + [k["text"] for k in report["key_points"]])
    g["language"] = detect_lang(body) == primary_lang(expect["lang"])
    if expect.get("lang_warn"):
        g["lang_warn_flagged"] = "⚠" in report["meta_line"]
    if expect.get("chapters") and chapters:
        g["chapters_anchored"] = report_metrics(report, chapters=chapters)["chapter_t_match"] >= 0.8
    return g


# ---------- library CLI ----------

def _family(model: str) -> str:
    model = (model or "").lower()
    for fam in ("qwen", "claude", "gpt", "gemma"):
        if fam in model:
            return fam
    return "codex/gpt" if "codex" in model else ("unknown" if not model else "other")


def summarise_library(paths) -> dict:
    rows = defaultdict(list)
    for p in paths:
        rep = parse_report(pathlib.Path(p).read_text(encoding="utf-8", errors="ignore"))
        if not rep["meta"] or not rep["key_points"]:
            continue
        m = report_metrics(rep)
        m["duration_s"] = rep["meta"].get("durationSeconds")
        rows[_family(rep["meta"].get("agentModel"))].append(m)
    out = {}
    for fam, ms in sorted(rows.items()):
        durs = [m["duration_s"] for m in ms if isinstance(m["duration_s"], int)]
        out[fam] = {
            "reports": len(ms),
            "kp_zero_paragraphs": sum(m["kp_paragraph_share"] == 0 for m in ms),
            "kp_all_paragraphs": sum(m["kp_paragraph_share"] == 1 for m in ms),
            "kp_out_of_range": sum(not m["kp_in_range"] for m in ms),
            "reports_with_ts_mismatch": sum(m["ts_mismatches"] > 0 for m in ms),
            "ts_mismatch_entries": sum(m["ts_mismatches"] for m in ms),
            "takeaway_overlap_gt_0.5": sum(m["takeaway_overlap"] > 0.5 for m in ms),
            "median_generation_s": statistics.median(durs) if durs else None,
        }
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+", help="report .html files or a directory of them")
    ap.add_argument("--json", action="store_true", help="per-report metrics as JSON lines")
    args = ap.parse_args(argv)
    files = []
    for p in map(pathlib.Path, args.paths):
        files += sorted(p.glob("*.html")) if p.is_dir() else [p]
    if args.json:
        for f in files:
            rep = parse_report(f.read_text(encoding="utf-8", errors="ignore"))
            print(json.dumps({"file": f.name, **report_metrics(rep)}, ensure_ascii=False))
        return 0
    summary = summarise_library(files)
    cols = list(next(iter(summary.values()), {}).keys())
    print("| family | " + " | ".join(cols) + " |")
    print("|---" * (len(cols) + 1) + "|")
    for fam, row in summary.items():
        print(f"| {fam} | " + " | ".join(str(row[c]) for c in cols) + " |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
