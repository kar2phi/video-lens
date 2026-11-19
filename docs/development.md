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
task test                      # fast: scripts, renderer, sanitiser, viewer build (no network, ~10 s)
task test-real                 # real YouTube: recs sources, Whisper audio download, no LLM (~1 min)
task test-full                 # everything, including a real agent run (slow, needs an API key)
```

Every test runs against made-up data: `tests/recs_world.py` builds channels, topics and a
library for the recs tests, and `tests/fake_share_service.py` stands in for the share service,
checked against `tests/share_contract.json`.

---

## Releasing

The installed skill compares its version with `version.json` at the repo root, fetched from
`main` (058). In the same commit, bump `metadata.version` in `skills/video-lens/SKILL.md` and
`latest` in `version.json`; `tests/test_update_check.py` fails when they differ. Change
`minimum` only on purpose: when older installs really break (the share contract changes, YouTube
breaks an old fetch path, a security fix). Gallery and recs version bumps are independent and
leave `version.json` alone. Tests run with `VIDEO_LENS_NO_UPDATE_CHECK=1`.

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
        update_check.py   ← once a day, tells the user when a newer video-lens is out (058)
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
      template.html     ← Recommendations page template
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
    raycast-video-lens.sh ← Raycast script (source of truth)
    yt_template_dev.py ← dev server helper
  tests/              ← fast suite, network tier, slow e2e, share contract and fake share service
  docs/               ← guide, this page, screenshots
  Taskfile.yml
  requirements.txt
```

**Always edit files in this repo (the report page in `viewer/`, then `python3 tools/build_viewer.py --mode local`), then deploy with `task install-skill-local AGENT=claude` and `task install-raycast AGENT=claude`.** Never edit directly in `~/.{agent}/skills/` or `~/.raycast/scripts/`.
