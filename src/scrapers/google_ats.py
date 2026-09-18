"""
Google `site:` search discovery scraper (Part 3b).

The highest-leverage source: reaches every company on Greenhouse, Lever,
Ashby, Workday, SmartRecruiters, and Workable -- not just the ones
enumerated by hand in config/companies.yaml. It works by asking Claude's
server-side web search tool (same ANTHROPIC_API_KEY already used for
scoring/tailoring -- no separate search API key needed) to search each ATS
domain for postings matching Shiva's target-track keywords.

Every hit is re-fetched through a structured public API in src/sources/
so the record has a real posted_at, location, and full JD text -- the
search hit is only used to *discover the company* (a board token, or
tenant/site for Workday), never as the job data itself.

SmartRecruiters and Workable used to be page-scraped instead, which
captured no location, so the US filter silently dropped every one of those
postings. Both now go through their public APIs like the rest.

Read-only. No login, anywhere. Rate limited: 3-8s randomized delay between
every outbound request, exponential backoff on errors.
"""
import os
import random
import re
import time
import datetime

import anthropic

from sources import greenhouse, lever, ashby, workday, smartrecruiters, workable

MODEL = "claude-sonnet-4-6"

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
    "smartrecruiters.com": smartrecruiters.fetch_jobs,
    "apply.workable.com": workable.fetch_jobs,
}

# Pulls the company token out of a matched URL.
TOKEN_PATTERNS = {
    "boards.greenhouse.io": re.compile(r"boards\.greenhouse\.io/([^/?#]+)"),
    "jobs.lever.co": re.compile(r"jobs\.lever\.co/([^/?#]+)"),
    "jobs.ashbyhq.com": re.compile(r"jobs\.ashbyhq\.com/([^/?#]+)"),
    # SmartRecruiters also serves "oneclick-ui/company/<Token>/..." apply URLs.
    "smartrecruiters.com": re.compile(r"smartrecruiters\.com/(?:oneclick-ui/company/)?([^/?#]+)"),
    # apply.workable.com/j/<shortcode> carries no account slug -- skip those.
    "apply.workable.com": re.compile(r"apply\.workable\.com/(?!j/)([^/?#]+)"),
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


def fetch_jobs(profile: dict, max_queries: int = 8, keywords_per_query: int = 4) -> list[dict]:
    """Run the discovery scraper end to end. Returns normalized job dicts;
    relevance/excluded-track filtering happens at merge time in cli.py
    (src/relevance.py), the same gate every other source goes through."""
    headers = {}
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if workspace_id:
        headers["anthropic-workspace-id"] = workspace_id
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], default_headers=headers)
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

        if platform == "myworkdayjobs.com":
            parsed = workday.parse_workday_url(url)
            if not parsed:
                continue
            tenant, wd, site = parsed
            key = (platform, tenant, wd, site)
            if key in seen_tokens:
                continue
            seen_tokens.add(key)
            try:
                company_jobs = workday.fetch_jobs(tenant, wd, site)
                for j in company_jobs:
                    j["discovered_at"] = _now_iso()
                    j["discovered_via"] = f"google_ats:{platform}"
                jobs.extend(company_jobs)
                print(f"  [ok] workday/{tenant}: {len(company_jobs)} posting(s)")
            except Exception as e:
                print(f"  [warn] google_ats: workday/{tenant} fetch failed: {e}")
            _sleep()
        elif fetcher:
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

    return jobs
