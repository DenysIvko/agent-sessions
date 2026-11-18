# Product analytics

Agent Sessions uses PostHog Product Analytics, with the official Python SDK in the
local backend. Collection is enabled by default in configured 0.3.0+ builds. Open
**Privacy** in the dashboard, or **Usage Analytics** in either tray menu, to turn it off.
The preference is stored with the app's local data and shared by all its interfaces.
It survives restarts and upgrades. If an existing preference cannot be read, collection
stays off until the user explicitly changes it.

## Data sent

Every event has a random installation ID, event time, app version, operating system
(`macos`, `windows`, or `linux`), and interface (`web` or `tray`). The random ID measures
repeat usage without linking a coding account or conversation. Reinstalling preserves it.

| Event | Additional properties | Meaning |
| --- | --- | --- |
| `app_opened` | None | Tray received its first healthy backend response |
| `dashboard_opened` | None | Web dashboard loaded |
| `tray_opened` | None | Tray panel opened |
| `view_selected` | `view`: new, all, favorites | User selected a collection |
| `filter_used` | `filter`: source, project, status, type, search, clear | A filter was used; its value is never sent |
| `session_open_requested` | `source`: codex, claude, antigravity; `method`: link, copy | Opening was requested, not proof the source app opened |
| `favorite_changed` | `source`, `enabled` | Favorite was saved locally |
| `session_archived` | `source` | Session was hidden locally, not proof of source archival |
| `tutorial_started` | None | Tour opened |
| `tutorial_completed` | None | User clicked Done |
| `tutorial_dismissed` | `step`: 1-7 | Tour closed before Done |
| `notification_requested` | `kind`: completion, update, test | App requested an OS notification, not proof of a visible banner |
| `notification_clicked` | None | User activated a notification |
| `notifications_toggled` | `enabled` | Completion notification preference changed |
| `update_available` | None | Tray discovered a newer release |
| `update_download_requested` | None | User opened an installer download link, not proof of installation |

The backend rejects unknown events, extra properties and free-text values. It strips
SDK context enrichment before upload. No session IDs, titles, contents, prompts, model
output, project names, branch names, paths, search text, credentials or error messages
are sent. Polling is not tracked. No frontend PostHog script, autocapture, session replay,
feature flag fetch or exception capture is enabled.

Person profile processing and GeoIP enrichment are disabled. Events override the IP
property with `0.0.0.0`; the PostHog project's IP capture setting should also be disabled.
Like any HTTPS service, PostHog's network infrastructure receives the connection's IP.
The application does not attach it as an analytics property.

Events use a bounded memory queue, without a disk backlog. Turning collection off
discards queued events; an upload already in progress may finish. Previously uploaded
events remain in PostHog. Offline failures are dropped without retrying or interrupting
session actions. Demo mode never creates an analytics identity or sends events.

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

Recommended dashboard: daily active installations using unique `dashboard_opened` and
`app_opened` IDs, feature event totals, platform/version breakdowns, source usage from
`session_open_requested`, and the `tutorial_started` to `tutorial_completed` funnel.
Installation counts are devices, not people; one person can use several devices. A web
refresh counts as another dashboard opening. Aggregate unique IDs when measuring adoption.
