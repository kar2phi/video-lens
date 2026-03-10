# video-lens

## Workflow

Always edit skill files, templates, and Raycast scripts **in this repo first**, then push to their installed locations via `task install-skill` or `task install-raycast`.

Never edit files directly in `~/.{agent}/skills/` or `~/.raycast/scripts/` — those are deploy targets, not sources.

## Install commands

```bash
task install                        # installs Python dependencies (pip install -r requirements.txt)
task install-skill                  # installs skill for Claude Code (default)
task install-skill AGENT=copilot    # installs skill for GitHub Copilot
task install-skill AGENT=gemini     # installs skill for Gemini CLI
task install-skill AGENT=cursor     # installs skill for Cursor
task install-skill AGENT=windsurf   # installs skill for Windsurf
task install-skill AGENT=opencode   # installs skill for OpenCode
task install-skill AGENT=codex      # installs skill for Codex
task install-raycast                # copies scripts/raycast-video-lens.sh → ~/.raycast/scripts/video-lens.sh
```

The `AGENT` parameter controls which agent's skill directory is targeted (`~/.{AGENT}/skills/video-lens/`). The template path in SKILL.md is automatically patched during install.

## Repo layout

```
video-lens/
  CLAUDE.md
  Taskfile.yml
  requirements.txt
  scripts/
    raycast-video-lens.sh  ← Raycast script (source of truth)
    yt_template_dev.py     ← dev server helper
    sample_output.html     ← example output for dev/testing
  skill/
    SKILL.md               ← skill prompt (source of truth)
    template.html          ← HTML report template (source of truth)
```

## Dev

```bash
task dev   # renders template with sample content at http://localhost:8765/sample_output.html
```
