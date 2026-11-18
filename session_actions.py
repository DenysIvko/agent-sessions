"""Explicit session actions, delegated to the installed source applications."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

UUID = r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"


def archive_session(session):
    if session.get("running") or session.get("agents"):
        raise ValueError("Wait for this session and its agents to finish before archiving.")
    sid = session["id"]
    if session.get("source") == "codex" and re.fullmatch(UUID, sid):
        executable = shutil.which("codex")
        if not executable:
            candidate = Path.home() / ".local/bin/codex"
            executable = str(candidate) if os.access(candidate, os.X_OK) else None
        if not executable:
            raise RuntimeError("Install the Codex CLI to archive Codex sessions.")
        result = subprocess.run([executable, "archive", sid], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=25)
        if result.returncode:
            raise RuntimeError("Codex could not archive this session. " + result.stderr.strip()[-500:])
        return "Archived in Codex."
    if session.get("source") == "claude" and re.fullmatch(rf"claude:(?:local_)?{UUID}", sid):
        if sys.platform == "win32":
            raise RuntimeError("Claude Code source archival is unavailable on Windows; the local archive is saved.")
        helper = Path(os.environ.get("AGENT_SESSIONS_NATIVE_HELPER", Path(__file__).resolve().parent.parent.parent / "MacOS/AgentSessions"))
        if not helper.is_file():
            helper = Path.home() / "Applications/Agent Sessions.app/Contents/MacOS/AgentSessions"
        if not helper.is_file():
            raise RuntimeError("Install Agent Sessions to archive conversations in Claude Code.")
        result = subprocess.run([str(helper), "--archive-claude", sid.removeprefix("claude:")],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=25)
        try:
            reply = json.loads(result.stdout)
        except ValueError as error:
            raise RuntimeError("Claude Code did not confirm the archive action. Open the session to check it.") from error
        if not reply.get("ok"):
            raise RuntimeError(reply.get("message", "Could not archive in Claude Code."))
        return reply["message"]
    raise ValueError("Invalid session identifier.")
