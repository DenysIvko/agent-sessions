#!/usr/bin/env python3
"""Build, check, and optionally install the native menu bar app on this Mac."""

import argparse
import platform
import plistlib
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
APP = BUILD / "Agent Sessions.app"
IDENTIFIER = "local.agent-sessions"


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True, cwd=ROOT)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Install in ~/Applications")
    parser.add_argument("--bundle-backend", action="store_true", help="Include Python and all runtime dependencies")
    args = parser.parse_args()
    BUILD.mkdir(exist_ok=True)
    run(sys.executable, ROOT / "scripts/configure_analytics.py")
    native = ROOT / "macos"
    common = ["xcrun", "swiftc", "-swift-version", "5", "-target", f"{platform.machine()}-apple-macosx13.0",
              "-module-cache-path", BUILD / "ModuleCache"]
    run(*common, native / "SessionMonitor.swift", native / "TrayViewController.swift", native / "MonitorTests.swift",
        "-framework", "AppKit", "-o", BUILD / "MonitorTests")
    run(BUILD / "MonitorTests")
    contents = APP / "Contents"
    (contents / "MacOS").mkdir(parents=True, exist_ok=True)
    resources = contents / "Resources"
    resources.mkdir(exist_ok=True)
    run(*common, "-O", native / "SessionMonitor.swift", native / "TrayViewController.swift", native / "ClaudeArchive.swift", native / "AgentSessions.swift",
        "-framework", "AppKit", "-framework", "UserNotifications",
        "-o", contents / "MacOS/AgentSessions")
    info = plistlib.loads((native / "Info.plist").read_bytes())
    info["CFBundleShortVersionString"] = (ROOT / "VERSION").read_text().strip()
    info["CFBundleVersion"] = info["CFBundleShortVersionString"]
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    dashboard = resources / "dashboard"
    if dashboard.exists():
        shutil.rmtree(dashboard)
    dashboard.mkdir()
    for file in ["server.py", "claude_sessions.py", "antigravity_sessions.py", "session_actions.py", "processes.py", "app_config.py", "updates.py", "demo.py", "product_analytics.py", "analytics-config.json", "VERSION"]:
        shutil.copy2(ROOT / file, dashboard / file)
    shutil.copytree(ROOT / "public", dashboard / "public")
    if args.bundle_backend:
        run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--name", "agent-sessions-server",
            "--distpath", BUILD / "frozen", "--workpath", BUILD / "pyinstaller", "--specpath", BUILD,
            "--add-data", f"{ROOT / 'public'}:public", "--add-data", f"{ROOT / 'VERSION'}:.",
            "--add-data", f"{ROOT / 'analytics-config.json'}:.",
            "--collect-data", "tzdata", ROOT / "server.py")
        if (resources / "backend").exists():
            shutil.rmtree(resources / "backend")
        shutil.copytree(BUILD / "frozen/agent-sessions-server", resources / "backend")
        run(sys.executable, ROOT / "scripts/collect_licenses.py", resources / "licenses")
        shutil.copy2(ROOT / "LICENSE", resources / "LICENSE")
        shutil.copy2(ROOT / "THIRD_PARTY_NOTICES.md", resources / "THIRD_PARTY_NOTICES.md")
    run(*common, native / "MakeIcon.swift", "-framework", "AppKit", "-o", BUILD / "MakeIcon")
    run(BUILD / "MakeIcon", BUILD / "AppIcon.iconset")
    run("iconutil", "-c", "icns", BUILD / "AppIcon.iconset", "-o", resources / "AppIcon.icns")
    run("plutil", "-lint", contents / "Info.plist")
    run("codesign", "--force", "--deep", "--sign", "-", "--identifier", IDENTIFIER, "--timestamp=none", APP)
    run("codesign", "--verify", "--deep", "--strict", APP)
    destination = APP
    if args.install:
        destination = Path.home() / "Applications/Agent Sessions.app"
        destination.parent.mkdir(exist_ok=True)
        if destination.exists():
            with (destination / "Contents/Info.plist").open("rb") as stream:
                if plistlib.load(stream).get("CFBundleIdentifier") != IDENTIFIER:
                    raise SystemExit(f"Refusing to replace an unrelated app at {destination}")
            shutil.rmtree(destination)
        shutil.copytree(APP, destination)
        run("codesign", "--verify", "--deep", "--strict", destination)
    print(f"Ready: {destination}")


if __name__ == "__main__":
    main()
