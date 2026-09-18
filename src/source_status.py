"""
Per-source run status, written by `pull`/`scrape` and read by the dashboard.

Before this, the dashboard's "sources live" line only checked whether
credentials were set in .env -- Indeed showed as live while every real run
was stopped by a CAPTCHA. This records what actually happened on the last
run of each source so failures are visible instead of silent.
"""
import datetime
import json
import os

OK, BLOCKED, FAILED = "ok", "blocked", "failed"


def load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def record(path: str, source: str, state: str, fetched: int = 0, detail: str = ""):
    data = load(path)
    data[source] = {
        "state": state,
        "fetched": fetched,
        "detail": detail[:300],
        "last_run": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
