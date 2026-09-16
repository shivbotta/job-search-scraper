#!/usr/bin/env python3
"""
Shiva's job search CLI. See CLAUDE.md for the full workflow.

Usage:
    python cli.py pull [--companies config/companies.yaml]
    python cli.py add-manual --url URL --text "..." [--title T] [--company C]
    python cli.py score [--job-id ID]
    python cli.py tailor --job-id ID
    python cli.py outreach --job-id ID
    python cli.py track --job-id ID --status STATUS [--notes "..."]
    python cli.py list [--min-score N]
"""
import argparse
import json
import os
import sys

import yaml
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from sources import greenhouse, lever, ashby, manual, workday  # noqa: E402
from scrapers import google_ats, linkedin, indeed  # noqa: E402
from scoring import deterministic, ai_scorer, bands  # noqa: E402
import geo  # noqa: E402
import dedupe  # noqa: E402
from datehelpers import parse_posted_at  # noqa: E402
import tailor as tailor_mod  # noqa: E402
import outreach as outreach_mod  # noqa: E402
import tracker  # noqa: E402
import dashboard as dashboard_mod  # noqa: E402

load_dotenv()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
JOBS_FILE = os.path.join(DATA_DIR, "jobs_seen.json")
TRACKER_FILE = os.path.join(DATA_DIR, "tracker.csv")
HIDDEN_FILE = os.path.join(DATA_DIR, "hidden.json")
PROFILE_FILE = os.path.join(os.path.dirname(__file__), "profile.json")
TAILORED_DIR = os.path.join(DATA_DIR, "tailored")


def load_profile():
    with open(PROFILE_FILE) as f:
        return json.load(f)


def load_jobs():
    if not os.path.exists(JOBS_FILE):
        return {}
    with open(JOBS_FILE) as f:
        return json.load(f)


