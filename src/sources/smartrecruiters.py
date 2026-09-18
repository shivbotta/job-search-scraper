"""
SmartRecruiters public postings API.

  List:   https://api.smartrecruiters.com/v1/companies/{company}/postings
  Detail: https://api.smartrecruiters.com/v1/companies/{company}/postings/{id}

No auth -- it's the same public feed that powers each company's hosted
careers page. Replaces the old page-scrape path, which captured no location
at all, so every SmartRecruiters posting was silently dropped by the US
filter and the source never contributed a single job.

The list endpoint already carries location, so the per-posting detail call
(needed for the description) is only made for US postings. Some companies
list hundreds of mostly non-US roles; fetching detail for all of them would
be slow and impolite for jobs that get discarded anyway.
"""
import time

import requests

BASE = "https://api.smartrecruiters.com/v1/companies/{company}/postings"
PAGE = 100
MAX_LIST = 400


def _is_us(loc: dict) -> bool:
    return (loc.get("country") or "").lower() == "us"


def _location_text(loc: dict) -> str:
    if loc.get("remote"):
        return "Remote - United States"
    bits = [loc.get("city"), loc.get("region")]
    return ", ".join(b for b in bits if b) + ", United States"


def _description(detail: dict) -> str:
    sections = (detail.get("jobAd") or {}).get("sections") or {}
    order = ("jobDescription", "qualifications", "additionalInformation", "companyDescription")
    return "\n".join((sections.get(k) or {}).get("text", "") or "" for k in order)


def fetch_jobs(company: str) -> list[dict]:
    listing = []
    offset = 0
    while offset < MAX_LIST:
        resp = requests.get(BASE.format(company=company),
                            params={"limit": PAGE, "offset": offset}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("content", [])
        listing.extend(batch)
        if len(batch) < PAGE or offset + PAGE >= data.get("totalFound", 0):
            break
        offset += PAGE

    jobs = []
    for p in listing:
        loc = p.get("location") or {}
        if not _is_us(loc):
            continue
        detail = {}
        try:
            d = requests.get(p["ref"], timeout=15)
            if d.status_code == 200:
                detail = d.json()
        except requests.RequestException:
            pass
        time.sleep(0.3)

        jobs.append({
            "source": "smartrecruiters",
            "company": company,
            "job_id": f"sr-{company}-{p['id']}",
            "title": p.get("name", ""),
            "location": _location_text(loc),
            "url": detail.get("postingUrl")
                   or f"https://jobs.smartrecruiters.com/{company}/{p['id']}",
            "posted_at": p.get("releasedDate", ""),
            "description_html": _description(detail),
        })
    return jobs
