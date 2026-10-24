#!/usr/bin/env bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title video-lens
# @raycast.mode silent
# @raycast.argument1 {"type": "text", "placeholder": "YouTube URL (leave blank to use clipboard)", "optional": true}
# @raycast.argument2 {"type": "text", "placeholder": "Model (optional — e.g. opus, sonnet; blank = claude-haiku-5-5)", "optional": true}

# Optional parameters:
# @raycast.icon 📺
# @raycast.packageName cmux

# Documentation:
# @raycast.description Summarise a YouTube video — opens Claude in cmux and launches the HTML report in the browser

ytURL="$1"
if [[ -z "$ytURL" ]]; then
  ytURL="$(pbpaste)"
fi

# Mirrors preflight.py's YOUTUBE_HOSTS — m.youtube.com is what the iOS share sheet emits.
if [[ ! "$ytURL" =~ ^https?://((www|m)\.)?(youtube\.com|youtu\.be)/ ]]; then
  osascript -e "display dialog \"Invalid YouTube URL: $ytURL\" buttons {\"OK\"} default button 1"
  exit 1
fi

ytURL="$(printf '%s' "$ytURL" | tr -dc 'A-Za-z0-9/:?=&._%-')"

# `tell application "cmux"` below only compiles when the app is installed.
if ! open -Ra cmux 2>/dev/null; then
  osascript -e 'display dialog "cmux is not installed (https://cmux.com)." buttons {"OK"} default button 1'
  exit 1
fi

# Blank model argument means Haiku 5.5. install-raycast blanks this default for the
# non-Claude agents, whose CLIs don't know that ID.
model="${2:-claude-haiku-5-5}"

# stdout is dropped: Raycast shows a silent script's last output line as a toast, and
# AppleScript would print "true" (the result of the Enter keystroke below).
osascript - "$ytURL" "$HOME/Downloads" "$model" >/dev/null <<'EOF'
on run argv
  set ytURL to item 1 of argv
  set outputDir to item 2 of argv
  set modelInput to item 3 of argv
  -- Pass the model through verbatim; a blank one (non-Claude agents) means "whatever
  -- the CLI is configured to use".
  if modelInput is "" then
    set modelArg to ""
  else
    set modelArg to "--model " & quoted form of modelInput
  end if
  set cmd to "cd " & quoted form of outputDir & " && claude --dangerously-skip-permissions --allowedTools \"Bash,Read,Write\" " & modelArg & " \"/video-lens " & ytURL & "\""

  tell application "cmux"
    activate
    -- Cold start: the first window takes a moment to appear.
    repeat 50 times
      if (count of windows) > 0 then exit repeat
      delay 0.2
    end repeat
    if (count of windows) = 0 then new window

    -- Always a fresh workspace: never type into a terminal that is already in use.
    set ws to new tab
    select tab ws
    set term to focused terminal of ws
    -- Let the shell come up. The workspace inherits the previous one's directory,
    -- which is why cmd starts with a cd.
    delay 0.5
    -- input text pastes, and a pasted newline does not run the line; send Enter separately.
    input text cmd to term
    perform action "text:\\r" on term
  end tell
end run
EOF
