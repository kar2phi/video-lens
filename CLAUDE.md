# video-lens

## Workflow

Always edit skill files, templates, and Raycast scripts **in this repo first**, then sync to installed locations.

Never edit files directly in `~/.{agent}/skills/` or `~/.raycast/scripts/` — those are deploy targets, not sources.

After editing `skills/video-lens/` or `template.html`, run `task install-skill-local AGENT=claude` to sync immediately. When ready to publish, push and run `task install-skill`.

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
```

## Dev

```bash
task dev   # renders template → ~/Downloads/sample_output.html, serves at http://localhost:8765/sample_output.html
```
