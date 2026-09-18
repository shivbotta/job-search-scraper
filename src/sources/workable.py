"""
Workable public jobs widget API.

  https://apply.workable.com/api/v1/widget/accounts/{account}?details=true

No auth -- the same endpoint Workable's embeddable careers widget uses.
One call returns every open job with title, location, publish date and
full description. Replaces the old page-scrape path, which (like
SmartRecruiters) captured no location, so the US filter dropped every
Workable posting.
"""
import requests

URL = "https://apply.workable.com/api/v1/widget/accounts/{account}"


def _location_text(j: dict) -> str:
    country = j.get("country") or ""
    if j.get("telecommuting") and country in ("United States", "US", "USA"):
        return "Remote - United States"
    bits = [j.get("city"), j.get("state"), country]
    return ", ".join(b for b in bits if b)


def fetch_jobs(account: str) -> list[dict]:
    resp = requests.get(URL.format(account=account), params={"details": "true"}, timeout=20)
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs", []):
        jobs.append({
            "source": "workable",
            "company": account,
            "job_id": f"wk-{account}-{j.get('shortcode')}",
            "title": j.get("title", ""),
            "location": _location_text(j),
            "url": j.get("url") or j.get("shortlink") or "",
            "posted_at": j.get("published_on", ""),
            "description_html": j.get("description", "") or "",
        })
    return jobs
