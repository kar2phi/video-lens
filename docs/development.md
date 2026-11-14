# Developing video-lens

Back to the [README](../README.md). User-facing docs: [guide.md](guide.md).

## Dev server

The report page is built from `viewer/` (`tokens.css`, `components.css`, `viewer.css`,
`viewer.js`, `shell.html`). `skills/video-lens/template.html` is generated from it; never edit it
by hand. After changing `viewer/`:

```bash
python3 tools/build_viewer.py --mode local   # rewrites template.html and the shared CSS of the gallery and Discover pages
python3 tools/build_viewer.py --check        # exit 1 when any generated file is stale (also run by task test)
task dev                                     # rebuild and serve a sample report
```

`task dev` serves a rendered sample report from `~/Downloads/video-lens/reports/` on
`http://localhost:8765/`.

---

## Testing

Three tiers, cheapest first:

```bash
task test                      # fast: scripts, renderer, sanitiser, eval checks (no network, ~10 s)
task test-real                 # real YouTube: fetch every fixture video, no LLM (~30 s)
task eval AGENT=claude         # real agent runs on the fixture videos, every report validated
task eval AGENT=pi MODEL=qwen3.8:27b-mxfp8
```

The fixtures in `evals/fixtures.json` each cover one branch: the happy path with chapters, a
German video, a language request, a missing language (`LANG_WARN`), a captions-disabled video
that must stop and ask before transcribing locally, and (with `SET=full`) a 1h36m talk.
`SET=share` runs the sharing cases: share and unshare, the terms notice before the first share,
a transcript that asks the agent to share, and a rate limit. Every case talks to its own fake
share service (`tests/fake_share_service.py`) with its own share config, so no eval run reaches a
real service.
`task eval` loads the skill from the working tree (or `REF=<git ref>`) into a throwaway
directory, so your installed copy is never touched. Each report is moved out of
`~/Downloads/video-lens` right after its run, and the gallery index is rebuilt at the end.

Each case is checked against **gates**: report served, no `template.html` read, no hand-written
HTML, first render accepted or fixed on the one retry, written in the transcript's language,
outline links to this video, chapters anchored, `⚠` suffix after `LANG_WARN`, no claimed
success without `HTML_REPORT:`, and for the captions-disabled video: no report and no
transcription without consent. Two sharing gates hold on every case: the closing share offer
appears exactly when preflight listed `share` (half the fixtures turn the offer off), and no
share happens unless the user asked for it. It also records **metrics**: key-point count and paragraph
share, timestamp mismatches, outline and summary length against the SKILL.md bands, tag reuse,
Takeaway/Summary overlap, tool calls, wall time and cost.

To A/B a SKILL.md change, run both arms and compare them. The compare exits 1 on any gate that
held in every A run and broke in a B run:

```bash
task eval AGENT=claude REF=HEAD RUNS=2      # committed skill
task eval AGENT=claude RUNS=2               # working tree
task eval-compare A=evals/results/<run-a> B=evals/results/<run-b>
task eval-library                           # same metrics over every saved report, by model family
```

The agent's transcript and metadata fetches are recorded in `evals/cache/` the first time
each fixture runs and replayed after that. Both arms of an A/B then read byte-identical
transcripts, and a 40-run comparison makes about 15 YouTube requests instead of about a
hundred. The cache key includes the fetch script's hash, so a branch that changes the
fetcher records its own inputs. `LIVE=1` fetches everything fresh; `task test-real` always
does.

Bursts of transcript requests get the IP blocked by YouTube, sometimes for hours. On live
fetches the runner pauses between cases, checks once before starting, and marks blocked
cases `BLOCKED` (not scored). Blocks are never recorded into the cache.

`video-lens-recs` has its own eval, which replays recorded source pulls so runs are
deterministic and free:

```bash
task eval-recs AGENT=claude                         # built-in synthetic fixture + your recorded ones
task eval-recs AGENT=pi MODEL=qwen3.8:27b-mxfp8
task eval-recs-record NAME=ai-week REQUEST="what's new in AI this week"
python3 evals/run_recs_eval.py label ai-week        # yes / maybe / no per candidate (--review: all of them)
task eval-recs-prior                                # precision of the scoring prior alone, per weight variant
task eval-recs-compare A=evals/results/<run-a> B=evals/results/<run-b>
task eval-recs-rejudge RUN=evals/results/<run>     # re-score a run after relabelling, no agent
```

Gates: every pick is in the candidate table and none was already summarised or dismissed,
at most 2 per channel on a page, a full first page (12) unless fewer labelled-relevant rows fit under the channel cap, at least one pick from
outside your subscriptions when a relevant one exists, reasons that are not the title, the
chat list relayed unchanged, and the page served. With labels it also reports precision@5
and @10. Recorded fixtures contain your topics and library, so they live in the gitignored
`evals/recs_fixtures/`; the `synthetic` fixture uses made-up channels.

---

## Repo layout

```
video-lens/
  skills/
    video-lens/
      SKILL.md          ← skill prompt (source of truth)
      template.html     ← HTML report template (generated from viewer/)
      scripts/
        fetch_transcript.py
        fetch_metadata.py
        preflight.py
        render_report.py
        serve_report.sh
        share_report.py   ← turns a report into an unlisted link, only on request
        share_payload.py  ← checks a report against the share service's limits
        transcribe_local.py ← local Whisper fallback (optional deps: mlx-whisper + ffmpeg)
    video-lens-gallery/
      SKILL.md          ← gallery skill prompt (source of truth)
      index.html        ← gallery viewer (source of truth)
      scripts/
        backfill_meta.py  ← backfills meta blocks into old reports
        build_index.py    ← builds manifest.json and copies index.html
    video-lens-recs/
      SKILL.md          ← recommendations skill prompt (source of truth)
      template.html     ← Discover page template
      references/setup.md ← first-run setup, read only during setup
      scripts/
        recs.py           ← CLI: recommend, render, resolve, feedback, topics, account, stats
        collect.py        ← preflight + sources → filters → features → shortlist table
        scoring.py        ← hard filters, perf/velocity/affinity, prior, shortlist quotas
        yt_sources.py     ← yt-dlp listings and search, RSS, optional Data API, record/replay
        page.py           ← picks validation, Discover page, chat list
        store.py          ← config, subscriptions, shown log, feedback (XDG dirs)
        takeout.py        ← Google Takeout subscriptions import
  viewer/             ← report page source: tokens, components, viewer CSS/JS, shell
  tools/
    build_viewer.py   ← builds template.html (and the share viewer) from viewer/
  scripts/
    raycast-video-lens.sh ← Raycast script (source of truth)
    yt_template_dev.py← Dev server helper
  evals/
    fixtures.json     ← real fixture videos and what each must produce
    checks.py         ← report/trace gates and metrics (also scores the saved library)
    run_eval.py       ← runs an agent on the fixtures; --compare for A/B
    replay.py         ← records each fixture's fetch once, replays it after
    run_recs_eval.py  ← video-lens-recs eval: record, label, prior, run, compare
  tests/              ← fast suite, network tier (test_real_videos.py), slow e2e,
                        share contract and fake share service
  docs/               ← guide, this page, screenshots
  Taskfile.yml
  requirements.txt
```

**Always edit files in this repo (the report page in `viewer/`, then `python3 tools/build_viewer.py --mode local`), then deploy with `task install-skill-local AGENT=claude` and `task install-raycast AGENT=claude`.** Never edit directly in `~/.{agent}/skills/` or `~/.raycast/scripts/`.
