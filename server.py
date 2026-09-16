#!/usr/bin/env python3
"""
Local dashboard server.

Run: python server.py
Then open http://localhost:8765 -- refresh any morning after running
`python cli.py pull && python cli.py score`.

Runs on localhost only. The /apply route is the one place this tool writes
state on your behalf, and it only ever updates your own local tracker.csv +
hidden.json -- it never touches LinkedIn, Indeed, Gmail, or any external
service.
"""
import json
import os
import sys

from flask import Flask, jsonify

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import dashboard as dashboard_mod  # noqa: E402
import tracker  # noqa: E402

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
JOBS_FILE = os.path.join(DATA_DIR, "jobs_seen.json")
TRACKER_FILE = os.path.join(DATA_DIR, "tracker.csv")
HIDDEN_FILE = os.path.join(DATA_DIR, "hidden.json")

app = Flask(__name__)


def load_jobs():
    if not os.path.exists(JOBS_FILE):
        return {}
    with open(JOBS_FILE) as f:
        return json.load(f)


@app.route("/")
def index():
    jobs = load_jobs()
    buckets = dashboard_mod.build_view(jobs, HIDDEN_FILE)
    return dashboard_mod.render_html(buckets)


@app.route("/apply/<job_id>", methods=["POST"])
def apply(job_id):
    jobs = load_jobs()
    job = jobs.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404
    tracker.mark_applied(TRACKER_FILE, HIDDEN_FILE, job)
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("Dashboard running at http://localhost:8765")
    app.run(port=8765, debug=False)
