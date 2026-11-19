# Product analytics

Agent Sessions uses PostHog Product Analytics, with the official Python SDK in the
local backend. Collection is enabled by default in configured 0.3.0+ builds. Open
**Privacy** in the dashboard, or **Usage Analytics** in either tray menu, to turn it off.
The preference is stored with the app's local data and shared by all its interfaces.
It survives restarts and upgrades. If an existing preference cannot be read, collection
stays off until the user explicitly changes it.

## Data sent

Every event has a random installation ID, event time, app version, operating system
(`macos`, `windows`, or `linux`), and origin (`web`, `tray`, or `backend`). The random ID measures
repeat usage without linking a coding account or conversation. Reinstalling preserves it.

| Event | Additional properties | Meaning |
| --- | --- | --- |
| `app_opened` | None | Tray received its first healthy backend response |
| `dashboard_opened` | None | Web dashboard loaded |
| `tray_opened` | None | Tray panel opened |
| `view_selected` | `view`: new, all, favorites | User selected a collection |
| `filter_used` | `filter`, `selection` | Fixed source/status/type choice, or applied/cleared/selected for search/project; never query text or project identity |
| `session_open_requested` | `source`: codex, claude, antigravity; `method`: link, copy | Opening was requested, not proof the source app opened |
| `session_open_result` | `source`, `method`, `result`: accepted, copied, manual_copy, failed, unavailable | Native OS handoff or clipboard result; manual_copy means the browser showed its fallback prompt |
| `session_reviewed` | `source`, `method`: manual, open, copy, notification | Local review action; manual review is available in the Mac context menu |
| `favorite_changed` | `source`, `enabled` | Favorite was saved locally |
| `session_archived` | `source` | Session was hidden locally, not proof of source archival |
| `action_failed` | `source`, `action`: favorite, archive; `reason`: timeout, request_failed | Client did not receive confirmation; a timed-out operation may still finish |
| `source_status_changed` | `source`, `status`: data, empty, error | Backend reader's initial state and changes; empty means no eligible sessions, not proof an app is uninstalled |
| `source_archive_result` | `source`, `result`: completed, failed, skipped_running, skipped_unavailable, unsupported | Separate background source archive outcome; completed means the helper/CLI confirmed it |
| `navigation_requested` | `destination`: dashboard, tutorial, privacy, notification_settings | Intent to open a destination; no URL is sent |
| `tutorial_started` | `entry`: first_run, help, link | Tour opened automatically, from Help, or from an explicit tour link |
| `tutorial_step_viewed` | `step`: 1-7; `direction`: start, next, back | Step became visible; does not measure time spent reading |
| `tutorial_completed` | None | User clicked Done |
| `tutorial_dismissed` | `step`: 1-7 | Tour closed before Done |
| `notification_requested` | `kind`: completion, update, test | App requested an OS notification, not proof of a visible banner |
| `notification_clicked` | None | User activated a notification |
| `notifications_toggled` | `enabled` | Completion notification preference changed |
| `notification_permission_changed` | `permission`: allowed, denied, not_determined, provisional, unknown | macOS permission initially observed and changes; Windows Qt does not expose this |
| `notification_send_result` | `kind`: completion, update, test; `result`: accepted, failed | macOS notification API callback, not proof of a visible banner; Windows Qt has no equivalent callback |
| `update_available` | None | Tray discovered a newer release |
| `update_check_requested` | `trigger`: manual, automatic | Tray requested an update check; GitHub results may come from the local cache |
| `update_check_result` | `trigger`, `result`: available, current, failed | Failed network checks are not reported as up-to-date |
| `update_download_requested` | None | User opened an installer download link, not proof of installation |

The backend rejects unknown events, extra properties and free-text values. It strips
SDK context enrichment before upload. No session IDs, titles, contents, prompts, model
output, project names, branch names, paths, search text, credentials or error messages
are sent. Repeated healthy source polls do not emit events. No frontend PostHog script, autocapture, session replay,
feature flag fetch or exception capture is enabled.

