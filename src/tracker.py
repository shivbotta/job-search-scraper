"""Simple CSV application tracker."""
import csv
import os
import datetime

import hidden as hidden_mod

FIELDS = ["job_id", "company", "title", "url", "track", "det_score",
          "ai_score", "status", "last_updated", "notes"]


def _ensure_file(path: str):
    if not os.path.exists(path):
        with open(path, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()


def upsert(path: str, job_id: str, **fields):
    _ensure_file(path)
    rows = []
    found = False
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["job_id"] == job_id:
                row.update({k: v for k, v in fields.items() if v is not None})
                row["last_updated"] = datetime.date.today().isoformat()
                found = True
            rows.append(row)
    if not found:
        new_row = {k: "" for k in FIELDS}
        new_row["job_id"] = job_id
        new_row.update({k: v for k, v in fields.items() if v is not None})
        new_row["last_updated"] = datetime.date.today().isoformat()
        rows.append(new_row)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def read_all(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def mark_applied(tracker_path: str, hidden_path: str, job: dict):
    """Logs the application AND hides same-fingerprint postings from the
    dashboard until that company reposts the role."""
    det = job.get("deterministic_score", {}) or {}
    ai = job.get("ai_score", {}) or {}
    upsert(
        tracker_path,
        job["job_id"],
        company=job.get("company"),
        title=job.get("title"),
        url=job.get("url"),
        track=det.get("best_track"),
        det_score=det.get("composite_score"),
        ai_score=ai.get("fit_score"),
        status="applied",
    )
    hidden_mod.hide_job(hidden_path, job.get("company", ""), job.get("title", ""), job["job_id"])
