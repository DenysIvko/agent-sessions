"""Explicit, anonymous PostHog events shared by the web and native clients."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
import sys
import tempfile
import threading
import uuid

from app_config import DATA_DIR, ROOT, VERSION

SURFACES = {"web", "tray"}
SOURCES = {"codex", "claude", "antigravity"}
EVENTS = {
    "app_opened": {},
    "dashboard_opened": {},
    "tray_opened": {},
    "view_selected": {"view": {"new", "all", "favorites"}},
    "filter_used": {"filter": {"source", "project", "status", "type", "search", "clear"}},
    "session_open_requested": {"source": SOURCES, "method": {"link", "copy"}},
    "favorite_changed": {"source": SOURCES, "enabled": bool},
    "session_archived": {"source": SOURCES},
    "tutorial_started": {},
    "tutorial_completed": {},
    "tutorial_dismissed": {"step": set(range(1, 8))},
    "notification_requested": {"kind": {"completion", "update", "test"}},
    "notification_clicked": {},
    "notifications_toggled": {"enabled": bool},
    "update_available": {},
    "update_download_requested": {},
}


def validate_event(event, properties):
    if not isinstance(event, str) or event not in EVENTS or not isinstance(properties, dict):
        raise ValueError("Unknown analytics event.")
    schema = {"surface": SURFACES, **EVENTS[event]}
    if properties.keys() != schema.keys():
        raise ValueError("Unexpected analytics properties.")
    for key, allowed in schema.items():
        value = properties[key]
        if allowed is bool:
            valid = type(value) is bool
        else:
            valid = type(value) in (str, int) and value in allowed
        if not valid:
            raise ValueError("Invalid analytics property.")


def configuration():
    try:
        config = json.loads((ROOT / "analytics-config.json").read_text())
    except (OSError, ValueError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    return {"key": os.environ.get("POSTHOG_PROJECT_KEY", config.get("key", "")),
            "host": os.environ.get("POSTHOG_HOST", config.get("host", "https://eu.i.posthog.com"))}


class Analytics:
    def __init__(self, *, demo=False, path=DATA_DIR / "analytics.json", config=None):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.queue = Queue(maxsize=100)
        self.generation = 0
        self.client = None
        self.worker = None
        self.closed = False
        self.demo = demo
        self.enabled = True
        self.installation_id = str(uuid.uuid4())
        config = configuration() if config is None else config
        self.key = config.get("key", "")
        self.host = config.get("host", "")
        self.configured = (not demo and isinstance(self.key, str) and self.key.startswith("phc_")
                           and isinstance(self.host, str)
                           and self.host in {"https://eu.i.posthog.com", "https://us.i.posthog.com"})
        if demo:
            return
        try:
            state = json.loads(self.path.read_text())
            if type(state["enabled"]) is not bool or not isinstance(state["installationId"], str):
                raise ValueError("Invalid preference")
            self.enabled = state["enabled"]
            self.installation_id = str(uuid.UUID(state["installationId"]))
        except FileNotFoundError:
            if self.configured:
                try:
                    self._save(self.enabled)
                except OSError:
                    self.enabled = False
        except (OSError, ValueError, KeyError, TypeError):
            # Never turn a previously disabled preference back on after a bad read.
            self.enabled = False

    def status(self):
        with self.lock:
            return {"enabled": self.enabled, "configured": self.configured, "demo": self.demo}

    def _save(self, enabled):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump({"enabled": enabled, "installationId": self.installation_id}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError("Enabled must be a boolean.")
        with self.lock:
            if not self.demo:
                self._save(enabled)
            self.enabled = enabled
            self.generation += 1
            # Discard pending events, including when switching off and on quickly.
            while True:
                try:
                    self.queue.get_nowait()
                    self.queue.task_done()
                except Empty:
                    break
        return self.status()

    def capture(self, event, properties):
        validate_event(event, properties)
        with self.lock:
            if not self.enabled or not self.configured or self.closed:
                return
            try:
                self.queue.put_nowait((self.generation, event, dict(properties), datetime.now(timezone.utc)))
            except Full:
                return
            if self.worker is None:
                self.worker = threading.Thread(target=self._send, daemon=True, name="product-analytics")
                self.worker.start()

    def _before_send(self, message):
        with self.lock:
            if self.closed or not self.enabled or self.sending_generation != self.generation:
                return None
        # Strip SDK context enrichment as well as application properties.
        props = message["properties"]
        event = message["event"]
        clean = {key: props[key] for key in ("surface", *EVENTS[event])}
        validate_event(event, clean)
        clean.update({"app_version": VERSION,
                      "platform": {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux"),
                      "$geoip_disable": True, "$ip": "0.0.0.0"})
        return {"event": event, "properties": clean, "distinct_id": self.installation_id,
                "timestamp": message["timestamp"], "uuid": message["uuid"],
                "options": {"process_person_profile": False}}

    def _send(self):
        while not self.closed:
            try:
                generation, event, properties, timestamp = self.queue.get(timeout=1)
            except Empty:
                continue
            try:
                with self.lock:
                    if not self.enabled or generation != self.generation or self.closed:
                        continue
                    self.sending_generation = generation
                if self.client is None:
                    from posthog import Posthog
                    # Our bounded queue lets opt-out discard pending work. The SDK
                    # sends synchronously only on this background worker.
                    self.client = Posthog(self.key, host=self.host, sync_mode=True, timeout=3,
                                          max_retries=0, disable_geoip=True, is_server=False,
                                          enable_local_evaluation=False, privacy_mode=True,
                                          before_send=self._before_send)
                self.client.capture(event, distinct_id=self.installation_id, properties=properties,
                                    timestamp=timestamp, options={"process_person_profile": False})
            except Exception:
                # Analytics never blocks product actions or writes private errors to logs.
                pass
            finally:
                self.queue.task_done()

    def close(self):
        self.closed = True
