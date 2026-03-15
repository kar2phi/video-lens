#!/usr/bin/env bash
# Serve an HTML report via a local HTTP server and open it in the browser.
#
# Usage: serve_report.sh /absolute/path/to/report.html
#
# - Kills any existing server on port 8765
# - Starts python3 http.server in the file's directory
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

DIR="$(dirname "$HTML_PATH")"
FILE="$(basename "$HTML_PATH")"
PORT=8765

# Kill any existing server on the port
lsof -ti:"$PORT" | xargs kill 2>/dev/null || true
sleep 0.2

# Start HTTP server in background
python3 -m http.server "$PORT" --directory "$DIR" &>/dev/null &
sleep 1

# Open in browser
URL="http://localhost:${PORT}/${FILE}"
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
