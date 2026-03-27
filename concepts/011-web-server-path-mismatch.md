# 011 — Web Server Path Mismatch Analysis

## Problem

When triggering a video-lens run, the HTML report sometimes opens but cannot be accessed because the web server is running on a different path. The behavior appears non-deterministic and may involve interactions between the two skills (video-lens and video-lens-gallery).

## Architecture Overview

Both skills share a single serve script (`skills/video-lens/scripts/serve_report.sh`) and a single HTTP server instance on **port 8765**. The server lifecycle is managed via a PID file at `~/.cache/video-lens/server.pid` — each invocation kills any previous server before starting a new one.

### How each entry point calls serve_report.sh

| Entry point | Arguments | Serve root | URL path |
|---|---|---|---|
| video-lens SKILL.md (step 6) | `serve_report.sh "OUTPUT_PATH" ~/Downloads/video-lens` | `~/Downloads/video-lens` | `reports/<file>.html` |
| video-lens-gallery SKILL.md (step 4) | `serve_report.sh ~/Downloads/video-lens/index.html ~/Downloads/video-lens` | `~/Downloads/video-lens` | `index.html` |
| `task dev` (Taskfile.yml) | `serve_report.sh ~/Downloads/video-lens/sample_output.html` | `~/Downloads/video-lens` (heuristic) | `sample_output.html` |

All three entry points resolve to the same serve root (`~/Downloads/video-lens`). The serve_report.sh path logic has three modes:

1. **Explicit root** (2 args): `SERVE_DIR = $2`, `URL_PATH = strip prefix`
2. **Reports heuristic** (1 arg, file in `reports/`): `SERVE_DIR = parent of reports/`, `URL_PATH = reports/<file>`
3. **Fallback** (1 arg, file not in `reports/`): `SERVE_DIR = file's directory`, `URL_PATH = <file>`

**Finding: The serve_report.sh logic is correct in all three modes.** No path inconsistencies exist between the two skills or `task dev`.

### Directory structure served

```
~/Downloads/video-lens/                     <- SERVE_ROOT (port 8765)
  index.html                                 <- gallery (http://localhost:8765/index.html)
  manifest.json                              <- gallery metadata
  reports/
    YYYY-MM-DD-HHmmss-video-lens_*.html      <- reports (http://localhost:8765/reports/<file>.html)
```

## Root Cause

### Bug: template.html `file://` fallback constructs mismatched cmd and URL

**File:** `skills/video-lens/template.html:1081-1088`

When a report is opened via `file://` (instead of `http://`), the template shows a fallback overlay with:
- A shell command to start a local server
- An "Open" button that links to the report via `http://localhost:8765/...`
- A 5-second auto-redirect countdown

The relevant code:

```javascript
var rawPath = window.location.pathname;
var dir = decodeURIComponent(rawPath.replace(/\/[^/]+$/, ''));
var parts = rawPath.split('/');
var file = parts[parts.length - 1];
var parent = parts[parts.length - 2];
var urlPath = (parent === 'reports') ? 'reports/' + file : file;
var localUrl = 'http://localhost:8765/' + urlPath;
var cmd = 'python3 -m http.server 8765 --directory "' + dir.replace(/"/g, '\\"') + '"';
```

For a report at `file:///Users/philka/Downloads/video-lens/reports/2026-03-27-file.html`:

| Variable | Value | Correct? |
|---|---|---|
| `dir` | `/Users/philka/Downloads/video-lens/reports` | - |
| `parent` | `reports` | - |
| `urlPath` | `reports/2026-03-27-file.html` | Yes |
| `localUrl` | `http://localhost:8765/reports/2026-03-27-file.html` | Yes (if serve root = `.../video-lens`) |
| `cmd` | `python3 -m http.server 8765 --directory ".../video-lens/reports"` | **No** — serves from `reports/`, not its parent |

The `cmd` starts the server inside `reports/`, so the file is served at `http://localhost:8765/2026-03-27-file.html`. But `localUrl` expects `http://localhost:8765/reports/2026-03-27-file.html` — a path that would resolve to `.../reports/reports/2026-03-27-file.html`, which doesn't exist. **Result: 404.**

### Compounding factor: stale server detection

The fallback UI polls `http://localhost:8765/` every 2 seconds (line 1218). If a server from a *previous* invocation is still running on port 8765 (serving from a different directory), the poll succeeds, the UI shows "Running", and the 5-second auto-redirect fires — navigating to a URL the stale server can't serve. The user sees a broken page with no clear explanation.

### Why the behavior appears non-deterministic

The bug only manifests when the report is opened via `file://` instead of `http://`. This happens when:
- The agent opens the file directly (`open ~/Downloads/video-lens/reports/file.html`) instead of through serve_report.sh
- serve_report.sh fails silently (port occupied, python3 not found, etc.) and the agent falls back to opening the file directly
- The browser has a cached `file://` bookmark or history entry

When serve_report.sh runs successfully (the normal path), the server is started correctly and the browser opens the `http://` URL directly — bypassing the fallback entirely.

## Proposed Fix

### 1. Fix the cmd/localUrl mismatch in template.html (critical)

**File:** `skills/video-lens/template.html:1088`

```javascript
// Before:
var cmd = 'python3 -m http.server 8765 --directory "' + dir.replace(/"/g, '\\"') + '"';

// After:
var serveDir = (parent === 'reports') ? dir.replace(/\/reports$/, '') : dir;
var cmd = 'python3 -m http.server 8765 --directory "' + serveDir.replace(/"/g, '\\"') + '"';
```

When the file is inside a `reports/` directory, the server command now uses the parent directory as the serve root, matching the `localUrl` path.

### 2. Replace blind sleep with active port check in serve_report.sh (robustness)

**File:** `skills/video-lens/scripts/serve_report.sh:60-61`

The current code sleeps 1 second and then checks if the process is alive (`kill -0`). This doesn't verify the server is actually listening.

```bash
# Before:
sleep 1

# After:
# Wait for server to listen (up to 3s)
for _i in 1 2 3 4 5 6; do
  curl -sf -o /dev/null "http://localhost:${PORT}/" 2>/dev/null && break
  sleep 0.5
done
```

This reduces the window where the browser opens before the server is ready to accept connections.

## What does NOT need to change

| Component | Status | Reason |
|---|---|---|
| `serve_report.sh` path logic (lines 28-38) | Correct | All three modes produce consistent SERVE_DIR and URL_PATH |
| video-lens SKILL.md invocation (line 225) | Correct | Passes 2 args with explicit root |
| video-lens-gallery SKILL.md invocation (line 55) | Correct | Passes 2 args with explicit root |
| Gallery `reportUrl()` (index.html:1002-1005) | Correct | Constructs URLs with `origin + '/' + href` |
| `task dev` invocation (Taskfile.yml:33) | Correct | 1-arg call, file at root level (not in `reports/`) |
| Port 8765 hardcoding | Out of scope | Would require coordinated changes across 6+ files |
| Server detection `no-cors` limitation | Inherent | Browser security prevents distinguishing 200 vs 404 in opaque responses |

## Verification

1. **`task dev`** — confirm `http://localhost:8765/sample_output.html` loads correctly
2. **file:// fallback** — open a report directly via `open ~/Downloads/video-lens/reports/<any-report>.html`:
   - Fallback should show cmd serving from `~/Downloads/video-lens` (not `.../reports`)
   - "Open" button should link to `http://localhost:8765/reports/<file>.html`
   - Starting the server with the shown cmd should make the report load at that URL
3. **Existing tests** — `task test` should pass