def save_jobs(jobs: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(JOBS_FILE, "w") as f:
        json.dump(jobs, f, indent=2)


def cmd_pull(args):
    with open(args.companies) as f:
        companies = yaml.safe_load(f) or {}

    jobs = load_jobs()
    discovered = []

    for token in companies.get("greenhouse", []):
        try:
            discovered.extend(greenhouse.fetch_jobs(token))
        except Exception as e:
            print(f"  [warn] greenhouse/{token} failed: {e}")

    for token in companies.get("lever", []):
        try:
            discovered.extend(lever.fetch_jobs(token))
        except Exception as e:
            print(f"  [warn] lever/{token} failed: {e}")

    for token in companies.get("ashby", []):
        try:
            discovered.extend(ashby.fetch_jobs(token))
        except Exception as e:
            print(f"  [warn] ashby/{token} failed: {e}")

    for entry in companies.get("workday", []) or []:
        if not isinstance(entry, dict):
            continue  # commented-out reference entries parse as None/str, skip
        try:
            discovered.extend(workday.fetch_jobs(entry["tenant"], entry["wd"], entry["site"]))
        except Exception as e:
            print(f"  [warn] workday/{entry.get('tenant')} failed: {e}")

    new_count, duplicate_count, dropped_non_us = _merge_discovered(jobs, discovered)
    save_jobs(jobs)
    print(f"Pulled. {new_count} new postings, {duplicate_count} duplicate(s) merged, "
          f"{dropped_non_us} dropped (non-US). {len(jobs)} total tracked.")


def _merge_discovered(jobs: dict, discovered: list) -> tuple[int, int, int]:
    """Merge a list of newly-discovered postings into the jobs dict.

    Dedup happens on two levels (Part 3e): an exact job_id match (the same
    URL/source scraped twice), and a normalized company+title fingerprint
    match -- the SAME posting found via two different sources gets a
    different job_id format per source (e.g. "li-..." vs "gh-company-123")
    and would otherwise show up on the dashboard twice. On a fingerprint
    match, source lists are merged (so the dashboard can show "found on
    LinkedIn + Greenhouse") and the newer posted_at's data wins, since a
    later scrape of the same role usually has fresher/fuller info.

    Returns (new_count, duplicate_count, dropped_non_us)."""
    new_count = duplicate_count = dropped_non_us = 0
    fp_index = {
        dedupe.fingerprint(j.get("company", ""), j.get("title", "")): jid
        for jid, j in jobs.items()
    }

    for j in discovered:
        if not geo.is_us_location(j.get("location", "")):
            dropped_non_us += 1
            continue

        existing = jobs.get(j["job_id"])
        if not existing:
            fp = dedupe.fingerprint(j.get("company", ""), j.get("title", ""))
            existing_id = fp_index.get(fp)
            if existing_id:
                existing = jobs[existing_id]

        if existing:
            duplicate_count += 1
            sources = set(existing.get("also_found_on", [existing.get("source")]))
            sources.add(j["source"])
            existing["also_found_on"] = sorted(sources)
            existing["duplicate"] = len(sources) > 1

            new_posted = parse_posted_at(j.get("posted_at"))
            old_posted = parse_posted_at(existing.get("posted_at"))
            if new_posted and (not old_posted or new_posted > old_posted):
                merged = {**j, "job_id": existing["job_id"],
                          "also_found_on": existing["also_found_on"],
                          "duplicate": existing["duplicate"]}
                jobs[existing["job_id"]] = merged
        else:
            jobs[j["job_id"]] = j
            fp_index[dedupe.fingerprint(j.get("company", ""), j.get("title", ""))] = j["job_id"]
            new_count += 1
    return new_count, duplicate_count, dropped_non_us


def cmd_scrape(args):
    profile = load_profile()
    jobs = load_jobs()
    total_new = total_dup = total_dropped = 0

    print("Discovering via Google site: search "
          "(Greenhouse/Lever/Ashby/Workday/SmartRecruiters/Workable)...")
    try:
        discovered = google_ats.fetch_jobs(profile, max_queries=args.max_queries)
    except KeyError:
        print("  [error] ANTHROPIC_API_KEY not set -- google_ats needs it for web search")
        discovered = []
    n, d, u = _merge_discovered(jobs, discovered)
    total_new += n
    total_dup += d
    total_dropped += u
    print(f"  google_ats: {n} new, {d} duplicate, {u} dropped (non-US)")

    keyword_pool = google_ats._build_keyword_pool(profile)

    if not args.skip_linkedin:
        print("Searching LinkedIn (secondary account)...")
        try:
            discovered = linkedin.fetch_jobs(keyword_pool)
            n, d, u = _merge_discovered(jobs, discovered)
            total_new += n
            total_dup += d
            total_dropped += u
            print(f"  linkedin: {n} new, {d} duplicate, {u} dropped (non-US)")
        except KeyError:
            print("  [skip] SCRAPER_LINKEDIN_USERNAME/PASSWORD not set")
        except linkedin.SecurityCheckpointError as e:
            print(f"  [stopped] {e}")
        except Exception as e:
            print(f"  [warn] linkedin scrape failed: {e}")

    if not args.skip_indeed:
        print("Searching Indeed (secondary account)...")
        try:
            discovered = indeed.fetch_jobs(keyword_pool)
            n, d, u = _merge_discovered(jobs, discovered)
            total_new += n
            total_dup += d
            total_dropped += u
            print(f"  indeed: {n} new, {d} duplicate, {u} dropped (non-US)")
        except KeyError:
            print("  [skip] SCRAPER_INDEED_USERNAME/PASSWORD not set")
        except indeed.SecurityCheckpointError as e:
            print(f"  [stopped] {e}")
        except Exception as e:
            print(f"  [warn] indeed scrape failed: {e}")

    save_jobs(jobs)
    print(f"Scrape complete. {total_new} new posting(s), {total_dup} duplicate(s) seen again, "
          f"{total_dropped} dropped (non-US). {len(jobs)} total tracked.")


def cmd_add_manual(args):
    jobs = load_jobs()
    j = manual.add_manual_job(args.url, args.text, args.title or "", args.company or "")
    jobs[j["job_id"]] = j
    save_jobs(jobs)
    print(f"Added manual job {j['job_id']}. Fill in title/company in data/jobs_seen.json if left blank.")


def cmd_score(args):
    profile = load_profile()
    jobs = load_jobs()
    targets = [args.job_id] if args.job_id else list(jobs.keys())

    for jid in targets:
        job = jobs.get(jid)
        if not job:
            print(f"  [skip] {jid} not found")
            continue

        det = deterministic.score_job(job, profile)
        job["deterministic_score"] = det

        try:
            ai = ai_scorer.score_job(job, profile)
            job["ai_score"] = ai
        except KeyError:
            print("  [warn] ANTHROPIC_API_KEY not set -- skipping AI scoring")
            ai = None
        except Exception as e:
            print(f"  [warn] AI scoring failed for {jid}: {e}")
            ai = None

        jobs[jid] = job
        band_score = ai["fit_score"] if ai and ai.get("fit_score") is not None else det["composite_score"]
        band = bands.score_band(band_score)
        det_line = f"det={det['composite_score']} ({det['best_track']})"
        ai_line = f"ai={ai['fit_score']}" if ai and ai.get("fit_score") is not None else "ai=n/a"
        print(f"{jid[:36]:36s} {job.get('title','')[:32]:32s} {det_line:26s} {ai_line:8s} [{band}]")

    save_jobs(jobs)


def cmd_tailor(args):
    profile = load_profile()
    jobs = load_jobs()
    job = jobs.get(args.job_id)
    if not job:
        print(f"Job {args.job_id} not found. Run `list` to see known job IDs.")
        return

    job_dir = os.path.join(TAILORED_DIR, args.job_id)
    os.makedirs(job_dir, exist_ok=True)
    pdf_path = os.path.join(job_dir, "resume.pdf")

    result = tailor_mod.tailor_resume(job, profile, pdf_out_path=pdf_path)
    ai_score = (job.get("ai_score") or {}).get("fit_score")
    det_score = (job.get("deterministic_score") or {}).get("composite_score")
    result["job_score"] = ai_score if ai_score is not None else det_score
    result["job_title"] = job.get("title")
    result["job_company"] = job.get("company")
    report_path = os.path.join(job_dir, "report.json")
    with open(report_path, "w") as f:
        json.dump(result, f, indent=2)

    if result.get("_standing_rules_violations"):
        print(f"  [WARNING] {result['_WARNING']}")
        print(f"Report written to {report_path} (no PDF -- standing rules violation)")
        return

    print(f"Baseline coverage: {result['baseline_coverage_pct']}% -> "
          f"Tailored coverage: {result.get('tailored_coverage_pct', '?')}%")
    if result.get("honest_gaps"):
        print(f"Honest gaps ({len(result['honest_gaps'])}): {', '.join(result['honest_gaps'][:3])}"
              + (" ..." if len(result["honest_gaps"]) > 3 else ""))
    print(f"PDF: {pdf_path}")
    print(f"Report: {report_path}")


def cmd_outreach(args):
    profile = load_profile()
    jobs = load_jobs()
    job = jobs.get(args.job_id)
    if not job:
        print(f"Job {args.job_id} not found.")
        return

    result = outreach_mod.build_outreach_brief(job, profile)
    print(json.dumps(result, indent=2))


def cmd_track(args):
    jobs = load_jobs()
    job = jobs.get(args.job_id, {})

    if args.status == "applied" and job:
        # Marking applied also hides same-company/same-role postings from the
        # dashboard until that role is reposted -- see src/hidden.py.
        tracker.mark_applied(TRACKER_FILE, HIDDEN_FILE, job)
    else:
        det = job.get("deterministic_score", {})
        ai = job.get("ai_score", {})
        tracker.upsert(
            TRACKER_FILE,
            args.job_id,
            company=job.get("company"),
            title=job.get("title"),
            url=job.get("url"),
            track=det.get("best_track"),
            det_score=det.get("composite_score"),
            ai_score=ai.get("fit_score"),
            status=args.status,
            notes=args.notes,
        )
    print(f"Tracked {args.job_id} as '{args.status}'")


def cmd_applied(args):
    if not os.path.exists(TRACKER_FILE):
        print("No applications tracked yet.")
        return
    import csv
    with open(TRACKER_FILE, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "applied"]
    if not rows:
        print("No applications tracked yet.")
        return
    rows.sort(key=lambda r: r["last_updated"], reverse=True)
    for r in rows:
        print(f"{r['job_id'][:38]:38s} {r['title'][:28]:28s} {r['company'][:18]:18s} "
              f"applied {r['last_updated']}  {r['url']}")


def cmd_dashboard(args):
    jobs = load_jobs()
    profile = load_profile()
    sources_status = {"google site: search": True, "Greenhouse/Lever/Ashby/Workday": True,
                       "LinkedIn": True, "Indeed": True}
    feed_html = dashboard_mod.render_feed_tab(jobs, HIDDEN_FILE, TRACKER_FILE, sources_status)
    applied_html = dashboard_mod.render_applied_tab(TRACKER_FILE)
    skills_gap_html = dashboard_mod.render_skills_gap_tab(TAILORED_DIR)
    profile_html = dashboard_mod.render_profile_tab(profile)
    html_out = dashboard_mod.render_app_html(feed_html, applied_html, skills_gap_html, profile_html)
    out_path = os.path.join(DATA_DIR, "dashboard.html")
    with open(out_path, "w") as f:
        f.write(html_out)
    print(f"Static snapshot written to {out_path}")
    print("For the interactive version (Mark Applied, Research+Tailor, profile edits):")
    print("  python server.py")
    print("  then open http://localhost:9009")


def cmd_list(args):
    jobs = load_jobs()
    rows = []
    for jid, job in jobs.items():
        det = job.get("deterministic_score", {}).get("composite_score", -1)
        ai = job.get("ai_score", {}).get("fit_score", -1)
        rows.append((jid, job.get("title", ""), job.get("company", ""), det, ai))

    rows.sort(key=lambda r: (r[3] if r[3] is not None else -1), reverse=True)
    for jid, title, company, det, ai in rows:
        if args.min_score and (det or 0) < args.min_score:
            continue
        print(f"{jid[:40]:40s} {title[:30]:30s} {company[:20]:20s} det={det} ai={ai}")


def main():
    p = argparse.ArgumentParser(description="Shiva's job search CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pull")
    sp.add_argument("--companies", default="config/companies.yaml")
    sp.set_defaults(func=cmd_pull)

    sp = sub.add_parser("scrape", help="Discover fresh postings from all sources")
    sp.add_argument("--max-queries", type=int, default=8)
    sp.add_argument("--skip-linkedin", action="store_true")
    sp.add_argument("--skip-indeed", action="store_true")
    sp.set_defaults(func=cmd_scrape)

    sp = sub.add_parser("add-manual")
    sp.add_argument("--url", required=True)
    sp.add_argument("--text", required=True)
    sp.add_argument("--title")
    sp.add_argument("--company")
    sp.set_defaults(func=cmd_add_manual)

    sp = sub.add_parser("score")
    sp.add_argument("--job-id")
    sp.set_defaults(func=cmd_score)

    sp = sub.add_parser("tailor")
    sp.add_argument("--job-id", required=True)
    sp.add_argument("--format", choices=["pdf"], default="pdf",
                     help="PDF only, per Shiva's decision -- no DOCX")
    sp.set_defaults(func=cmd_tailor)

    sp = sub.add_parser("outreach")
    sp.add_argument("--job-id", required=True)
    sp.set_defaults(func=cmd_outreach)

    sp = sub.add_parser("track")
    sp.add_argument("--job-id", required=True)
    sp.add_argument("--status", required=True,
                     choices=["scored", "applied", "screening", "interview", "rejected", "offer"])
    sp.add_argument("--notes", default="")
    sp.set_defaults(func=cmd_track)

    sp = sub.add_parser("list")
    sp.add_argument("--min-score", type=int)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("applied", help="Show every job you've marked applied")
    sp.set_defaults(func=cmd_applied)

    sp = sub.add_parser("dashboard", help="Write a static dashboard snapshot to data/dashboard.html")
    sp.set_defaults(func=cmd_dashboard)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
