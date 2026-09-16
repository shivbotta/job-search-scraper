"""
Lever public postings API.

Docs: https://github.com/lever/postings-api
No auth required, designed for public consumption (same feed as jobs.lever.co).
"""
import requests

BASE_URL = "https://api.lever.co/v0/postings/{token}"


def fetch_jobs(company_token: str) -> list[dict]:
    """Fetch all open postings for a company's Lever board.

    company_token is the slug in jobs.lever.co/<token>.
    """
    url = BASE_URL.format(token=company_token)
    resp = requests.get(url, params={"mode": "json"}, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for j in data:
        cats = j.get("categories", {})
        jobs.append({
            "source": "lever",
            "company": company_token,
            "job_id": f"lv-{company_token}-{j['id']}",
            "title": j.get("text", ""),
            "location": cats.get("location", ""),
            "url": j.get("hostedUrl", ""),
            "posted_at": j.get("createdAt", ""),
            "description_html": j.get("descriptionPlain", j.get("description", "")),
        })
    return jobs
