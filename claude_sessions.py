"""Read local Claude Code metadata without starting or changing conversations."""

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from app_config import TIMEZONE, support_dir

CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
DESKTOP = support_dir() / "Claude/claude-code-sessions"
SESSION_ID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$")


def timestamp(value):
    if isinstance(value, (float, int)):
        return value / 1000
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return 0


def live_sessions(root):
    if sys.platform == "win32":
        from processes import matching_processes, open_files
        processes = list(matching_processes("claude"))
        pids = {p.pid for p in processes}
        loaded = {p.stem for p in open_files(processes)
                  if p.suffix == ".jsonl" and p.is_relative_to(root / "projects") and SESSION_ID.fullmatch(p.stem)}
        busy = set()
        for path in (root / "sessions").glob("*.json"):
            try:
                row = json.loads(path.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                continue
            if row.get("pid") in pids and (row.get("status") in ("busy", "running") or row.get("isBusy") is True):
                busy.add(row.get("sessionId"))
        return busy, loaded
    processes = subprocess.run(["ps", "-axo", "pid=,comm="], capture_output=True,
                               text=True, check=True, timeout=3).stdout
    pids = {int(line.split(None, 1)[0]) for line in processes.splitlines()
            if line.strip().endswith("/claude") or "/claude/versions/" in line}
    busy = set()
    for path in (root / "sessions").glob("*.json"):
        try:
            row = json.loads(path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            continue
        if row.get("pid") in pids and (row.get("status") in ("busy", "running") or row.get("isBusy") is True):
            busy.add(row.get("sessionId"))
    if not pids:
        return busy, set()
    result = subprocess.run(["lsof", "-nP", "-p", ",".join(map(str, pids)), "-Fn"],
                            capture_output=True, text=True, timeout=5)
    if result.returncode not in (0, 1) or (result.returncode == 1 and not result.stdout):
        raise RuntimeError("Could not read live Claude Code processes")
    loaded = set()
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            path = Path(line[1:])
            if path.suffix == ".jsonl" and path.is_relative_to(root / "projects") and SESSION_ID.fullmatch(path.stem):
                loaded.add(path.stem)
    return busy, loaded


def read_transcript(path):
    # shortcut: local formats are internal; use the SDK when it exposes actual
    # activity timestamps and desktop archive state together.
    info = {"createdAt": 0, "activityAt": 0, "startedAt": None, "endedAt": None,
            "status": None, "pending": False, "title": "", "cwd": "", "branch": "", "model": ""}
    first_prompt = ""
    with path.open() as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # A writer may not have finished the final JSONL record yet.
                continue
            if not isinstance(row, dict) or row.get("isSidechain"):
                continue
            kind = row.get("type")
            if kind == "custom-title":
                info["title"] = row.get("customTitle") or info["title"]
            if kind not in ("user", "assistant", "system") or row.get("isMeta"):
                continue
            if kind == "system" and row.get("subtype") not in ("turn_duration", "stop_hook_summary"):
                continue
            at = timestamp(row.get("timestamp"))
            if not at:
                continue
            info["createdAt"] = min(info["createdAt"] or at, at)
            if at < info["activityAt"]:
                continue
            info["activityAt"] = at
            for source, target in (("cwd", "cwd"), ("gitBranch", "branch")):
                info[target] = row.get(source) or info[target]
            message = row.get("message") or {}
            if not isinstance(message, dict):
                raise ValueError("Unexpected Claude message format")
            content = message.get("content", [])
            blocks = content if isinstance(content, list) else []
            tool_result = any(b.get("type") == "tool_result" for b in blocks if isinstance(b, dict))
            if kind == "user":
                if not tool_result:
                    info["startedAt"] = at
                    if not first_prompt:
                        text = content if isinstance(content, str) else " ".join(
                            b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text")
                        first_prompt = " ".join(text.split())[:120]
                info.update(pending=True, status="inProgress", endedAt=None)
            elif kind == "assistant":
                model = message.get("model") or row.get("requestedModel")
                if model and model != "<synthetic>":
                    info["model"] = model
                failed = row.get("isApiErrorMessage") is True
                finished = failed or message.get("stop_reason") in ("end_turn", "stop_sequence")
                info.update(pending=not finished, status="failed" if failed else "completed" if finished else "inProgress",
                            endedAt=at if finished else None)
            elif not row.get("preventedContinuation"):
                info.update(pending=False, status="failed" if info["status"] == "failed" else "completed", endedAt=at)
    info["title"] = info["title"] or first_prompt or "Untitled Claude Code session"
    return info


class ClaudeSessions:
    def __init__(self, root=CLAUDE, desktop=DESKTOP):
        self.root, self.desktop = root, desktop
        self.cache = {}

    def read(self, now, live=None, include_ids=()):
        include_ids = set(include_ids)
        today = datetime.fromtimestamp(now, TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        start, end = today.timestamp(), (today + timedelta(days=1)).timestamp()
        busy, loaded = live_sessions(self.root) if live is None else live
        transcripts = {}
        archived_ids = set()
        paths = list((self.root / "projects").glob("*/*.jsonl"))
        for path in paths:
            if not SESSION_ID.fullmatch(path.stem):
                continue
            try:
                marker = json.loads((path.parent / path.stem / "archived.json").read_text())
            except FileNotFoundError:
                marker = {}
            if marker.get("archived") is True:
                archived_ids.add(path.stem)
            try:
                stat = path.stat()
                signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
                cached = self.cache.get(path)
                if not cached or cached[0] != signature:
                    cached = self.cache[path] = (signature, read_transcript(path))
            except FileNotFoundError:
                continue
            previous = transcripts.get(path.stem)
            if not previous or cached[1]["activityAt"] > previous["activityAt"]:
                transcripts[path.stem] = cached[1]
        self.cache = {p: self.cache[p] for p in paths if p in self.cache}

        sessions, claimed = [], set()
        desktop_rows = {}
        for path in self.desktop.rglob("local_*.json"):
            try:
                row = json.loads(path.read_text())
            except FileNotFoundError:
                continue
            sid = row.get("sessionId", "")
            if not sid.startswith("local_") or not SESSION_ID.fullmatch(sid[6:]):
                continue
            previous = desktop_rows.get(sid)
            if not previous or row.get("lastActivityAt", 0) > previous.get("lastActivityAt", 0):
                desktop_rows[sid] = row
        for sid, row in desktop_rows.items():
            ids = set(row.get("priorCliSessionIds") or [])
            ids.update(id for id in (row.get("cliSessionId"), row.get("lastAssistantCliSessionId")) if id)
            claimed.update(ids)
            if row.get("isArchived"):
                continue
            histories = [transcripts[id] for id in ids if id in transcripts]
            info = dict(max(histories, key=lambda item: item["activityAt"])) if histories else {}
            created = timestamp(row.get("createdAt")) or info.get("createdAt", 0)
            activity = max(created, timestamp(row.get("lastActivityAt")), info.get("activityAt", 0))
            running = bool(ids & busy or ids & loaded and info.get("pending"))
            activity = now if running else activity
            related_ids = {f"claude:{id}" for id in ids}
            is_today = start <= activity < end
            if not is_today and not (related_ids | {f"claude:{sid}"}) & include_ids:
                continue
            edge = timestamp(row.get("lastTurnEdgeAt"))
            if not running and info.get("status") != "failed" and row.get("completedTurns", 0) and edge >= max(
                    timestamp(row.get("latestUserFrameAt")), info.get("activityAt", 0)):
                info.update(status="completed", endedAt=edge)
            cwd = row.get("originCwd") or row.get("cwd") or info.get("cwd", "")
            sessions.append(self.session(sid, row.get("title") or info.get("title"), cwd,
                                         created, activity, running, info,
                                         url=f"claude://epitaxy/{sid}", model=row.get("model")))
            sessions[-1].update(isToday=is_today, relatedIds=sorted(related_ids))
        for sid, info in transcripts.items():
            if sid in claimed or sid in archived_ids:
                continue
            running = sid in busy or sid in loaded and info["pending"]
            activity = now if running else info["activityAt"]
            is_today = start <= activity < end
            if not is_today and f"claude:{sid}" not in include_ids:
                continue
            session = self.session(sid, info["title"], info["cwd"], info["createdAt"], activity, running, info,
                                   url=f"claude://resume?session={sid}")
            resume = shlex.join(["claude", "--resume", sid])
            session["resumeCommand"] = f"cd {shlex.quote(info['cwd'])} && {resume}" if info["cwd"] else resume
            session["isToday"] = is_today
            sessions.append(session)
        return sessions

    @staticmethod
    def session(sid, title, cwd, created, activity, running, info, url=None, model=None):
        # shortcut: Claude has no persisted read receipt in these local sources.
        # Keep it unknown until the app provides an authoritative read signal.
        return {"id": f"claude:{sid}", "sessionId": sid, "source": "claude", "title": title or "Untitled Claude Code session",
                "project": Path(cwd).name if cwd else "No project", "projectId": f"workspace:{cwd or 'claude'}",
                "model": model or info.get("model", ""), "branch": info.get("branch", ""), "kind": "Chat",
                "createdAt": created, "updatedAt": activity, "activityAt": activity, "running": bool(running),
                "unread": None, "status": "inProgress" if running else info.get("status"),
                "startedAt": info.get("startedAt"), "endedAt": None if running else info.get("endedAt"),
                "agents": 0, "url": url}
