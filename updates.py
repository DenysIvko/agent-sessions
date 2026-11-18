"""Check GitHub Releases without sending session data or executing downloads."""

import json
import platform
import re
import sys
import threading
import time
from urllib.request import Request, urlopen

from app_config import REPOSITORY, VERSION

RELEASE_URL = f"https://github.com/{REPOSITORY}/releases"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+", value):
        raise ValueError("Expected a stable semantic version")
    return tuple(map(int, value.removeprefix("v").split(".")))


def release_update(release, current=VERSION, system=sys.platform, machine=platform.machine()):
    result = {"currentVersion": current, "available": False, "releaseURL": RELEASE_URL}
    if release.get("draft") or release.get("prerelease"):
        return result
    tag = release.get("tag_name", "")
    if version_tuple(tag) <= version_tuple(current):
        return result
    asset = "Agent-Sessions-Windows-x64-Setup.exe" if system == "win32" else (
        "Agent-Sessions-macOS-arm64.dmg" if machine.lower() in ("arm64", "aarch64") else "Agent-Sessions-macOS-x64.dmg")
    for item in release.get("assets", []):
        url = item.get("browser_download_url", "")
        if item.get("name") == asset and url == f"{RELEASE_URL}/download/{tag}/{asset}":
            return {**result, "available": True, "version": tag.removeprefix("v"), "downloadURL": url,
                    "releaseURL": f"{RELEASE_URL}/tag/{tag}"}
    return result


class UpdateChecker:
    def __init__(self):
        self.lock = threading.Lock()
        self.checked_at = 0
        self.result = {"currentVersion": VERSION, "available": False, "releaseURL": RELEASE_URL}

    def check(self):
        with self.lock:
            if time.time() - self.checked_at < 6 * 60 * 60:
                return self.result
            try:
                request = Request(API_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": f"Agent-Sessions/{VERSION}"})
                with urlopen(request, timeout=8) as response:
                    release = json.loads(response.read(2 * 1024 * 1024))
                self.result = release_update(release)
                self.checked_at = time.time()
            except (OSError, ValueError, TypeError):
                # A missing first release, offline GitHub, or a rate limit never blocks session tracking.
                self.checked_at = time.time() - 5 * 60 * 60
            return self.result


checker = UpdateChecker()
