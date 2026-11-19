# Releasing Agent Sessions

1. Change `VERSION` to a new stable `MAJOR.MINOR.PATCH` on a feature branch.
2. Update `docs/release-notes.md`, documentation, and screenshots as needed.
3. Open a pull request. Wait for Mac ARM64, Mac x64, and Windows builds/tests.
4. Review the three downloadable installer artifacts. The maintainer merges the PR.
5. The main-branch release workflow builds the merged source, creates `vX.Y.Z`,
   uploads all three installers plus `SHA256SUMS.txt`, and publishes the release.
6. The Pages workflow deploys changes in `site/` from main. The site resolves the latest
   public release automatically. Existing installations discover it within six hours.

The release workflow rejects non-main dispatches and never replaces an existing version.
For a failed first run, fix the problem in a PR and rerun Release from main. Do not publish
installers from an unmerged branch. Preview artifacts on PRs are for review only.

## Signing

The initial pipeline produces **unsigned preview installers**, with ad-hoc signing for
local Mac integrity. Ad-hoc signing is not Developer ID signing or notarization.
A trusted publisher release requires an Apple Developer ID Application identity,
Apple notarization credentials, and a Windows Authenticode signing certificate or service.
Keep signing keys in protected CI secrets or a signing service, never in the repository.

Before distributing signed releases, add certificate-backed signing after packaging
and before checksum generation, notarize/staple Mac disk images, and verify both Mac
Gatekeeper assessment and Windows Authenticode signature status. Update the preview
wording only after those checks pass. Signing credentials are not bundled or generated
by the application.

## Reproducing packages

Install `requirements-build.txt` on a matching architecture and run
`python scripts/package_macos.py`. Native tests run as part of that command.
Windows additionally needs `requirements-windows.txt` and Inno Setup 6. Run
`python scripts/package_windows.py`, then `ISCC.exe windows/installer.iss`.
Python is bundled by PyInstaller. No Python installation is required on a target machine.
CI uses Python 3.13, with exact package versions in the requirements files.

Configure `POSTHOG_PROJECT_KEY` and `POSTHOG_HOST` before packaging official 0.3.0+
builds. These are injected into ignored client configuration during packaging; only
the public ingestion token is bundled. Tests and demo mode do not send events, even
when a token is configured. See [analytics setup](analytics.md).

## Screenshots

Use `python server.py --demo --port 4319` and capture the actual dashboard.
The demo is read-only and contains fictional sessions. Never publish the normal
port 4318 view. Windows CI can render `python windows/check_ui.py --screenshot <path>`
offscreen using the actual tray controls. Keep public images in `site/assets/`.

On Windows, offscreen screenshot rendering needs system fonts explicitly:

```powershell
$env:QT_QPA_FONTDIR = Join-Path $env:SystemRoot "Fonts"
python windows/check_ui.py --screenshot site/assets/tray.png
```
