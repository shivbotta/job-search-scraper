"""
Manual job entry.

For LinkedIn, Indeed, or any board without a public, ToS-friendly API.
Shiva pastes the job text himself -- this module never fetches those URLs
programmatically.
"""
import hashlib
import datetime


def add_manual_job(url: str, text: str, title: str = "", company: str = "") -> dict:
    job_id = "manual-" + hashlib.sha1((url + text[:200]).encode()).hexdigest()[:10]
    return {
        "source": "manual",
        "company": company or "(unknown - fill in)",
        "job_id": job_id,
        "title": title or "(unknown - fill in)",
        "location": "",
        "url": url,
        "posted_at": datetime.date.today().isoformat(),
        "description_html": text,
    }
