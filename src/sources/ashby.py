"""
Ashby public job board API.

Docs: https://developers.ashbyhq.com/docs/public-job-posting-api
No auth required for the public job-board endpoint.
"""
import requests

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"


def fetch_jobs(org_token: str) -> list[dict]:
    """Fetch all open postings for a company's Ashby board.

    org_token is the slug in jobs.ashbyhq.com/<token>.
    """
    url = BASE_URL.format(token=org_token)
    resp = requests.get(url, params={"includeCompensation": "true"}, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for j in data.get("jobs", []):
        jobs.append({
            "source": "ashby",
            "company": org_token,
            "job_id": f"ab-{org_token}-{j['id']}",
            "title": j.get("title", ""),
            "location": j.get("location", ""),
            "url": j.get("jobUrl", ""),
            "posted_at": j.get("publishedAt", ""),
            "description_html": j.get("descriptionHtml", ""),
        })
    return jobs
