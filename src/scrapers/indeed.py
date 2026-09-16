"""
Indeed job search scraper (Part 3c).

Same posture as linkedin.py: secondary account only (SCRAPER_INDEED_USERNAME/
PASSWORD), rate limited, logs out and clears cookies when done, and never
attempts to solve a CAPTCHA or verification challenge -- stops and reports
instead.

KNOWN LIMITATION, confirmed live: unlike LinkedIn (which let this same
secondary account log in cleanly), Indeed serves an image CAPTCHA
("Select all squares with...") right after the email step, before a
password is even entered -- on the very first automated login attempt.
This isn't a selector bug to fix; it's Indeed's bot detection working as
intended against a fresh automated browser. fetch_jobs() will reliably
raise SecurityCheckpointError here rather than hang or silently fail.
"""
import hashlib
import os
import random
import time
import datetime

from playwright.sync_api import sync_playwright

LOGIN_URL = "https://secure.indeed.com/auth"
SEARCH_URL = "https://www.indeed.com/jobs?q={kw}&l=United+States&fromage=1"


class SecurityCheckpointError(Exception):
    """Raised on a CAPTCHA / verification wall. Never bypassed."""


def _sleep(min_s=3.0, max_s=8.0):
    time.sleep(random.uniform(min_s, max_s))


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _is_checkpoint(page) -> bool:
    """Detects Indeed's CAPTCHA/verification walls. Confirmed live: a fresh
    automated login on a secondary account triggers an image CAPTCHA
    ("Select all squares with...") right after the email step, before a
    password is even entered. This is never solved -- callers must stop the
    moment this returns True."""
    url = page.url
    if "challenge" in url or "verify" in url:
        return True
    if page.query_selector("iframe[src*='recaptcha'], iframe[title*='recaptcha' i]"):
        return True
    body_text = page.inner_text("body").lower()
    return any(s in body_text for s in [
        "verify you are a human", "additional verification required",
        "unusual traffic", "select all squares", "select all images",
    ])


def _login(page):
    username = os.environ["SCRAPER_INDEED_USERNAME"]
    password = os.environ["SCRAPER_INDEED_PASSWORD"]

    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    _sleep(2, 4)
    page.fill("input[name='__email']", username)
    _sleep(1, 2)
    page.click("button[data-tn-element='auth-page-email-submit-button']")
    _sleep(3, 5)

    if _is_checkpoint(page):
        raise SecurityCheckpointError(
            "Indeed showed a CAPTCHA/verification challenge right after the "
            "email step -- confirmed live on this account. Stopping; this "
            "tool never attempts to solve one."
        )

    page.fill("input[type='password']", password)
    _sleep(1, 2)
    page.click("button[type='submit']")
    _sleep(4, 7)

    if _is_checkpoint(page):
        raise SecurityCheckpointError("Indeed showed a verification challenge after password step.")


def _logout(page):
    try:
        page.goto("https://secure.indeed.com/account/logout", wait_until="domcontentloaded")
        _sleep(1, 2)
    except Exception:
        pass


def _extract_cards(page) -> list[dict]:
    cards = page.query_selector_all("div.job_seen_beacon, td.resultContent")
    results = []
    for card in cards:
        try:
            title_el = card.query_selector("h2.jobTitle span, a.jcs-JobTitle span")
            company_el = card.query_selector("span.companyName")
            location_el = card.query_selector("div.companyLocation")
            link_el = card.query_selector("a.jcs-JobTitle, h2.jobTitle a")
            snippet_el = card.query_selector("div.job-snippet")

            href = link_el.get_attribute("href") if link_el else None
            if not href:
                continue
            url = href if href.startswith("http") else f"https://www.indeed.com{href}"
            results.append({
                "title": (title_el.inner_text().strip() if title_el else ""),
                "company": (company_el.inner_text().strip() if company_el else ""),
                "location": (location_el.inner_text().strip() if location_el else ""),
                "url": url.split("&")[0],
                "snippet": (snippet_el.inner_text().strip() if snippet_el else ""),
            })
        except Exception:
            continue
    return results


def fetch_jobs(keywords: list[str], max_keywords: int = 4, max_per_keyword: int = 25) -> list[dict]:
    if "SCRAPER_INDEED_USERNAME" not in os.environ or "SCRAPER_INDEED_PASSWORD" not in os.environ:
        raise KeyError("SCRAPER_INDEED_USERNAME/PASSWORD not set")

    sample_keywords = random.sample(keywords, min(max_keywords, len(keywords)))
    jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
        )
        page = context.new_page()

        try:
            print("  [indeed] logging in (secondary account)...")
            _login(page)
            print("  [indeed] login ok")

            for kw in sample_keywords:
                print(f"  [indeed] searching: {kw}")
                page.goto(SEARCH_URL.format(kw=kw.replace(" ", "+")), wait_until="domcontentloaded")
                _sleep()
                if _is_checkpoint(page):
                    raise SecurityCheckpointError("Indeed showed a checkpoint mid-search.")

                cards = _extract_cards(page)[:max_per_keyword]
                for c in cards:
                    jobs.append({
                        "source": "indeed",
                        "company": c["company"],
                        "job_id": f"in-{hashlib.sha1(c['url'].encode()).hexdigest()[:10]}",
                        "title": c["title"],
                        "location": c["location"],
                        "url": c["url"],
                        "posted_at": "",
                        "description_html": c["snippet"],
                        "discovered_at": _now_iso(),
                        "discovered_via": "indeed_search",
                    })
                print(f"  [indeed] {kw}: {len(cards)} card(s)")
                _sleep()

        finally:
            print("  [indeed] logging out, clearing cookies...")
            _logout(page)
            context.clear_cookies()
            context.close()
            browser.close()

    return jobs
