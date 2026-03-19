---
name: video-lens-gallery
description: Open or rebuild the video-lens gallery index. Triggers on "show my gallery", "open video library", "rebuild the index", "browse saved videos", "build gallery", "show video-lens index", "backfill metadata", "update index".
license: MIT
allowed-tools: Bash
---

# video-lens-gallery

Manage and browse your saved video-lens reports.

## Step 1 — Locate skill scripts

Discover both `video-lens/scripts` (`$_sd`) and `video-lens-gallery/scripts` (`$_gd`) using the standard agent discovery pattern:

```bash
# video-lens scripts (needed for serve_report.sh in Step 4)
_sd="$HOME/.claude/skills/video-lens/scripts"
[ -d "$_sd" ] || _sd="$HOME/.gemini/skills/video-lens/scripts"
[ -d "$_sd" ] || _sd="$HOME/.opencode/skills/video-lens/scripts"
[ -d "$_sd" ] || _sd="$HOME/.cursor/skills/video-lens/scripts"

# video-lens-gallery scripts (needed for build_index.py in Step 3)
_gd="$HOME/.claude/skills/video-lens-gallery/scripts"
[ -d "$_gd" ] || _gd="$HOME/.gemini/skills/video-lens-gallery/scripts"
[ -d "$_gd" ] || _gd="$HOME/.opencode/skills/video-lens-gallery/scripts"
[ -d "$_gd" ] || _gd="$HOME/.cursor/skills/video-lens-gallery/scripts"
```

If `$_sd` does not exist, exit with:

> `video-lens skill not found — install it first: npx skills add kar2phi/video-lens`

## Step 2 — Backfill metadata (only if requested)

If the user's request mentions "backfill" or "update metadata", run:

```bash
python3 "$_gd/backfill_meta.py" --dir ~/Downloads/video-lens
```

## Step 3 — Rebuild index

```bash
python3 "$_gd/build_index.py" --dir ~/Downloads/video-lens
```

## Step 4 — Serve gallery

```bash
bash "$_sd/serve_report.sh" ~/Downloads/video-lens/index.html
```
