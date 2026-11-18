"""Completion and review state for the Windows tray."""

OUTCOMES = {"completed": "finished", "failed": "failed", "interrupted": "stopped"}


def all_sessions(snapshot):
    return list({s["id"]: s for s in snapshot.get("favoriteSessions", []) + snapshot.get("sessions", [])}.values())


def completion_id(session):
    return f"{session['id']}:{session.get('turnId') or session.get('startedAt', 0)}:{session.get('status')}:{session.get('endedAt')}"


class SessionMonitor:
    def __init__(self, reviews=None):
        self.reviews = reviews or {"pending": {}, "reviewed": {}}
        self.previous = {}
        self.last_check = {}

    def update(self, snapshot):
        finished = []
        checked = snapshot.get("checkedAt")
        if checked is None:
            return finished
        errors = snapshot.get("sourceErrors", {})
        for source in ("codex", "claude", "antigravity"):
            if source in errors:
                continue
            sessions = [s for s in snapshot.get("sessions", []) if s["source"] == source]
            baseline = self.last_check.get(source)
            for session in sessions:
                previous = self.previous.get(session["id"])
                if baseline is not None and not session.get("running") and session.get("status") in OUTCOMES:
                    new_result = not previous or completion_id(previous) != completion_id(session)
                    observed = previous and previous.get("running")
                    recent = (session.get("endedAt") or 0) > baseline
                    if new_result and (observed or recent):
                        finished.append(session)
                        self.reviews["pending"][session["id"]] = completion_id(session)
            self.previous = {id: s for id, s in self.previous.items() if s["source"] != source}
            self.previous.update({s["id"]: s for s in sessions})
            self.last_check[source] = checked
        sessions = all_sessions(snapshot)
        for session in sessions:
            if session["source"] not in errors and (session.get("running") or session.get("unread") is False
                    or self.reviews["pending"].get(session["id"]) != completion_id(session)):
                self.reviews["pending"].pop(session["id"], None)
        if not errors:
            ids = {s["id"] for s in sessions}
            self.reviews = {key: {id: value for id, value in items.items() if id in ids}
                            for key, items in self.reviews.items()}
        return finished

    def new_sessions(self, snapshot):
        return [s for s in all_sessions(snapshot) if s.get("running") or (
            s.get("status") in OUTCOMES and s.get("unread") is not False
            and self.reviews["reviewed"].get(s["id"]) != completion_id(s)
            and (s.get("unread") is True or self.reviews["pending"].get(s["id"]) == completion_id(s)))]

    def mark_reviewed(self, session):
        self.reviews["reviewed"][session["id"]] = completion_id(session)
        self.reviews["pending"].pop(session["id"], None)
