#!/usr/bin/env bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title video-lens
# @raycast.mode silent
# @raycast.argument1 {"type": "text", "placeholder": "YouTube URL (leave blank to use clipboard)", "optional": true}
# @raycast.argument2 {"type": "text", "placeholder": "Model (optional — e.g. opus, sonnet; blank uses the CLI default)", "optional": true}

# Optional parameters:
# @raycast.icon 📺
# @raycast.packageName iTerm

# Documentation:
# @raycast.description Summarise a YouTube video — opens Claude in iTerm2 and launches the HTML report in the browser

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

osascript - "$ytURL" "$HOME/Downloads" "$2" <<'EOF'
on run argv
  set ytURL to item 1 of argv
  set outputDir to item 2 of argv
  set modelInput to item 3 of argv
  -- Pass the model through verbatim; blank means "whatever the CLI is configured
  -- to use". Pinning IDs here only creates a standing maintenance tax.
  if modelInput is "" then
    set modelArg to ""
  else
    set modelArg to "--model " & quoted form of modelInput
  end if
  set cmd to "cd " & quoted form of outputDir & " && claude --dangerously-skip-permissions --allowedTools \"Bash,Read\" " & modelArg & " \"/video-lens " & ytURL & "\""

  if application "iTerm2" is running or (exists application "iTerm2") then
    tell application "iTerm2"
      activate

      if (count of windows) = 0 then
        set newWindow to (create window with default profile)
        tell current session of newWindow
          write text cmd
        end tell
      else
        tell current window
          create tab with default profile
          tell current session
            write text cmd
          end tell
        end tell
      end if

    end tell
  else
    tell application "Terminal"
      activate
      do script cmd
    end tell
  end if
end run
EOF
