"""Prepare public ingestion configuration without committing the project token."""

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def configure():
    path = ROOT / "analytics-config.json"
    key = os.environ.get("POSTHOG_PROJECT_KEY")
    if key:
        if not key.startswith("phc_"):
            raise ValueError("Use a public PostHog project token, never a personal API key.")
        host = os.environ.get("POSTHOG_HOST") or "https://eu.i.posthog.com"
        if host not in {"https://eu.i.posthog.com", "https://us.i.posthog.com"}:
            raise ValueError("Unsupported PostHog ingestion host.")
        path.write_text(json.dumps({"key": key, "host": host}))
    elif not path.exists():
        path.write_text("{}")
    return path


if __name__ == "__main__":
    configure()
