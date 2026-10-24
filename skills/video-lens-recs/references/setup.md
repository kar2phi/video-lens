# video-lens-recs — setup

Read this only during setup, a Takeout import, enabling live mode, or a topic refresh.
`recs.py` below means `python3 "SCRIPTS_DIR/recs.py"`, with `SCRIPTS_DIR` from the
`SCRIPTS_DIR:` line. Ask the user one question at a time. Never ask for passwords, and never
copy cookies anywhere.

Open setup with one line on what this conversation will see: the user's subscription list,
and the titles, channels and tags of their video-lens reports. With a hosted model that goes
to its provider; with a local model it stays on this machine.

## 1. Account data — offer three options

**A) Google Takeout import** (the baseline; no credentials, about 5 minutes plus Google's wait):

1. takeout.google.com → *Deselect all* → tick **YouTube and YouTube Music**.
2. *All YouTube data included* → keep **subscriptions** only, untick history.
3. Export, wait for Google's e-mail, download the zip.

Then run `recs.py account import-takeout "<path to the zip or the unpacked folder>"`. It
prints `IMPORTED: N subscriptions`. An `IGNORED:` line means the archive held a history file,
which is never read. Folder names follow the account language; the importer finds the file by
its content.

**B) Live mode** (opt-in). yt-dlp reads the user's logged-in browser session for three things
only:

- current subscriptions, synced at most once a day;
- a recent-watch check: each run reads the IDs of the recent watches (about 40 per day of its
  window, at most 600), drops the candidates the user has watched, and forgets the IDs when it
  exits. Only a video the skill showed earlier is recorded as watched. No history file is
  ever written;
- the YouTube home feed, as one more candidate source.

So each run makes two signed-in reads, each a few paged requests, plus the daily sync; "next"
reuses the run and reads nothing. Tell the user plainly:
yt-dlp's documentation warns that using an account with yt-dlp can get it temporarily or
permanently suspended. Low volume keeps the risk small, but it is theirs to take.

Run `recs.py account live --browser firefox` (or `firefox:<profile name>`, `chrome`, `brave`,
`edge`, `safari`). Browser notes:

- **macOS + Firefox:** recent macOS versions block other apps from reading Firefox's profile.
  If you see `COOKIES_UNREADABLE` ("could not find firefox cookies database"), the user must
  give their terminal app **Full Disk Access** (System Settings → Privacy & Security → Full
  Disk Access), restart the terminal, and rerun.
- **Chrome, Brave, Edge** on macOS ask once for Keychain access ("Chrome Safe Storage").
- **Safari** needs Full Disk Access for the terminal.
- **Linux:** Firefox and Chrome work as they are.

On `ERROR:LIVE_SYNC_FAILED`, relay its hint; the account mode stays as it was.
`recs.py account probe` checks what live mode can read and prints only counts.
`recs.py account off` turns live mode off.

**C) Skip.** Start with channels the user names (`recs.py topics add-channel KEY @handle`),
the channels of their video-lens library, and topic searches.

## 2. Topics

Run `recs.py topics propose`. It takes up to a minute for many channels and prints:

- `LIBRARY_TAGS`: the most common report tags, with counts;
- `LIBRARY_LANGUAGES`: the languages of the user's reports;
- one line per subscribed or often-summarised channel: id, title, whether subscribed, its
  reports and their tags, and 3 recent video titles;
- `PROPOSAL_PATH`: where to write your proposal.

Group the channels into **4–8 topics** and `Write` this JSON to `PROPOSAL_PATH`:

```json
{
  "languages": ["en"],
  "topics": {
    "ai": {
      "label": "AI & agents",
      "channels": ["UCxxxxxxxxxxxxxxxxxxxxxx"],
      "queries": ["ai agents", "agent evals"],
      "keywords": ["agent", "llm", "evals"],
      "exclude_keywords": ["giveaway"],
      "report_tags": ["ai", "ai agents", "llm"]
    },
    "news": {"label": "News", "channels": ["UCyyyyyyyyyyyyyyyyyyyyyy"], "queries": [], "window_days": 2,
             "report_tags": ["news"]}
  }
}
```

Rules:

- Base the topics on clusters in `LIBRARY_TAGS` and on the channels' recent titles.
- `channels`: only `UC…` ids from the propose output. A channel may be in at most 2 topics.
  Leave off-topic channels (music, gaming, one-offs) unassigned.
- `queries`: 2–5 YouTube searches that find good videos outside the subscriptions. Use none
  for news topics: news is time-critical, so channels only, and `window_days` 1–2.
- `keywords`: 3–8 words or short phrases that mark a relevant title.
- `report_tags`: tags from `LIBRARY_TAGS` that define this topic in the library. They select
  the taste profile.
- `languages`: the language codes `LIBRARY_LANGUAGES` shows with a real share, e.g.
  `["en", "de"]`. Only search results and home-feed videos are filtered by language.

Show the user a short table (key · label · number of channels · queries) and ask them to
confirm or change it. Then run `recs.py topics apply "PROPOSAL_PATH"`. On `ERROR:TOPICS_*`, fix
what it names, re-`Write` the file and apply again.

For "refresh my topics", `recs.py topics propose --refresh` lists only unassigned channels,
recent tags no topic covers, and channels the user no longer subscribes to. Write a proposal
with only the topics that change, and apply it (topics not in the file are kept).

## 3. First run

Suggest a first request built from the new topics, e.g. "what's new in AI this week", and run
the main pipeline (SKILL.md Step 1).

## Optional extras

- **YouTube Data API key** (better search filters, exact counts):
  1. console.cloud.google.com → create a project → enable **YouTube Data API v3** →
     Credentials → *Create API key* (restrict it to that API).
  2. Add `export YOUTUBE_API_KEY=…` to the shell profile. To use another variable, set
     `sources.api_key_env` in `~/.config/video-lens/recs.json`.
  3. The free quota is 10,000 units a day for list calls, plus 100 search calls a day. A run
     uses at most 5 searches per topic and prints what it spent. Without a key, or once the
     quota is used up, search falls back to yt-dlp.
- **Channel ids for older reports:** the gallery's
  `backfill_meta.py --dir ~/Downloads/video-lens --channel-ids --lookup` adds channel ids to
  reports made before video-lens stored them. Channel matching then no longer depends on
  names.
- **Summarize button:** when the video-lens Raycast script is installed
  (`task install-raycast`), the Discover page's *Summarize* opens it through a Raycast
  deeplink. Otherwise it copies `/video-lens <url>` to paste into the agent. Set
  `"ui": {"raycast_summarize": false}` to always copy.
