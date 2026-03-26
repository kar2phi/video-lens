#!/usr/bin/env bash
# Serve an HTML report via a local HTTP server and open it in the browser.
#
# Usage: serve_report.sh /absolute/path/to/report.html [/serve/root/dir]
#
# - Kills any existing server on port 8765
# - Starts python3 http.server in the file's directory (or explicit root)
# - Opens the report in the default browser

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: serve_report.sh /path/to/report.html" >&2
    exit 1
fi

HTML_PATH="$1"

if [ ! -f "$HTML_PATH" ]; then
    echo "ERROR: File not found: $HTML_PATH" >&2
    exit 1
fi

DIR="$(cd "$(dirname "$HTML_PATH")" && pwd)"
FILE="$(basename "$HTML_PATH")"
PORT=8765

# Use explicit root if provided (tilde-expanded by caller), else fall back to heuristic
if [ $# -ge 2 ]; then
  SERVE_DIR="$(cd "$2" && pwd)"
  URL_PATH="${HTML_PATH#${SERVE_DIR}/}"
elif [[ "$(basename "$DIR")" == "reports" ]]; then
  SERVE_DIR="$(dirname "$DIR")"
  URL_PATH="reports/$FILE"
else
  SERVE_DIR="$DIR"
  URL_PATH="$FILE"
fi

# Kill any existing server on the port
lsof -ti:"$PORT" | xargs kill 2>/dev/null || true
sleep 0.2

# Start HTTP server in background
python3 -m http.server "$PORT" --directory "$SERVE_DIR" &>/dev/null &
sleep 1

# Open in browser
URL="http://localhost:${PORT}/${URL_PATH}"
if [[ "${NO_BROWSER:-}" != "1" ]]; then
  if command -v open &>/dev/null; then
      open "$URL"
  elif command -v xdg-open &>/dev/null; then
      xdg-open "$URL"
  else
      echo "Open $URL in your browser"
  fi
fi

echo "HTML_REPORT: $HTML_PATH"