Person profile processing and GeoIP enrichment are disabled. Events override the IP
property with `0.0.0.0`; the PostHog project's IP capture setting should also be disabled.
Like any HTTPS service, PostHog's network infrastructure receives the connection's IP.
The application does not attach it as an analytics property.

Events use a bounded memory queue, without a disk backlog. Turning collection off
discards queued events; an upload already in progress may finish. Previously uploaded
events remain in PostHog. Offline failures are dropped without retrying or interrupting
session actions. Demo mode never creates an analytics identity or sends events.

## Coverage and interpretation

- Web, Mac and Windows cover their available tabs, filters, favorite/archive actions,
  session openings, Help/Privacy navigation and update controls. The Mac notification
  opening path emits the same session-open events as clicking a session row.
- Search emits on editing completion or clear, not on every keystroke or repeated focus.
  Source/status/type selections use a fixed enum. Project selection and search retain
  only selected/applied/cleared labels.
- Browser deep links cannot confirm that another application opened, so they emit only
  a request. Native `accepted` means the OS accepted the handoff; it does not prove a
  conversation loaded. Copying a command does not prove it was pasted or run.
- Local favorites and archives emit success only after confirmation. Source archive
  failures still leave the session hidden locally. Backend outcomes have `surface=backend`
  and do not identify which UI initiated the operation.
- Notifications that are denied, hidden by Focus, or dismissed without clicking cannot
  be counted as visible or read. Windows does not invent a notification delivery result.
- Privacy visits respect the existing sharing preference. Switching analytics off sends
  no opt-out event and does not create a tracking exception. Never derive an opt-out rate
  by interpreting silence as a deliberate preference change.
- Backend failures may prevent even the failure event from reaching the local collector.
  This is best-effort product analytics, not a crash reporting or audit log system.
- No events are emitted for hovers, scrolling, dismissing an error toast, individual
  keystrokes, background refreshes, or quitting. No timing/CPU metrics or recordings run.

## Maintainer setup

1. Create an EU PostHog project on the Free plan. Keep autocapture, heatmaps, web vitals
   and session replay disabled. Disable IP capture in project settings.
2. Set the GitHub Actions secret `POSTHOG_PROJECT_KEY` to the **public project token**
   and repository variable `POSTHOG_HOST` to `https://eu.i.posthog.com`.
3. Packaging generates ignored `analytics-config.json` and bundles it into the app.
   Never use a personal API key or project secret key here. The ingestion token is
   public client configuration and can be extracted from installers; it cannot read data.
4. For local development, supply the same environment variables, or an ignored
   `analytics-config.json` with `key` and `host`. Without configuration, the app remains
   fully functional and sends no events. Fork PRs without access to secrets stay unconfigured.
5. Check a disposable installation in PostHog's Activity view. Confirm the exact event
   properties, then turn sharing off and verify further interactions produce no events.

Recommended dashboard:

- Daily engaged installations and retention: unique IDs across `app_opened`,
  `dashboard_opened`, `tray_opened`, `view_selected`, `filter_used`,
  `session_open_requested`, `favorite_changed`, `session_archived`, `session_reviewed`,
  `navigation_requested`, `tutorial_started`, `tutorial_step_viewed`,
  `notification_clicked`, `notifications_toggled`, and `update_download_requested`.
  Do not count source polling, notification requests, permission snapshots or automatic
  update checks as user engagement. Leaving the app open overnight is not engagement.
- Feature totals and source usage, with platform/version and web/tray breakdowns.
- Tutorial funnel: `tutorial_started` -> `tutorial_completed`; inspect step and entry
  properties to locate abandonment. First-seen IDs describe first observed use, not
  confirmed software installations.
- Action reliability: compare `favorite_changed` and `session_archived` against
  `action_failed` by action/source; inspect `session_open_result` by method/result.
- Source health: `source_status_changed` by source/status and `source_archive_result`
  by source/result. These count observations and transitions, not outage duration.
- Update checks by trigger/result, and notification requests/clicks plus the available
  macOS permission/send results. Downloads are requests, not completed upgrades.

Installation counts are devices, not people; one person can use several devices. A web
refresh counts as another dashboard opening. Aggregate unique IDs when measuring adoption.
