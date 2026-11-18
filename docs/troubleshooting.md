# Troubleshooting and local data

## Nothing appears

Run at least one supported source app and create or update a conversation today.
The app reads local data only. A source that has never been installed is empty.
A present but incompatible data schema reports a source error; other sources continue.
The New tab shows running and unreviewed results. Use All to see read and idle sessions.

Antigravity uses `~/.gemini/antigravity/conversation_summaries.db`. A source with only
legacy encrypted `.pb` files is not supported. Its resume action copies the official
`agy --conversation <id>` command; paste it into a terminal with the Antigravity CLI installed.

Windows detects native Windows sessions, not sessions inside WSL. Process information
can be restricted by OS permissions. Do not run the app as administrator just to reveal
another user's sessions.

## App data

- macOS: `~/Library/Application Support/Agent Sessions/`
- Windows: `%APPDATA%\Agent Sessions\`
- Development override: `AGENT_SESSIONS_DATA_DIR`

`favorites.json` stores flagged IDs. `archived.json` stores hidden IDs and known Claude
aliases. Quit the app and remove a specific ID from `archived.json` to restore it locally;
restore in the source app too if source archival succeeded. Back up the file before editing.
macOS review/notification preferences live in the `local.agent-sessions` preferences domain.
Windows preferences use the current user's `Agent Sessions` QSettings registry entry.
Uninstalling intentionally keeps these settings. No source transcripts are deleted.

Source path overrides: `CODEX_HOME`, `CLAUDE_CONFIG_DIR`, `ANTIGRAVITY_HOME`.
The timezone follows the operating system when the process starts; restart after changing it.

## Notifications

Allow Agent Sessions notifications in the operating system. Focus/Do Not Disturb
and Windows notification settings can suppress banners. Existing completed sessions
do not trigger a burst of notifications on first launch. The app never opens its panel
just because a run finishes. Clicking a Windows completion notification opens New.

## Archiving

Local hiding succeeds independently of source availability. Disk or network errors
are reported because local persistence cannot be confirmed. Codex can refuse source
archival while a desktop writer lock is held. Claude source archival requires existing
macOS Accessibility permission; no permission dialog is opened in the background.
Antigravity source archival and Windows Claude source archival are not attempted.

## Updates

Only stable GitHub releases with a matching platform installer are offered. Checks
are cached for six hours; offline/API failures retry later. Updates are downloaded
through GitHub and installed manually. Favorites and archives are outside the app bundle.
If another program owns port 4318, quit it or use `server.py --port <port>` for a web-only
source run. The desktop app expects port 4318.
