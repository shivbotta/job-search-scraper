"""
Workday public job board API (Part 3d).

Workday doesn't publish a documented public API the way Greenhouse/Lever/
Ashby do, but every company running Workday recruiting exposes the same
internal JSON endpoint their own careers site calls -- confirmed live
against workday.wd5.myworkdayjobs.com/Workday:

  Search (POST): https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
  Detail (GET):  https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{externalPath}

This covers a large share of "big tech custom career site" employers that
are actually running Workday under a company-branded URL (Adobe, Broadcom,
Visa, Mastercard, PayPal, GE, Honeywell, John Deere, and many more from the
MASTER-BUILD-PROMPT roster). No login, read-only, same public data their own
frontend fetches.
"""
import re
import time

import requests

PAGE_SIZE = 20
MAX_PAGES = 15  # cap per company so one huge board can't dominate a run


def parse_workday_url(url: str):
    """Pulls (tenant, wd, site) out of any myworkdayjobs.com URL, e.g.
    https://workday.wd5.myworkdayjobs.com/en-US/Workday/job/... ->
    ('workday', 'wd5', 'Workday'). Returns None if the URL doesn't match."""
    m = re.search(
        r"https?://([^.]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)/",
        url + "/",
    )
    return (m.group(1), m.group(2), m.group(3)) if m else None


def fetch_jobs(tenant: str, wd: str, site: str) -> list[dict]:
    """Fetch every open posting for one Workday tenant/site, with full JD
    text (a second GET per posting -- the search endpoint only returns
    title/location/postedOn, not the description)."""
    base = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    jobs = []
    offset = 0

    for _ in range(MAX_PAGES):
        resp = requests.post(
            f"{base}/jobs",
            json={"appliedFacets": {}, "limit": PAGE_SIZE, "offset": offset, "searchText": ""},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break

        for p in postings:
            external_path = p.get("externalPath", "")
            detail = {}
            try:
                d = requests.get(f"{base}{external_path}", timeout=15)
                if d.status_code == 200:
                    detail = d.json().get("jobPostingInfo", {})
            except requests.RequestException:
                pass
            time.sleep(0.3)  # light pacing between per-job detail calls

            jobs.append({
                "source": "workday",
                "company": tenant,
                "job_id": f"wd-{tenant}-{detail.get('jobReqId') or external_path}",
                "title": detail.get("title") or p.get("title", ""),
                "location": detail.get("location") or p.get("locationsText", ""),
                "url": detail.get("externalUrl") or f"{base.replace('/wday/cxs', '')}{external_path}",
                "posted_at": detail.get("startDate", ""),
                "description_html": detail.get("jobDescription", ""),
            })

        if len(postings) < PAGE_SIZE or offset + PAGE_SIZE >= data.get("total", 0):
            break
        offset += PAGE_SIZE

    return jobs
