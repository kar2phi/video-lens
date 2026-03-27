# Fork Analysis: Gdetrane/video-lens — Security & Hardening Adoption Plan

The [Gdetrane/video-lens](https://github.com/Gdetrane/video-lens) fork (2 commits, Mar 24-25 2026) adapts video-lens for Linux/Claude-only use. The Linux-specific and multi-agent-removal changes are out of scope, but the fork contains **security hardening** and **skill reliability** improvements worth adopting. This document catalogues every adoptable difference with implementation-ready details.

Decisions: keep Raycast, keep multi-agent support, keep macOS-first behavior.

---

## 1. Security: Add `rel="noopener noreferrer"` to all external links

### Problem

Several `target="_blank"` links are missing `rel="noopener noreferrer"`, which exposes the opener page to potential `window.opener` manipulation and leaks referrer information to third-party sites.

### Current state

| File | Line | Current | Issue |
|---|---|---|---|
| `skills/video-lens/template.html` | 958 | `<a href="...github..." target="_blank">View on GitHub</a>` | Missing `rel` entirely |
| `skills/video-lens/template.html` | 1013 | `<a href="{{VIDEO_URL}}" target="_blank">Open on YouTube</a>` | Missing `rel` entirely |
| `skills/video-lens/template.html` | 1369 | `<a href="{{VIDEO_URL}}" target="_blank" ...>Watch on YouTube</a>` (onPlayerError fallback) | Missing `rel` entirely |
| `skills/video-lens-gallery/index.html` | 555 | `<a href="...github..." target="_blank">View on GitHub</a>` | Missing `rel` entirely |
| `skills/video-lens-gallery/index.html` | 952 | `titleLink.rel = 'noopener';` (list view JS) | Has `noopener` but missing `noreferrer` |
| `skills/video-lens-gallery/index.html` | 1042 | `titleLink.rel = 'noopener';` (card view JS) | Has `noopener` but missing `noreferrer` |
| `skills/video-lens/scripts/fetch_metadata.py` | 21 | `rel="noopener"` in `_linkify()` | Has `noopener` but missing `noreferrer` |

### Already correct (no change needed)

| File | Line | Status |
|---|---|---|
| `template.html` | 1604 | `rel="noopener noreferrer"` in description URL linkification |
| `template.html` | 1614 | `.video-description a` rewrite applies `rel="noopener noreferrer"` |

### Implementation

**`skills/video-lens/template.html`:**
- Line 958: `target="_blank"` -> `target="_blank" rel="noopener noreferrer"`
- Line 1013: `target="_blank"` -> `target="_blank" rel="noopener noreferrer"`
- Line 1369: `target="_blank"` -> `target="_blank" rel="noopener noreferrer"`

**`skills/video-lens-gallery/index.html`:**
- Line 555: `target="_blank"` -> `target="_blank" rel="noopener noreferrer"`
- Line 952: `titleLink.rel = 'noopener';` -> `titleLink.rel = 'noopener noreferrer';`
- Line 1042: `titleLink.rel = 'noopener';` -> `titleLink.rel = 'noopener noreferrer';`

**`skills/video-lens/scripts/fetch_metadata.py`:**
- Line 21: `rel="noopener"` -> `rel="noopener noreferrer"`

---

## 2. Security: PID-file-based server management (serve_report.sh)

### Problem

The current `serve_report.sh` uses `lsof -ti:$PORT | xargs kill` to kill existing servers. This has two issues:
1. **Over-broad**: kills *any* process on port 8765, not just video-lens servers (could kill unrelated services)
2. **Platform fragility**: `lsof` flags vary across platforms
3. **No startup verification**: the server is assumed to start successfully

### Current code — `skills/video-lens/scripts/serve_report.sh`

```bash
# Kill any existing server on the port
lsof -ti:"$PORT" | xargs kill 2>/dev/null || true
sleep 0.2
```

### Fork's approach

Uses a PID file at `${XDG_CACHE_HOME:-$HOME/.cache}/video-lens/server.pid`:

```bash
PID_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/video-lens"
PID_FILE="$PID_DIR/server.pid"

# Kill previous video-lens server via PID file
mkdir -p "$PID_DIR"
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
    sleep 0.2
  fi
  rm -f "$PID_FILE"
fi

# Start HTTP server in background
python3 -m http.server "$PORT" --directory "$SERVE_DIR" &>/dev/null &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"
sleep 1

# Verify server started
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
  echo "ERROR: HTTP server failed to start on port $PORT" >&2
  rm -f "$PID_FILE"
  exit 1
fi
```

### Recommended adoption (with modifications)

Adopt the PID-file approach **but keep these existing behaviors** that the fork removed:

1. **Keep the explicit serve root argument** (`$2`) — used by SKILL.md Step 6 and `task dev` to serve both `reports/` and `index.html` from the same root
2. **Keep `open` before `xdg-open`** check order (macOS-first)

Changes to make:
1. Replace `lsof -ti:"$PORT" | xargs kill` with PID-file kill logic
2. Add server start verification (`kill -0`)
3. Store/read PID from `${XDG_CACHE_HOME:-$HOME/.cache}/video-lens/server.pid`

### Note on test cleanup

The tests (`test_e2e.py` `test_render_and_serve` and `test_claude_session` finally blocks) use `lsof -ti:8765` for cleanup. These should be updated to use PID-file cleanup, or keep `lsof` as a fallback in tests only (controlled environment).

---

## 3. Skill Hardening: Make yt-dlp a required dependency

### Problem

yt-dlp is currently marked "optional but recommended" in `SKILL.md`. In practice, reports are significantly better with yt-dlp (chapters, accurate metadata, video description). Making it optional adds complexity to the skill prompt and every error-handling path.

### Current state

**`skills/video-lens/SKILL.md`:**
- Line 5 (compatibility): `"Requires Python 3 and youtube-transcript-api >=0.6.3. Optional but recommended: yt-dlp and deno..."`
- Step 2b intro: `"If yt-dlp is unavailable or the command fails, proceed without its data"`
- Error table row: `yt-dlp not installed -> Suggest brew install yt-dlp or pip install yt-dlp; continue without enriched metadata -- do NOT stop.`

**`requirements.txt`:** `yt-dlp>=2026.3.3`

### Fork's changes

**Compatibility line:**
```
"Requires Python 3, youtube-transcript-api >=0.6.3, and yt-dlp for metadata and chapters."
```

**Step 2b intro:**
```
yt-dlp is required for enriched metadata, chapters, and video descriptions.
If the command fails, report the error and proceed with Step 2 metadata only.
```

**Error table:**
```
yt-dlp not installed -> Print: `pip install yt-dlp` and stop -- yt-dlp is required.
```

**`requirements.txt`:** `yt-dlp>=2026.3.17`

### Recommended adoption

1. Update compatibility string to state yt-dlp is required
2. Update Step 2b language to frame yt-dlp as required
3. Change error handling: if yt-dlp is not installed, **stop** (not continue)
4. Keep `brew install yt-dlp` as an option alongside `pip install yt-dlp` (macOS)
5. Bump version pin in `requirements.txt` to `>=2026.3.17`
6. Remove "deno" from compatibility string (not used anywhere)

### Files to modify
- `skills/video-lens/SKILL.md` -- lines 5, 65-66, 254
- `requirements.txt` -- line 2

---

## 4. Version pin: requirements.txt

### Current
```
yt-dlp>=2026.3.3
```

### Fork
```
yt-dlp>=2026.3.17
```

Bump to `>=2026.3.17` for a more recent, tested version. (Covered by item 3 above, listed separately for tracking.)

---

## Skipped changes (fork-only, not adopting)

| Fork change | Reason to skip |
|---|---|
| Simplify agent discovery to Claude-only | Keeping multi-agent support (8-directory loop) |
| Simplify gallery SKILL.md discovery | Same -- keeping multi-agent |
| Remove `install-raycast` Taskfile task | Keeping Raycast (macOS) |
| Simplify `install-skill-local` to Claude-only | Keeping multi-agent AGENT= parameter |
| Remove Raycast script | Keeping `scripts/raycast-video-lens.sh` |
| Swap `open`/`xdg-open` order | Keeping macOS-first (`open` before `xdg-open`) |

---

## Summary: What to adopt

| # | Change | Effort |
|---|---|---|
| 1 | `rel="noopener noreferrer"` on all external links | Small -- 7 edits across 3 files |
| 2 | PID-file server management (keep explicit root arg) | Medium -- rewrite kill/verify logic in serve_report.sh |
| 3 | Make yt-dlp required + bump version pin | Small -- 3 edits in SKILL.md + 1 in requirements.txt |

## Implementation order

1. **`rel="noopener noreferrer"`** -- pure security, no behavioral change, no risk
2. **yt-dlp version pin bump** -- trivial, no risk
3. **yt-dlp required dependency** -- SKILL.md wording changes
4. **PID-file server management** -- behavioral change, needs testing

## Verification

After all changes:
```bash
task test          # fast tests -- template rendering, index building, serve
task test-full     # slow tests -- real transcript fetch, metadata, Claude session
task dev           # visual check -- template renders and serves correctly
```
