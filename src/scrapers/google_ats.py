"""
Google `site:` search discovery scraper (Part 3b).

The highest-leverage source: reaches every company on Greenhouse, Lever,
Ashby, Workday, SmartRecruiters, and Workable -- not just the ones
enumerated by hand in config/companies.yaml. It works by asking Claude's
server-side web search tool (same ANTHROPIC_API_KEY already used for
scoring/tailoring -- no separate search API key needed) to search each ATS
domain for postings matching Shiva's target-track keywords.

For hits on Greenhouse/Lever/Ashby we re-fetch the company's full board
through the existing structured API modules (src/sources/*) so the record
has real posted_at, location, and full JD text -- the search hit is only
used to *discover the company token*, never as the job data itself. For
Workday/SmartRecruiters/Workable there's no simple public API, so the
posting page itself is fetched once (no login) for the JD text.

Read-only. No login, anywhere. Rate limited: 3-8s randomized delay between
every outbound request, exponential backoff on errors.
"""
import hashlib
import os
import random
import re
import time
import datetime

import requests
import anthropic

from sources import greenhouse, lever, ashby

MODEL = "claude-sonnet-4-6"

# Domains searched. Greenhouse/Lever/Ashby hits get re-fetched through the
# structured public APIs already in src/sources/; the rest are fetched as
# plain pages since they have no simple public JSON feed.
ATS_PLATFORMS = [
    "boards.greenhouse.io",
    "jobs.lever.co",
    "jobs.ashbyhq.com",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "apply.workable.com",
]

STRUCTURED_FETCHERS = {
    "boards.greenhouse.io": greenhouse.fetch_jobs,
    "jobs.lever.co": lever.fetch_jobs,
    "jobs.ashbyhq.com": ashby.fetch_jobs,
}

# Pulls the company token out of a matched URL for platforms with a
# structured fetcher above.
TOKEN_PATTERNS = {
    "boards.greenhouse.io": re.compile(r"boards\.greenhouse\.io/([^/?#]+)"),
    "jobs.lever.co": re.compile(r"jobs\.lever\.co/([^/?#]+)"),
    "jobs.ashbyhq.com": re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)"),
}


def _sleep(min_s=3.0, max_s=8.0):
    time.sleep(random.uniform(min_s, max_s))


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _build_keyword_pool(profile: dict) -> list[str]:
    keywords = []
    for track in profile.get("target_tracks", []):
        keywords.extend(track.get("keywords", []))
    seen = set()
    uniq = []
    for k in keywords:
        lk = k.lower()
        if lk not in seen:
            seen.add(lk)
            uniq.append(k)
    return uniq


def _search_platform(client: "anthropic.Anthropic", platform: str, sample_keywords: list[str],
                      max_retries: int = 3) -> list[dict]:
    """Search one ATS domain via Claude's web_search tool. Returns raw hits
    (url, title). Retries with exponential backoff on transient errors."""
    query_desc = " OR ".join(f'"{k}"' for k in sample_keywords)
    delay = 5.0
    for attempt in range(max_retries):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=1024,
                tools=[{
                    "type": "web_search_20250305",
                    "name": "web_search",
                    "max_uses": 3,
                    "allowed_domains": [platform],
                }],
                messages=[{
                    "role": "user",
                    "content": (
                        f"Search {platform} for open job postings matching any of: "
                        f"{query_desc}. Posted recently preferred. Just search, "
                        "don't write a summary."
                    ),
                }],
            )
            hits = []
            for block in resp.content:
                if getattr(block, "type", None) == "web_search_tool_result":
                    content = block.content
                    if isinstance(content, list):
                        for item in content:
                            url = getattr(item, "url", None)
                            title = getattr(item, "title", None)
                            if url:
                                hits.append({"url": url, "title": title or ""})
            return hits
        except anthropic.APIStatusError as e:
            if e.status_code == 429 and attempt < max_retries - 1:
                print(f"  [warn] google_ats: rate limited on {platform}, backing off {delay:.0f}s")
                time.sleep(delay)
                delay *= 3
                continue
            print(f"  [warn] google_ats: search failed for {platform}: {e}")
            return []
        except Exception as e:
            print(f"  [warn] google_ats: search failed for {platform}: {e}")
            return []
    return []


