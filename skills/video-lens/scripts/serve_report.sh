#!/usr/bin/env bash
# Serve an HTML report via a local HTTP server and open it in the browser.
#
# Usage: serve_report.sh /absolute/path/to/report.html [/serve/root/dir]
#
# - Kills any previous video-lens server via PID file
# - Takes over, or reuses, a server already on the port that serves this directory
# - Starts python3 http.server in the file's directory (or explicit root)
# - Prints HTML_REPORT: only once the report URL returns this exact file
# - Opens the report in the default browser
#
# VIDEO_LENS_PORT overrides port 8765. It is meant for tests only: reports and
# the gallery link to localhost:8765.

set -euo pipefail

# Normalize a possibly-Windows-style path ("C:\foo\bar") to POSIX form
# ("/c/foo/bar"). On native Linux/macOS paths (already "/...") this is a
# no-op. Needed because on Windows the renderer emits native paths (Python's
# os.path uses backslashes there), while this script's own path arithmetic
# further down (dirname/basename/prefix-stripping against `pwd` output) is
# POSIX-only — without normalizing first, the prefix-strip silently fails to
# match and leaks the raw Windows path into the served URL. Used only for
# that internal arithmetic; $HTML_PATH itself is left exactly as given, since
# `-f`/`wc`/`grep` all accept native Windows paths fine under Cygwin/MSYS,
# and callers may rely on getting back the same path they passed in (see the
# final "HTML_REPORT:" line).
to_posix() {
  local p="$1"
  case "$p" in
    /*) printf '%s\n' "$p"; return ;;
  esac
  if command -v cygpath &>/dev/null; then
    cygpath -u "$p"
    return
  fi
  p="${p//\\//}"
  if [[ "$p" =~ ^([A-Za-z]):(.*)$ ]]; then
    # tr, not ${var,,}: macOS ships bash 3.2, which rejects ,, as a bad substitution.
    local drive
    drive="$(printf '%s' "${BASH_REMATCH[1]}" | tr '[:upper:]' '[:lower:]')"
    p="/${drive}${BASH_REMATCH[2]}"
  fi
  printf '%s\n' "$p"
}

# Command line of pid $1. Cygwin's ps has no -o, so fall back to /proc.
proc_args() {
  ps -p "$1" -o args= 2>/dev/null \
    || tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null \
    || true
}

# Exit 0 if something accepts connections on 127.0.0.1:$PORT. Unlike lsof, this
# works on Windows (Cygwin/MSYS) and on minimal Linux images.
port_in_use() {
  python3 -c 'import socket, sys
s = socket.socket()
s.settimeout(0.5)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)' "$PORT"
}

# Exit 0 if the report URL returns 200 with exactly this report's bytes, i.e.
# whoever answers on the port serves this run's file.
serves_this_report() {
  python3 -c 'import sys, urllib.parse, urllib.request
port, path, size = sys.argv[1], sys.argv[2], int(sys.argv[3])
url = "http://127.0.0.1:%s/%s" % (port, urllib.parse.quote(path))
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
try:
    with opener.open(url, timeout=1) as r:
        sys.exit(0 if r.status == 200 and len(r.read()) == size else 1)
except Exception:
    sys.exit(1)' "$PORT" "$URL_PATH" "$BYTES"
}

if [ $# -lt 1 ]; then
    echo "Usage: serve_report.sh /path/to/report.html" >&2
    exit 1
fi

HTML_PATH="$1"

if [ ! -f "$HTML_PATH" ]; then
    echo "ERROR:SERVE_FILE_NOT_FOUND $HTML_PATH" >&2
    exit 1
fi

BYTES=$(wc -c < "$HTML_PATH" | tr -d ' ')
if [ "$BYTES" -lt 4096 ] || ! grep -q '</html>' "$HTML_PATH"; then
    echo "ERROR:SERVE_REPORT_INCOMPLETE size=$BYTES path=$HTML_PATH" >&2
    exit 1
fi

PORT="${VIDEO_LENS_PORT:-8765}"
if ! [[ "$PORT" =~ ^[0-9]{4,5}$ ]] || [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
  echo "ERROR:SERVE_PORT_INVALID VIDEO_LENS_PORT must be a number from 1024 to 65535, got '$PORT'" >&2
  exit 1
fi

HTML_PATH_POSIX="$(to_posix "$HTML_PATH")"
DIR="$(cd "$(dirname "$HTML_PATH_POSIX")" && pwd)"
FILE="$(basename "$HTML_PATH_POSIX")"

# Use explicit root if provided (tilde-expanded by caller), else fall back to heuristic
if [ $# -ge 2 ]; then
  SERVE_DIR="$(cd "$2" && pwd)"
  URL_PATH="${HTML_PATH_POSIX#${SERVE_DIR}/}"
elif [[ "$(basename "$DIR")" == "reports" ]]; then
  SERVE_DIR="$(dirname "$DIR")"
  URL_PATH="reports/$FILE"
else
  SERVE_DIR="$DIR"
  URL_PATH="$FILE"
fi

PID_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/video-lens"
PID_FILE="$PID_DIR/server.pid"
SERVER_LOG="$PID_DIR/server.log"
mkdir -p "$PID_DIR"
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    # Verify it's actually our http.server on this port before killing — match
    # against the full command line, not just the truncated comm name.
    if proc_args "$OLD_PID" | grep -q "http.server.*$PORT"; then
      kill "$OLD_PID" 2>/dev/null || true
      sleep 0.2
    fi
  fi
  rm -f "$PID_FILE"
fi

# The PID file only tracks servers started with the same cache dir, so the port
# can still be held by a server from another session or cache root. Then:
# - a python http.server for OUR directory is taken over (killed and restarted),
#   which keeps it tracked by the PID file;
# - any other server that already returns this report is reused. This covers a
#   holder lsof cannot name (lsof is missing on Windows and minimal Linux). It
#   also avoids starting a second listener: Windows lets that bind next to the
#   first and then routes requests to either one;
# - anything else is refused loudly, never killed: it may be an unrelated
#   http.server the user runs for another project.
REUSE=0
if port_in_use; then
  LISTEN_PID="$(lsof -ti tcp:$PORT -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  LISTEN_ARGS=""
  if [ -n "$LISTEN_PID" ]; then
    LISTEN_ARGS="$(proc_args "$LISTEN_PID")"
  fi
  # Whole-word match on the directory: a substring match would also take over a
  # server for "$SERVE_DIR-archive" or a subdirectory.
  if [[ "$LISTEN_ARGS" == *http.server* && " $LISTEN_ARGS " == *" $SERVE_DIR "* ]]; then
    kill "$LISTEN_PID" 2>/dev/null || true
    # Wait (up to ~2s) for the port to actually be released before binding.
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      port_in_use || break
      sleep 0.2
    done
  elif serves_this_report; then
    REUSE=1
    echo "Reusing the server already on port $PORT; it serves this report." >&2
  else
    HOLDER="an unidentified process"
    if [ -n "$LISTEN_ARGS" ]; then
      HOLDER="$LISTEN_ARGS"
    elif [ -n "$LISTEN_PID" ]; then
      HOLDER="pid $LISTEN_PID"
    fi
    echo "ERROR:SERVE_PORT_BUSY port $PORT is in use by $HOLDER, which does not serve $SERVE_DIR. Stop it, then rerun." >&2
    exit 1
  fi
fi

if [ "$REUSE" = 0 ]; then
  # Start HTTP server in background and detach it from this shell so it survives
  # after the skill command exits. Log stderr/stdout so failures can be diagnosed.
  nohup python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$SERVE_DIR" \
    >"$SERVER_LOG" 2>&1 < /dev/null &
  SERVER_PID=$!
  echo "$SERVER_PID" > "$PID_FILE"

  # Wait (up to ~3s) until the report URL returns this report. A live process is
  # not proof: on Windows a stale listener on the same port may be the one answering.
  SERVED=0
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    kill -0 "$SERVER_PID" 2>/dev/null || break
    if serves_this_report; then
      SERVED=1
      break
    fi
    sleep 0.1
  done

  if [ "$SERVED" = 0 ]; then
    if kill -0 "$SERVER_PID" 2>/dev/null; then
      kill "$SERVER_PID" 2>/dev/null || true
      echo "ERROR:SERVE_PORT_CONFLICT a server started on port $PORT, but http://localhost:$PORT/$URL_PATH does not return this report; another process is answering on that port. Stop it, then rerun." >&2
    else
      echo "ERROR:SERVE_PORT_FAILED HTTP server failed to start on port $PORT" >&2
      if [ -s "$SERVER_LOG" ]; then
        echo "Last server log:" >&2
        tail -10 "$SERVER_LOG" >&2 || true
      fi
    fi
    rm -f "$PID_FILE"
    exit 1
  fi
fi

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
