Agent Sessions 0.3.0 adds anonymous product analytics with PostHog.

- Usage events are enabled by default. Open Privacy in the dashboard or Usage Analytics in the tray menu to turn them off for this device.
- Explicit events cover dashboard and tray usage, favorites, archiving, opening sessions, the tutorial, notifications and updates.
- Coverage includes failed actions, separate source archive outcomes, source-read health changes, manual review, tutorial steps, fixed filter choices and update-check results. macOS notification opens share the regular session-open tracking path.
- Session contents, titles, IDs, project names, paths, search text and credentials stay out of analytics. There is no session recording or automatic interaction capture.
- The preference persists across restarts and upgrades. Disabling it discards queued events; an upload already in progress may finish.

Existing favorites, archives and review state are preserved. Demo mode and unconfigured builds send no usage events.

These are unsigned preview builds. They are not notarized by Apple or signed with a trusted Windows publisher certificate. OS security warnings may appear. Checksums are provided in SHA256SUMS.txt.

Antigravity App 2.x metadata is supported; opening copies its official CLI resume command. WSL and older protobuf-only Antigravity IDE storage are not supported. Source formats are internal and may change.