def _is_excluded(title: str, excluded_keywords: list[str]) -> bool:
    low = (title or "").lower()
    return any(ek.lower() in low for ek in excluded_keywords)


def _guess_company_from_url(platform: str, url: str) -> str:
    """Pull the actual employer name out of a Workday/SmartRecruiters/Workable
    URL. The company sits in different places per platform, so a generic
    "last label before .com" regex would just return the platform's own
    name (e.g. "myworkdayjobs") for every hit -- it has to be per-platform."""
    if platform == "myworkdayjobs.com":
        # <company>.wd#.myworkdayjobs.com/...
        m = re.search(r"://([^.]+)\.wd\d+\.myworkdayjobs\.com", url)
        return m.group(1) if m else url
    # smartrecruiters.com/<Company>/... and workable.com/<company>/...
    m = re.search(r"://[^/]+/([^/]+)/", url)
    return m.group(1) if m else url


def fetch_jobs(profile: dict, max_queries: int = 8, keywords_per_query: int = 4) -> list[dict]:
    """Run the discovery scraper end to end. Returns normalized job dicts
    ready to merge into data/jobs_seen.json, with excluded tracks already
    dropped per the standing rule (never surface IT Support/SOC/etc.)."""
    headers = {}
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if workspace_id:
        headers["anthropic-workspace-id"] = workspace_id
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], default_headers=headers)
    excluded_keywords = profile.get("excluded_tracks", {}).get("never_target", [])
    keyword_pool = _build_keyword_pool(profile)

    queries = []
    for i in range(max_queries):
        platform = ATS_PLATFORMS[i % len(ATS_PLATFORMS)]
        sample = random.sample(keyword_pool, min(keywords_per_query, len(keyword_pool)))
        queries.append((platform, sample))

    discovered = {}  # url -> {"platform": ..., "title": ...}
    for platform, sample in queries:
        print(f"  [search] site:{platform} ({' OR '.join(sample)})")
        for hit in _search_platform(client, platform, sample):
            discovered.setdefault(hit["url"], {"platform": platform, "title": hit["title"]})
        _sleep()

    print(f"  [info] {len(discovered)} unique URLs discovered across {len(queries)} queries")

    jobs = []
    seen_tokens = set()
    for url, meta in discovered.items():
        platform = meta["platform"]
        fetcher = STRUCTURED_FETCHERS.get(platform)

        if fetcher:
            token_pat = TOKEN_PATTERNS[platform]
            m = token_pat.search(url)
            if not m:
                continue
            token = m.group(1)
            key = (platform, token)
            if key in seen_tokens:
                continue
            seen_tokens.add(key)
            try:
                company_jobs = fetcher(token)
                for j in company_jobs:
                    j["discovered_at"] = _now_iso()
                    j["discovered_via"] = f"google_ats:{platform}"
                jobs.extend(company_jobs)
                print(f"  [ok] {platform}/{token}: {len(company_jobs)} posting(s)")
            except Exception as e:
                print(f"  [warn] google_ats: {platform}/{token} fetch failed: {e}")
            _sleep()
        else:
            # No simple public API (Workday/SmartRecruiters/Workable) --
            # fetch the posting page itself, once, no login.
            try:
                resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                jobs.append({
                    "source": "google_ats",
                    "company": _guess_company_from_url(platform, url),
                    "job_id": f"gats-{hashlib.sha1(url.encode()).hexdigest()[:10]}",
                    "title": meta["title"],
                    "location": "",
                    "url": url,
                    "posted_at": "",
                    "description_html": resp.text[:20000],
                    "discovered_at": _now_iso(),
                    "discovered_via": f"google_ats:{platform}",
                })
                print(f"  [ok] {platform}: fetched 1 posting page ({url})")
            except Exception as e:
                print(f"  [warn] google_ats: page fetch failed for {url}: {e}")
            _sleep()

    filtered = [j for j in jobs if not _is_excluded(j.get("title", ""), excluded_keywords)]
    dropped = len(jobs) - len(filtered)
    if dropped:
        print(f"  [info] dropped {dropped} posting(s) matching excluded_tracks.never_target")

    return filtered
