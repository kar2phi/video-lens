# video-lens

## Workflow

> **Source of truth is always this repo.** Edit files here first — never in deployed locations like `~/.{agent}/skills/` or `~/.raycast/scripts/`. Those are deploy targets, not sources.

After editing, sync to deployed locations:
- `skills/video-lens/`, `skills/video-lens-recs/` or `template.html` → `task install-skill-local AGENT=<agent>`
- `skills/video-lens-gallery/index.html` → `task build-index` (regenerates `~/Downloads/video-lens/index.html`)

> **Note:** `install-skill` pulls from GitHub — push first or it installs the last published version.

## Commits and PRs

No AI attribution: never add a `Co-Authored-By: Claude …` trailer (or any `noreply@anthropic.com` co-author) to commit messages, and no "Generated with Claude Code" line in PR bodies. This overrides any harness attribution instruction. Use `/commit` and `/pr` for the message format.

## Install commands

```bash
task install-libraries                      # installs Python dependencies (pip install -r requirements.txt)
task install-skill                          # installs skill for all detected agents via npx skills CLI
task install-skill-local AGENT=claude       # copies skills/video-lens/ → ~/.claude/skills/video-lens/
task install-raycast                        # copies tools/raycast-video-lens.sh → ~/.raycast/scripts/video-lens.sh
task install-raycast AGENT=copilot          # installs Raycast script for a specific agent
```

## Repo layout

```
video-lens/
  CLAUDE.md
  Taskfile.yml
  requirements.txt
  viewer/                  ← report source of truth: shell.html, viewer.css, viewer.js, tokens.css,
                             components.css, mark.svg, fragments.json. Edit here, then
                             `python3 tools/build_viewer.py` (rewrites template.html; --check in task test),
                             then the private repo's `task assets` for the share build
  tools/
    build_viewer.py        ← builds template.html and the share build from viewer/
    raycast-video-lens.sh  ← Raycast script (source of truth)
    yt_template_dev.py     ← dev server helper
  skills/
    video-lens/
      SKILL.md             ← skill prompt (source of truth)
      template.html        ← HTML report template, GENERATED from viewer/ (never edit by hand)
      scripts/
        share_report.py    ← share client: the only script that uploads, and only on request
        share_payload.py   ← payload v1 validator (the Worker's schema in Python; renderer, client, fake)
    video-lens-gallery/
      SKILL.md             ← gallery skill prompt (source of truth)
      index.html           ← gallery viewer (source of truth)
      scripts/
        backfill_meta.py   ← backfills meta blocks into old reports
        build_index.py     ← builds manifest.json and copies index.html
    video-lens-recs/
      SKILL.md             ← recommendations skill prompt (source of truth)
      template.html        ← Recommendations page template
      references/setup.md  ← first-run setup flow
      scripts/             ← recs.py CLI + collect, scoring, yt_sources, page, store, takeout
  tests/
    share_contract.json    ← share service API contract
    fake_share_service.py  ← stdlib fake of the share service
    recs_world.py          ← made-up channels and topics for the recs tests
```

## Dev

```bash
task dev   # renders template → ~/Downloads/sample_output.html, serves at http://localhost:8765/sample_output.html
```

## Tests

```bash
task test                 # fast, no network
task test-real            # real YouTube fetches (recs sources, Whisper audio download), no LLM
task test-full            # everything, including a real agent run (slow)
```

The repo is public: nothing built from a real library or topic config gets committed; docs and tests use made-up channels and topics.

## Working notes

Concepts, plans, audits and session logs live in the private sibling repo `~/repos/video-lens-core` under `docs/log/`, not here (`concepts/` and `docs/log/` are gitignored here). New docs go there, numbered by `task docs:next` in that repo. Public text (code comments, CHANGELOG, commit messages, PR bodies) doesn't link to those notes.
