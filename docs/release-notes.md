Agent Sessions 0.3.1 fixes a macOS startup crash that could make the menu bar icon disappear.

- The New tab is selected before startup notification callbacks can read the tray state. Previously, a callback arriving before the first dashboard snapshot could read an unselected tab and terminate the app.
- A native regression test reads the tray status before its panel loads, matching the failing startup order.

Existing favorites, archives, review state and analytics preferences are preserved.

These are unsigned preview builds. They are not notarized by Apple or signed with a trusted Windows publisher certificate. OS security warnings may appear. Checksums are provided in SHA256SUMS.txt.

Antigravity App 2.x metadata is supported; opening copies its official CLI resume command. WSL and older protobuf-only Antigravity IDE storage are not supported. Source formats are internal and may change.
