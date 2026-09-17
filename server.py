#!/usr/bin/env python3
"""
Local dashboard server (Part 8).

Run: python server.py
Then open http://localhost:9009 -- refresh any time after running
`python cli.py scrape && python cli.py score`.

Runs on localhost only. Every route that writes state only ever touches
this project's own local files (data/jobs_seen.json, tracker.csv,
hidden.json, profile.json, data/tailored/) -- it never touches LinkedIn,
Indeed, Gmail, or any external service.
"""
import json
import os
import sys

from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
import dashboard as dashboard_mod  # noqa: E402
import tracker  # noqa: E402
import outreach  # noqa: E402
import tailor as tailor_mod  # noqa: E402
import profile_updates  # noqa: E402

load_dotenv()

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
JOBS_FILE = os.path.join(DATA_DIR, "jobs_seen.json")
TRACKER_FILE = os.path.join(DATA_DIR, "tracker.csv")
HIDDEN_FILE = os.path.join(DATA_DIR, "hidden.json")
TAILORED_DIR = os.path.join(DATA_DIR, "tailored")
PROFILE_FILE = os.path.join(os.path.dirname(__file__), "profile.json")

app = Flask(__name__)


def load_jobs():
    if not os.path.exists(JOBS_FILE):
        return {}
    with open(JOBS_FILE) as f:
        return json.load(f)


def save_jobs(jobs: dict):
    with open(JOBS_FILE, "w") as f:
        json.dump(jobs, f, indent=2)


def load_profile():
    with open(PROFILE_FILE) as f:
        return json.load(f)


def _sources_status() -> dict:
    """No persistent health-check log exists yet -- this is an honest proxy
    based on whether each source's required credentials are configured,
    not a live ping. Good enough for the daily brief's "sources live" line
    without building a separate tracking system for it."""
    return {
        "google site: search": "ANTHROPIC_API_KEY" in os.environ,
        "Greenhouse/Lever/Ashby/Workday": True,  # no credentials needed
        "LinkedIn": bool(os.environ.get("SCRAPER_LINKEDIN_USERNAME") and os.environ.get("SCRAPER_LINKEDIN_PASSWORD")),
        "Indeed": bool(os.environ.get("SCRAPER_INDEED_USERNAME") and os.environ.get("SCRAPER_INDEED_PASSWORD")),
    }


@app.route("/")
def index():
    jobs = load_jobs()
    profile = load_profile()
    feed_html = dashboard_mod.render_feed_tab(jobs, HIDDEN_FILE, TRACKER_FILE, _sources_status())
    applied_html = dashboard_mod.render_applied_tab(TRACKER_FILE)
    skills_gap_html = dashboard_mod.render_skills_gap_tab(TAILORED_DIR)
    profile_html = dashboard_mod.render_profile_tab(profile)
    return dashboard_mod.render_app_html(feed_html, applied_html, skills_gap_html, profile_html)


@app.route("/api/feed/more")
def api_feed_more():
    """Serves both pagination and filtering -- a filter change re-requests
    offset 0 with source/industry set and replaces the bucket's list."""
    bucket = request.args.get("bucket", "")
    offset = request.args.get("offset", type=int, default=0)
    source = request.args.get("source", "")
    industry = request.args.get("industry", "")
    result = dashboard_mod.render_more_cards(
        load_jobs(), HIDDEN_FILE, bucket, offset, source=source, industry=industry
    )
    return jsonify(result)


@app.route("/api/apply/<job_id>", methods=["POST"])
def api_apply(job_id):
    jobs = load_jobs()
    job = jobs.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404
    tracker.mark_applied(TRACKER_FILE, HIDDEN_FILE, job)
    return jsonify({"ok": True})


@app.route("/api/applied/<job_id>", methods=["POST"])
def api_update_applied(job_id):
    body = request.get_json(force=True, silent=True) or {}
    fields = {k: v for k, v in body.items() if k in ("status", "notes")}
    if not fields:
        return jsonify({"ok": False, "error": "no valid fields"}), 400
    tracker.upsert(TRACKER_FILE, job_id, **fields)
    return jsonify({"ok": True})


@app.route("/api/research-tailor/<job_id>", methods=["POST"])
def api_research_tailor(job_id):
    jobs = load_jobs()
    job = jobs.get(job_id)
    if not job:
        return jsonify({"ok": False, "error": "job not found"}), 404
    profile = load_profile()

    try:
        research = outreach.build_outreach_brief(job, profile)
    except Exception as e:
        research = {"error": str(e)}

    job_dir = os.path.join(TAILORED_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    pdf_path = os.path.join(job_dir, "resume.pdf")
    try:
        tailor_result = tailor_mod.tailor_resume(job, profile, pdf_out_path=pdf_path)
        ai_score = (job.get("ai_score") or {}).get("fit_score")
        det_score = (job.get("deterministic_score") or {}).get("composite_score")
        tailor_result["job_score"] = ai_score if ai_score is not None else det_score
        tailor_result["job_title"] = job.get("title")
        tailor_result["job_company"] = job.get("company")
        with open(os.path.join(job_dir, "report.json"), "w") as f:
            json.dump(tailor_result, f, indent=2)
        if tailor_result.get("pdf_path"):
            tailor_result["pdf_url"] = f"/tailored/{job_id}/resume.pdf"
    except Exception as e:
        tailor_result = {"error": str(e)}

    # If research found a company brief, cache it onto the job record so the
    # card can show it without re-running research every page load.
    if research.get("company_brief"):
        job["company_brief"] = research["company_brief"]
        jobs[job_id] = job
        save_jobs(jobs)

    return jsonify({"ok": True, "research": research, "tailor": tailor_result})


@app.route("/tailored/<job_id>/resume.pdf")
def serve_resume(job_id):
    return send_from_directory(os.path.join(TAILORED_DIR, job_id), "resume.pdf")


@app.route("/api/profile/skill", methods=["POST"])
def api_add_skill():
    body = request.get_json(force=True, silent=True) or {}
    if not body.get("group") or not body.get("skill"):
        return jsonify({"ok": False, "error": "group and skill required"}), 400
    profile_updates.add_skill(PROFILE_FILE, body["group"], body["skill"])
    return jsonify({"ok": True})


@app.route("/api/profile/cert", methods=["POST"])
def api_add_cert():
    body = request.get_json(force=True, silent=True) or {}
    if not body.get("name"):
        return jsonify({"ok": False, "error": "name required"}), 400
    profile_updates.add_certification(PROFILE_FILE, body["name"])
    return jsonify({"ok": True})


@app.route("/api/profile/project", methods=["POST"])
def api_add_project():
    body = request.get_json(force=True, silent=True) or {}
    if not body.get("name") or not body.get("description"):
        return jsonify({"ok": False, "error": "name and description required"}), 400
    profile_updates.add_project(PROFILE_FILE, body["name"], body["description"], body.get("link", ""))
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("Dashboard running at http://localhost:9009")
    app.run(port=9009, debug=False)
