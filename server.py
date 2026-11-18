#!/usr/bin/env python3
"""A loopback-only dashboard of local coding agent sessions."""

import argparse
from datetime import datetime, timedelta
import json
import mimetypes
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from app_config import DATA_DIR, TIMEZONE, VERSION
from antigravity_sessions import read_sessions as read_antigravity_sessions
from claude_sessions import ClaudeSessions
from session_actions import archive_session
from updates import checker as update_checker
from product_analytics import Analytics

ROOT = Path(__file__).resolve().parent
CODEX = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
UUID = r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"
ROLLOUT_ID = re.compile(rf"rollout-.*-({UUID})\.jsonl$")
FAVORITES_PATH = DATA_DIR / "favorites.json"


def read_session_ids(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    if not isinstance(value, list) or not all(isinstance(id, str) for id in value):
        raise ValueError(f"{path.name} must contain session IDs.")
    return set(value)


def write_session_ids(path, ids):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(sorted(ids), stream)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def open_session_ids():
    """Confirm a session is loaded by a live Codex process, including long waits."""
    if sys.platform == "win32":
        from processes import matching_processes, open_files
        return {m.group(1) for path in open_files(matching_processes("codex"))
                if (m := ROLLOUT_ID.search(str(path)))}
    processes = subprocess.run(
        ["ps", "-axo", "pid=,comm="], capture_output=True, text=True, check=True, timeout=3
    ).stdout
    pids = [line.split(None, 1)[0] for line in processes.splitlines()
            if line.strip().endswith("/codex")]
    if not pids:
        return set()
    result = subprocess.run(
        ["lsof", "-nP", "-p", ",".join(pids), "-Fn"],
        capture_output=True, text=True, timeout=5
    )
    if result.returncode not in (0, 1) or (result.returncode == 1 and not result.stdout):
        raise RuntimeError("Could not read live Codex processes")
    return {m.group(1) for line in result.stdout.splitlines()
            if line.startswith("n") and (m := ROLLOUT_ID.search(line))}


def legacy_unread(global_state):
    # shortcut: legacy read state predates account-aware SQLite receipts. Only use
    # a single identity's local host; add identity selection if accounts are shared.
    identities = global_state.get("electron-thread-read-state-v1", {}).get("unreadByIdentity", {})
    if len(identities) != 1:
        return set()
    return {tid for host, ids in next(iter(identities.values())).items()
            if host.startswith("local:") for tid in ids}


def classify(row, loaded_ids, unread_ids):
    if row["archived"]:
        return None
    running = row["turn_status"] == "inProgress" and row["id"] in loaded_ids
    unread = bool(row["first_unread_turn"]) if row["receipt_id"] else row["id"] in unread_ids
    return running, unread


def read_sessions(codex=CODEX, loaded_ids=None, now=None, include_ids=()):
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now, TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    day_start, day_end = today.timestamp(), (today + timedelta(days=1)).timestamp()
    if not (codex / "state_5.sqlite").exists():
        return {"sessions": []}
    if loaded_ids is None:
        loaded_ids = open_session_ids()
    state_path = codex / ".codex-global-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    unread_ids = legacy_unread(state)
    connection = sqlite3.connect((codex / "state_5.sqlite").as_uri() + "?mode=ro", uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("ATTACH DATABASE ? AS history", ((codex / "thread_history_1.sqlite").as_uri() + "?mode=ro",))
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute("""
            SELECT t.id, t.name, t.title, t.cwd, t.model, t.source, t.thread_source,
                   t.archived, t.updated_at, t.git_branch, t.project_id,
                   r.thread_id AS receipt_id, r.first_unread_turn,
                   tt.status AS turn_status, tt.turn_id, tt.started_at, tt.completed_at,
                   MAX(COALESCE(tt.started_at, 0), COALESCE(tt.completed_at, 0),
                       COALESCE((SELECT MAX(i.created_at_ms, COALESCE(i.started_at_ms, 0),
                           COALESCE(i.completed_at_ms, 0)) / 1000.0
                           FROM history.thread_items i WHERE i.thread_id = t.id
                           ORDER BY i.rollout_ordinal DESC LIMIT 1), 0)) AS activity_at
            FROM threads t
            LEFT JOIN thread_read_receipts r ON r.thread_id = t.id
            LEFT JOIN history.thread_turns tt ON tt.thread_id = t.id
                AND tt.turn_id = (SELECT turn_id FROM history.thread_turns
                    WHERE thread_id = t.id ORDER BY rollout_ordinal DESC LIMIT 1)
            WHERE t.archived = 0
            ORDER BY t.updated_at DESC
        """).fetchall()
        edges = dict(connection.execute("SELECT child_thread_id, parent_thread_id FROM thread_spawn_edges"))
        project_names = dict(connection.execute("SELECT id, name FROM projects"))
        root_projects = dict(connection.execute("""SELECT path, MIN(project_id) FROM project_roots
            GROUP BY path HAVING COUNT(DISTINCT project_id) = 1"""))
    finally:
        connection.close()

    active_children = {}
    for row in rows:
        parent = edges.get(row["id"])
        if parent and row["id"] in loaded_ids and row["turn_status"] == "inProgress":
            active_children[parent] = active_children.get(parent, 0) + 1

    sessions = []
    projects = state.get("local-projects", {})
    assignments = state.get("thread-project-assignments", {})
    migrated_projects = state.get("app-server-project-id-by-legacy-project-id-by-host", {}).get(f"local:{codex}", {})
    for row in rows:
        # The desktop's child agents stay attached to their parent session.
        if row["id"] in edges:
            continue
        flags = classify(row, loaded_ids, unread_ids)
        if flags is None:
            continue
        running, unread = flags
        # A live run counts as activity today even if it started before midnight.
        activity_at = now if running else row["activity_at"]
        is_today = day_start <= activity_at < day_end
        if not is_today and row["id"] not in include_ids:
            continue
        assignment = assignments.get(row["id"], {})
        legacy_id = assignment.get("projectId")
        legacy_project = projects.get(legacy_id, {})
        project_id = (row["project_id"] or migrated_projects.get(legacy_id, legacy_id)
                      or root_projects.get(row["cwd"]) or f"workspace:{row['cwd']}")
        project = project_names.get(project_id) or legacy_project.get("name") or Path(row["cwd"]).name or "No project"
        sessions.append({
            "id": row["id"], "source": "codex", "title": row["name"] or row["title"] or "Untitled session",
            "project": project, "projectId": project_id, "model": row["model"], "branch": row["git_branch"],
            "kind": "Scheduled" if row["thread_source"] == "automation" else "Chat",
            "running": running, "unread": unread, "updatedAt": row["updated_at"],
            "status": row["turn_status"], "turnId": row["turn_id"],
            "activityAt": activity_at,
            "isToday": is_today,
            "startedAt": row["started_at"], "endedAt": row["completed_at"],
            "agents": active_children.get(row["id"], 0),
            "url": f"codex://threads/{row['id']}",
        })
    return {"sessions": sessions, "checkedAt": now, "scope": "This device",
            "date": today.date().isoformat(), "timezone": str(TIMEZONE)}


class Snapshot:
    def __init__(self, favorites_path=FAVORITES_PATH):
        self.lock = threading.Lock()
        self.refresh_lock = threading.RLock()
        self.archive_lock = threading.Lock()
        self.claude = ClaudeSessions()
        self.favorites_path = favorites_path
        self.archives_path = favorites_path.with_name("archived.json")
        self.favorites = set()
        self.archived = set()
        self.data = {"sessions": [], "checkedAt": None, "error": "Connecting to session sources..."}

    def refresh_once(self, now=None):
        with self.refresh_lock:
            return self._refresh_once(now)

    def _refresh_once(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            previous = self.data
        data = {"service": "agent-sessions", "version": VERSION, "schemaVersion": 1, "sourceErrors": {},
                "sessions": [], "favoriteSessions": [], "checkedAt": now, "scope": "This device",
                "date": datetime.fromtimestamp(now, TIMEZONE).date().isoformat(), "timezone": str(TIMEZONE)}
        errors = []
        try:
            self.favorites = read_session_ids(self.favorites_path)
        except (OSError, ValueError):
            errors.append("Favorites could not be loaded. Showing the last saved flags.")
        try:
            self.archived = read_session_ids(self.archives_path)
        except (OSError, ValueError):
            errors.append("Local archives could not be loaded. Keeping the last saved hidden sessions.")
        for source, label, reader in (
            ("codex", "Codex", lambda: read_sessions(now=now, include_ids=self.favorites)["sessions"]),
            ("claude", "Claude Code", lambda: self.claude.read(now, include_ids=self.favorites)),
            ("antigravity", "Antigravity", lambda: read_antigravity_sessions(now, include_ids=self.favorites)),
        ):
            try:
                sessions = reader()
            except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError, RuntimeError) as error:
                print(f"{label} session read failed: {error}", flush=True)
                saved = {s["id"]: s for s in previous["sessions"] + previous.get("favoriteSessions", [])}
                sessions = [s for s in saved.values() if s.get("source", "codex") == source]
                message = f"{label} unavailable. Showing its last successful update."
                errors.append(message)
                data["sourceErrors"][source] = message
            for session in sessions:
                if self.archived & {session["id"], *session.get("relatedIds", [])}:
                    continue
                session = {**session, "favorite": bool(self.favorites & {session["id"], *session.get("relatedIds", [])})}
                if session.get("isToday", True):
                    data["sessions"].append(session)
                if session["favorite"]:
                    data["favoriteSessions"].append(session)
        if errors:
            data["error"] = " ".join(errors)
        with self.lock:
            self.data = data
        return data

    def set_favorite(self, sid, enabled):
        if not isinstance(enabled, bool):
            raise ValueError("Favorite must be true or false.")
        with self.refresh_lock:
            with self.lock:
                sessions = self.data["sessions"] + self.data.get("favoriteSessions", [])
                session = next((s for s in sessions if s["id"] == sid), None)
            if session is None:
                raise ValueError("This session is no longer available in the dashboard.")
            favorites = read_session_ids(self.favorites_path)
            if enabled:
                favorites.add(sid)
            else:
                favorites.difference_update({sid, *session.get("relatedIds", [])})
            write_session_ids(self.favorites_path, favorites)
            self.favorites = favorites
            with self.lock:
                rows = {s["id"]: dict(s) for s in sessions}
                for row in rows.values():
                    row["favorite"] = bool(favorites & {row["id"], *row.get("relatedIds", [])})
                self.data = {**self.data,
                    "sessions": [rows[s["id"]] for s in self.data["sessions"]],
                    "favoriteSessions": [s for s in rows.values() if s["favorite"]]}

    def archive(self, sid):
        with self.refresh_lock:
            archived = read_session_ids(self.archives_path)
            if sid in archived:
                return
            with self.lock:
                sessions = self.data["sessions"] + self.data.get("favoriteSessions", [])
                session = next((s for s in sessions if s["id"] == sid), None)
                source_errors = self.data.get("sourceErrors", {})
            if session is None:
                raise ValueError("This session is no longer available in the dashboard.")
            archived.update({sid, *session.get("relatedIds", [])})
            write_session_ids(self.archives_path, archived)
            self.archived = archived
            with self.lock:
                self.data = {**self.data, **{
                    key: [s for s in self.data.get(key, [])
                          if not archived & {s["id"], *s.get("relatedIds", [])}]
                    for key in ("sessions", "favoriteSessions")}}
        # Hiding active work must not stop it; source failures never undo the local archive.
        if session["source"] in ("codex", "claude") and not session.get("running") and not session.get("agents") and session["source"] not in source_errors:
            threading.Thread(target=self._archive_in_source, args=(session,), daemon=True).start()

    def _archive_in_source(self, session):
        # Claude's UI archive actions must not compete for the selected conversation.
        with self.archive_lock:
            try:
                archive_session(session)
            except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
                print(f"Source archive failed; session remains hidden locally: {error}", flush=True)

    def refresh(self):
        while True:
            self.refresh_once()
            time.sleep(3)


class Handler(BaseHTTPRequestHandler):
    def allowed_request(self):
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        # The public HTML shell can be opened from another app or website.
        # Session data and mutations still require a same-origin request.
        navigation = (self.command == "GET" and urlsplit(self.path).path == "/"
                      and self.headers.get("Sec-Fetch-Mode") == "navigate"
                      and self.headers.get("Sec-Fetch-Dest") == "document")
        if host not in allowed or (self.headers.get("Sec-Fetch-Site") == "cross-site" and not navigation) or (
            origin and origin not in {f"http://{value}" for value in allowed}
        ):
            self.send_error(403)
            return False
        return True

    def do_POST(self):
        if not self.allowed_request():
            return
        if self.path not in ("/api/archive", "/api/favorite", "/api/analytics", "/api/analytics/preferences"):
            self.send_error(404)
            return
        # A custom header and JSON content type prevent cross-site form submissions.
        if self.headers.get("X-Session-Dashboard") != "1" or self.headers.get("Content-Type") != "application/json":
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 512:
                raise ValueError("Invalid request size.")
            self.connection.settimeout(3)
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("A JSON object is required.")
            if self.path == "/api/analytics/preferences":
                self.send_json(200, self.server.analytics.set_enabled(payload.get("enabled")))
                return
            if self.path == "/api/analytics":
                self.server.analytics.capture(payload.get("event"), payload.get("properties"))
                self.send_json(200, {"ok": True})
                return
            if not isinstance(payload.get("id"), str):
                raise ValueError("A session ID is required.")
            snapshot = self.server.snapshot
            if self.path == "/api/favorite":
                snapshot.set_favorite(payload["id"], payload.get("favorite"))
                self.send_json(200, {"favorite": payload["favorite"]})
                return
            snapshot.archive(payload["id"])
            self.send_json(200, {"message": "Archived in Agent Sessions."})
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            if self.path == "/api/archive":
                print(f"Archive failed: {error}", flush=True)
            self.send_json(400, {"error": str(error)})

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.allowed_request():
            return
        path = urlsplit(self.path).path
        if path == "/api/analytics":
            self.send_json(200, self.server.analytics.status())
            return
        if path == "/api/update":
            self.send_json(200, update_checker.check())
            return
        if path == "/api/sessions":
            with self.server.snapshot.lock:
                body = json.dumps({**self.server.snapshot.data, "analytics": self.server.analytics.status()}).encode()
            content_type = "application/json"
        elif path in ("/", "/app.js", "/styles.css", "/favicon.svg", "/colors.mjs", "/sessions.mjs", "/tutorial.mjs", "/analytics.mjs",
                      "/vendor/color-hash-2.0.2/color-hash.mjs"):
            file = ROOT / "public" / ("index.html" if path == "/" else path[1:])
            body = file.read_bytes()
            content_type = mimetypes.guess_type(file)[0] or "application/octet-stream"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--open", action="store_true", help="Open the dashboard in the default browser")
    parser.add_argument("--demo", action="store_true", help="Show fictional screenshot data without reading source apps")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.analytics = Analytics(demo=args.demo)
    if args.demo:
        from demo import snapshot
        server.snapshot = Snapshot()
        server.snapshot.data = snapshot()
        def read_only(*_):
            raise ValueError("This is a read-only demo.")
        server.snapshot.archive = read_only
        server.snapshot.set_favorite = read_only
    else:
        server.snapshot = Snapshot()
        threading.Thread(target=server.snapshot.refresh, daemon=True).start()
    url = f"http://127.0.0.1:{args.port}"
    print(f"Agent Sessions {VERSION} is running at {url}\nPress Ctrl+C to stop.", flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.analytics.close()
        server.server_close()


if __name__ == "__main__":
    main()
