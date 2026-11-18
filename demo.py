"""Fictional sessions for public screenshots. Never reads a user's source apps."""

from datetime import datetime
import time
from app_config import TIMEZONE, VERSION


def snapshot(now=None):
    now = now or time.time()
    examples = [
        ("codex", "Ship the new checkout flow", "Storefront", True, False),
        ("antigravity", "Build a faster image pipeline", "Studio", True, False),
        ("claude", "Add keyboard shortcuts", "Workspace", False, True),
        ("codex", "Fix the timezone edge case", "Calendar", False, True),
        ("antigravity", "Review API error handling", "Backend", False, False),
        ("claude", "Polish the onboarding screens", "Workspace", False, False),
    ]
    rows = []
    for i, (source, title, project, running, favorite) in enumerate(examples):
        rows.append({"id": f"demo-{i}", "source": source, "title": title, "project": project,
            "projectId": project.lower(), "model": "", "branch": "feat/improvements", "kind": "Chat",
            "running": running, "unread": not running, "favorite": favorite, "isToday": True,
            "activityAt": now - i * 240, "updatedAt": now - i * 240,
            "status": "inProgress" if running else "completed", "startedAt": now - 1200 - i * 60,
            "endedAt": None if running else now - i * 240, "turnId": f"demo-turn-{i}", "agents": 0,
            "url": None, "resumeCommand": "# Demo session - no source conversation"})
    return {"service": "agent-sessions", "version": VERSION, "schemaVersion": 1, "sourceErrors": {},
            "scope": "Demo data", "date": datetime.fromtimestamp(now, TIMEZONE).date().isoformat(),
            "timezone": str(TIMEZONE), "checkedAt": now, "sessions": rows,
            "favoriteSessions": [r for r in rows if r["favorite"]]}
