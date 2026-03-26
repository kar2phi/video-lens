---
name: video-lens-gallery
description: >
  Open or rebuild the video-lens gallery index — your personal library of saved video summaries.
  Use this whenever the user wants to browse, open, or search saved video reports:
  "show my gallery", "open video library", "browse saved videos", "build gallery",
  "what videos have I saved", "show my video notes", "my video summaries",
  "find my saved summary for [topic]", "rebuild the index", "show video-lens index",
  "backfill metadata", "update index".
license: MIT
allowed-tools: Bash
---

# video-lens-gallery

Manage and browse your saved video-lens reports.

## Step 1 — Locate skill scripts

Discover both `video-lens/scripts` (`$_sd`) and `video-lens-gallery/scripts` (`$_gd`) using the standard 8-agent discovery loop:

```bash
_sd=$(for d in ~/.agents ~/.claude ~/.copilot ~/.gemini ~/.cursor ~/.windsurf ~/.opencode ~/.codex; do
  [ -d "$d/skills/video-lens/scripts" ] && echo "$d/skills/video-lens/scripts" && break
done)
_gd=$(for d in ~/.agents ~/.claude ~/.copilot ~/.gemini ~/.cursor ~/.windsurf ~/.opencode ~/.codex; do
  [ -d "$d/skills/video-lens-gallery/scripts" ] && echo "$d/skills/video-lens-gallery/scripts" && break
done)
[ -z "$_sd" ] && echo "video-lens skill not found — install it first: npx skills add kar2phi/video-lens" && exit 1
[ -z "$_gd" ] && echo "video-lens-gallery skill not found — install it first: npx skills add kar2phi/video-lens" && exit 1
```

## Step 2 — Backfill metadata (only if requested)

If the user's request mentions "backfill", run:

```bash
python3 "$_gd/backfill_meta.py" --dir ~/Downloads/video-lens
```

## Step 3 — Rebuild index

Check that the reports directory exists before running:

```bash
[ -d ~/Downloads/video-lens ] || { echo "No reports directory found — save some videos first with the video-lens skill."; exit 1; }
python3 "$_gd/build_index.py" --dir ~/Downloads/video-lens
```

Tell the user the number of reports indexed, from the script's output.

## Step 4 — Serve gallery

```bash
bash "$_sd/serve_report.sh" ~/Downloads/video-lens/index.html ~/Downloads/video-lens
```

Tell the user the gallery is now available at `http://localhost:8765/index.html`.
