"""
LinkedIn job search scraper (Part 3c).

Uses a SECONDARY LinkedIn account (SCRAPER_LINKEDIN_USERNAME/PASSWORD) --
never Shiva's real one. Logs in once per run, searches, scrapes, logs out,
and clears cookies before exiting. Rate limited: 3-8s randomized delay
between every action.

LinkedIn's User Agreement prohibits automated access. This exists because
Shiva explicitly asked for it against a disposable account he accepts the
risk on (see CLAUDE.md). Regardless of that instruction, this code never
attempts to solve or bypass a CAPTCHA or identity checkpoint -- if LinkedIn
shows one, it stops immediately, logs out if possible, and reports it.
"""
import hashlib
import os
import random
import re
import time
import datetime

from playwright.sync_api import sync_playwright

LOGIN_URL = "https://www.linkedin.com/login"
SEARCH_URL = "https://www.linkedin.com/jobs/search/?keywords={kw}&location=United%20States&f_TPR=r86400"


class SecurityCheckpointError(Exception):
    """Raised when LinkedIn shows a CAPTCHA / identity verification wall.
    Never caught-and-bypassed -- always propagates so the run stops."""


def _sleep(min_s=3.0, max_s=8.0):
    time.sleep(random.uniform(min_s, max_s))


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _is_checkpoint(page) -> bool:
    url = page.url
    if "checkpoint" in url or "challenge" in url or "/authwall" in url:
        return True
    body_text = page.inner_text("body").lower()
    return any(s in body_text for s in [
        "let's do a quick security check", "verify your identity",
        "unusual activity", "enter the code",
    ])


def _login(page):
    username = os.environ["SCRAPER_LINKEDIN_USERNAME"]
    password = os.environ["SCRAPER_LINKEDIN_PASSWORD"]

    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    page.wait_for_selector('input[autocomplete="username"]', state="attached", timeout=15000)
    _sleep(2, 4)
    # LinkedIn's login form has no stable element IDs and duplicates its
    # markup (responsive layout) -- the FIRST DOM match is a hidden
    # duplicate and Playwright's :visible/is_visible() checks false-negative
    # on it, so match by accessible label and take the LAST match instead.
    page.get_by_label("Email or phone").last.fill(username)
    _sleep(1, 2)
    # get_by_label("Password") also matches the "Show password" eye-icon
    # button (aria-labelled with text containing "password") -- go straight
    # to the input via its autocomplete attribute instead.
    page.locator('input[autocomplete="current-password"]').last.fill(password)
    _sleep(1, 2)
    page.locator("button", has_text=re.compile(r"^Sign in$")).last.click()
    _sleep(4, 7)

    if _is_checkpoint(page):
        raise SecurityCheckpointError(
            "LinkedIn showed a security checkpoint / verification challenge "
            "during login. Stopping -- this tool never attempts to solve one."
        )


def _logout(page):
    """Best-effort clean logout. Never raises -- a failed logout shouldn't
    mask real scraping results, and the caller clears cookies regardless."""
    try:
        page.goto("https://www.linkedin.com/m/logout/", wait_until="domcontentloaded")
        _sleep(1, 2)
    except Exception:
        pass


CARD_SELECTOR = "li[data-occludable-job-id]"
DESCRIPTION_SELECTOR = "div.jobs-description__content"


def _extract_cards(page, max_cards: int) -> list[dict]:
    """Click each card (SPA nav, no full page reload -- confirmed by the URL
    gaining a currentJobId= param while staying on /jobs/search/) and pull
    the full JD from the detail panel that loads next to the list, so
    postings carry real description text instead of just a title."""
    cards = page.locator(CARD_SELECTOR)
    count = min(cards.count(), max_cards)
    results = []

    for i in range(count):
        card = cards.nth(i)
        try:
            job_id_attr = card.locator("div[data-job-id]").first.get_attribute("data-job-id")
            title_el = card.locator("a[href*='/jobs/view/']").first
            title = title_el.inner_text().split("\n")[0].strip()
            company = card.locator(".artdeco-entity-lockup__subtitle").first.inner_text().strip()
            location = card.locator(".artdeco-entity-lockup__caption").first.inner_text().strip()
            href = title_el.get_attribute("href") or ""
            url = f"https://www.linkedin.com{href.split('?')[0]}" if href.startswith("/") else href.split("?")[0]

            card.click()
            _sleep(2, 4)
            description = ""
            try:
                page.wait_for_selector(DESCRIPTION_SELECTOR, timeout=8000)
                description = page.locator(DESCRIPTION_SELECTOR).first.inner_text()
            except Exception:
                pass

            results.append({
                "title": title,
                "company": company,
                "location": location,
                "url": url,
                "job_id_attr": job_id_attr,
                "description": description,
            })
        except Exception:
            continue
        _sleep()

    return results


def fetch_jobs(keywords: list[str], max_keywords: int = 4, max_per_keyword: int = 15) -> list[dict]:
    """Log in once, search each keyword, scrape result cards, log out,
    clear cookies. Returns normalized job dicts (schema matches other
    sources: source/company/job_id/title/location/url/posted_at/
    description_html/discovered_at)."""
    if "SCRAPER_LINKEDIN_USERNAME" not in os.environ or "SCRAPER_LINKEDIN_PASSWORD" not in os.environ:
        raise KeyError("SCRAPER_LINKEDIN_USERNAME/PASSWORD not set")

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
            print("  [linkedin] logging in (secondary account)...")
            _login(page)
            print("  [linkedin] login ok")

            for kw in sample_keywords:
                print(f"  [linkedin] searching: {kw}")
                page.goto(SEARCH_URL.format(kw=kw.replace(" ", "%20")), wait_until="domcontentloaded")
                _sleep()
                if _is_checkpoint(page):
                    raise SecurityCheckpointError(
                        "LinkedIn showed a checkpoint mid-search. Stopping."
                    )

                cards = _extract_cards(page, max_per_keyword)
                for c in cards:
                    jobs.append({
                        "source": "linkedin",
                        "company": c["company"],
                        "job_id": f"li-{c['job_id_attr'] or hashlib.sha1(c['url'].encode()).hexdigest()[:10]}",
                        "title": c["title"],
                        "location": c["location"],
                        "url": c["url"],
                        "posted_at": "",  # LinkedIn shows relative time ("2 hours ago"),
                                          # not a parseable timestamp, on this view
                        "description_html": c["description"],
                        "discovered_at": _now_iso(),
                        "discovered_via": "linkedin_search",
                    })
                print(f"  [linkedin] {kw}: {len(cards)} card(s)")
                _sleep()

        finally:
            print("  [linkedin] logging out, clearing cookies...")
            _logout(page)
            context.clear_cookies()
            context.close()
            browser.close()

    return jobs
