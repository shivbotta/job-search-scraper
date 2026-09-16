"""
Greenhouse public job board API.

Docs: https://developers.greenhouse.io/job-board.html
No auth required. This is the same JSON feed that powers embeddable job widgets,
so pulling from it is explicitly within intended use.
"""
import requests

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def fetch_jobs(board_token: str) -> list[dict]:
    """Fetch all open postings for a company's Greenhouse board.

    board_token is the company slug, e.g. for boards.greenhouse.io/anthropic
    the token is 'anthropic'.
    """
    url = BASE_URL.format(token=board_token)
    resp = requests.get(url, params={"content": "true"}, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "source": "greenhouse",
            "company": board_token,
            "job_id": f"gh-{board_token}-{j['id']}",
            "title": j.get("title", ""),
            "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url", ""),
            "posted_at": j.get("updated_at", ""),
            "description_html": j.get("content", ""),
        })
    return jobs
