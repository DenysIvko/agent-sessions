"""Read Antigravity App 2.x conversation metadata from its local summary index."""

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import unquote, urlsplit

from app_config import TIMEZONE
from processes import matching_processes

ANTIGRAVITY = Path(os.environ.get("ANTIGRAVITY_HOME", Path.home() / ".gemini/antigravity"))
UUID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")


def timestamp(value):
    if not value:
        return 0
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def read_sessions(now, root=ANTIGRAVITY, include_ids=(), live=None):
    database = root / "conversation_summaries.db"
    if not database.exists():
        return []
    live = any(matching_processes("antigravity")) if live is None else live
    today = datetime.fromtimestamp(now, TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    start, end = today.timestamp(), (today + timedelta(days=1)).timestamp()
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute("""SELECT conversation_id, title, step_count, last_modified_time,
            workspace_uris, status, project_id, parent_conversation_id, not_fully_idle,
            killed, last_user_input_time FROM conversation_summaries""").fetchall()
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        archived = {r[0] for r in connection.execute(
            "SELECT DISTINCT conversation_id FROM conversations_fts WHERE archived = 1"
        )} if "conversations_fts" in tables else set()
    finally:
        connection.close()
    sessions = []
    for row in rows:
        sid = row["conversation_id"]
        if not UUID.fullmatch(sid) or sid in archived or row["parent_conversation_id"]:
            continue
        active = row["not_fully_idle"] or row["status"] in ("CASCADE_RUN_STATUS_RUNNING", "CASCADE_RUN_STATUS_PENDING")
        running = bool(live and active and not row["killed"])
        modified, started = timestamp(row["last_modified_time"]), timestamp(row["last_user_input_time"])
        activity = now if running else max(modified, started)
        is_today = start <= activity < end
        if not is_today and f"antigravity:{sid}" not in include_ids:
            continue
        status = "inProgress" if running else "interrupted" if row["killed"] else (
            "failed" if row["status"] == "CASCADE_RUN_STATUS_ERROR" else
            "completed" if not active and row["status"] == "CASCADE_RUN_STATUS_IDLE" and row["step_count"] else None)
        workspaces = json.loads(row["workspace_uris"]) if row["workspace_uris"] else []
        if not isinstance(workspaces, list) or not all(isinstance(uri, str) for uri in workspaces):
            raise ValueError("Unexpected Antigravity workspace metadata")
        workspace = unquote(urlsplit(workspaces[0]).path).rstrip("/") if workspaces else ""
        project = workspace.replace("\\", "/").rsplit("/", 1)[-1] or "No project"
        sessions.append({
            "id": f"antigravity:{sid}", "sessionId": sid, "source": "antigravity",
            "title": row["title"] or "Untitled Antigravity session", "project": project,
            "projectId": row["project_id"] or f"workspace:{workspace}", "model": "", "branch": "",
            "kind": "Chat", "running": running, "status": status, "unread": None,
            "activityAt": activity, "updatedAt": modified, "isToday": is_today,
            "startedAt": started or None, "endedAt": modified if status in ("completed", "failed", "interrupted") else None,
            "turnId": str(started), "agents": 0, "url": None, "resumeCommand": f"agy --conversation {sid}",
        })
    return sessions
