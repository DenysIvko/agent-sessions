"""Shared product metadata and platform-specific locations."""

import os
from pathlib import Path
import sys

from tzlocal import get_localzone

ROOT = Path(__file__).resolve().parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
REPOSITORY = "DenysIvko/agent-sessions"
TIMEZONE = get_localzone()


def support_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


DATA_DIR = Path(os.environ.get("AGENT_SESSIONS_DATA_DIR", support_dir() / "Agent Sessions"))
