# video-lens

## Workflow

> **Source of truth is always this repo.** Edit files here first — never in deployed locations like `~/.{agent}/skills/` or `~/.raycast/scripts/`. Those are deploy targets, not sources.

After editing, sync to deployed locations:
- `skills/video-lens/` or `template.html` → `task install-skill-local AGENT=<agent>`
- `skills/video-lens-gallery/index.html` → `task build-index` (regenerates `~/Downloads/video-lens/index.html`)

> **Note:** `install-skill` pulls from GitHub — push first or it installs the last published version.

## Install commands

```bash
task install-libraries                      # installs Python dependencies (pip install -r requirements.txt)
task install-skill                          # installs skill for all detected agents via npx skills CLI
task install-skill-local AGENT=claude       # copies skills/video-lens/ → ~/.claude/skills/video-lens/
task install-raycast                        # copies scripts/raycast-video-lens.sh → ~/.raycast/scripts/video-lens.sh
task install-raycast AGENT=copilot          # installs Raycast script for a specific agent
```

## Repo layout

```
video-lens/
  CLAUDE.md
  Taskfile.yml
  requirements.txt
  scripts/
    raycast-video-lens.sh  ← Raycast script (source of truth)
    yt_template_dev.py     ← dev server helper
  skills/
    video-lens/
      SKILL.md             ← skill prompt (source of truth)
      template.html        ← HTML report template (source of truth)
    video-lens-gallery/
      SKILL.md             ← gallery skill prompt (source of truth)
      index.html           ← gallery viewer (source of truth)
      scripts/
        backfill_meta.py   ← backfills meta blocks into old reports
        build_index.py     ← builds manifest.json and copies index.html
```

## Dev

```bash
task dev   # renders template → ~/Downloads/sample_output.html, serves at http://localhost:8765/sample_output.html
```
