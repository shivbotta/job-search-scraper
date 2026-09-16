"""
Fingerprint-based "hide until reposted" store.

When Shiva marks a job applied, every OTHER posting for the same
company+role fingerprint gets hidden from the dashboard -- until a posting
for that same fingerprint shows up with a posted_at newer than when it was
hidden (i.e. the company is genuinely hiring for that role again).
"""
import datetime
import json
import os
import re

from datehelpers import parse_posted_at


def _fingerprint(company: str, title: str) -> str:
    def norm(s):
        s = (s or "").lower().strip()
        s = re.sub(r"[^a-z0-9]+", " ", s)
        return re.sub(r"\s+", " ", s).strip()
    return f"{norm(company)}||{norm(title)}"


def load(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save(path: str, data: dict):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def hide_job(path: str, company: str, title: str, job_id: str):
    data = load(path)
    fp = _fingerprint(company, title)
    data[fp] = {
        "hidden_at": datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat(),
        "job_id": job_id,
        "company": company,
        "title": title,
    }
    save(path, data)


def is_hidden(hidden_store: dict, company: str, title: str, posted_at_raw) -> bool:
    fp = _fingerprint(company, title)
    entry = hidden_store.get(fp)
    if not entry:
        return False

    hidden_at = datetime.datetime.fromisoformat(entry["hidden_at"])
    posted_dt = parse_posted_at(posted_at_raw)

    if posted_dt is None:
        return True  # unknown posted date -- assume it's the same posting

    return posted_dt <= hidden_at
