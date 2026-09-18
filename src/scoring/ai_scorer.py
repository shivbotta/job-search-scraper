"""
AI-based job fit scoring via the Claude API.

Complements deterministic.py -- this one reasons about fit qualitatively
(seniority mismatch, culture signals, career trajectory) rather than just
counting keywords. Always shown side by side with the deterministic score,
never in place of it. Requires ANTHROPIC_API_KEY in the environment.

score_job() is a single synchronous call (used for one-off scoring, e.g.
Research + Tailor on a single card). score_jobs_concurrently() is the bulk
path: it fires many requests in flight at once via AsyncAnthropic + a
semaphore, instead of awaiting each one before starting the next. At ~1
job/sec sequentially, 2000 jobs is a 30+ hour run; bounded concurrency
turns the same 2000 jobs into a few minutes, limited by the semaphore size
rather than round-trip latency.
"""
import asyncio
import json
import os
import re
import time
from html import unescape

import anthropic

MODEL = "claude-sonnet-4-6"  # update if a newer default model is preferred

DEFAULT_CONCURRENCY = 15


def _clean_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _build_messages(job: dict, profile: dict) -> tuple[str, str]:
    posting_text = _clean_text(job.get("description_html", ""))[:6000]

    system = (
        "You are a blunt, honest career analyst scoring one job posting against "
        "one candidate's real profile. Do not inflate scores to be encouraging. "
        "Most postings should NOT score 80+; reserve high scores for genuine "
        "strong matches. Respond with ONLY valid JSON, no prose, no markdown fences."
    )

    user = f"""
CANDIDATE PROFILE (JSON):
{json.dumps(profile, indent=2)}

JOB POSTING:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Location: {job.get('location', '')}
Description:
{posting_text}

Score this posting's fit for the candidate on a 0-100 scale. Return JSON with
exactly these keys:
{{
  "fit_score": <int 0-100>,
  "best_matching_track": "<one of the candidate's target_tracks names>",
  "why": "<2-3 sentences, specific to this posting, no generic filler>",
  "genuine_gaps": ["<specific gap>", ...],
  "seniority_flag": "<'entry-level fit' | 'likely underqualified' | 'likely overqualified' | 'unclear'>",
  "partial_match_rationale": "<ONLY if fit_score is between 40 and 65: 2-3
    specific sentences on the transferable angle that makes this worth
    applying to anyway despite the gap -- Shiva's instruction is to surface
    partial matches honestly, not hide them. Empty string outside that range.>"
}}
"""
    return system, user


def _parse_response(raw_text: str, job_id: str) -> dict:
    raw = raw_text.strip()
    raw = re.sub(r"^```json|```$", "", raw).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {
            "fit_score": None,
            "best_matching_track": None,
            "why": f"[unparsed model output] {raw[:300]}",
            "genuine_gaps": [],
            "seniority_flag": "unclear",
            "partial_match_rationale": "",
        }

    parsed["job_id"] = job_id
    return parsed


def score_job(job: dict, profile: dict) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    system, user = _build_messages(job, profile)
    resp = client.messages.create(
        model=MODEL, max_tokens=600, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return _parse_response(resp.content[0].text, job["job_id"])


async def _score_one_async(client, sem: asyncio.Semaphore, job: dict, profile: dict) -> tuple[str, dict, Exception | None]:
    system, user = _build_messages(job, profile)
    async with sem:
        try:
            resp = await client.messages.create(
                model=MODEL, max_tokens=600, system=system,
                messages=[{"role": "user", "content": user}],
            )
            return job["job_id"], _parse_response(resp.content[0].text, job["job_id"]), None
        except Exception as e:
            return job["job_id"], None, e


async def _score_all_async(jobs: list, profile: dict, concurrency: int, progress_cb) -> dict:
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    sem = asyncio.Semaphore(concurrency)
    results = {}
    errors = {}
    done = 0
    total = len(jobs)
    start = time.monotonic()

    tasks = [asyncio.create_task(_score_one_async(client, sem, job, profile)) for job in jobs]
    for coro in asyncio.as_completed(tasks):
        job_id, result, err = await coro
        done += 1
        if err is not None:
            errors[job_id] = str(err)
        else:
            results[job_id] = result

        if progress_cb and (done % 50 == 0 or done == total):
            elapsed = time.monotonic() - start
            rate = done / elapsed if elapsed > 0 else 0
            remaining = (total - done) / rate if rate > 0 else 0
            progress_cb(done, total, elapsed, remaining)

    return {"results": results, "errors": errors}


def score_jobs_concurrently(jobs: list, profile: dict,
                             concurrency: int = DEFAULT_CONCURRENCY,
                             progress_cb=None) -> dict:
    """Scores a batch of jobs with up to `concurrency` requests in flight at
    once. Returns {"results": {job_id: parsed_score}, "errors": {job_id: str}}.
    progress_cb(done, total, elapsed_s, remaining_s) fires every 50 jobs and
    on completion, so a long run is never a silent black box."""
    if not jobs:
        return {"results": {}, "errors": {}}
    return asyncio.run(_score_all_async(jobs, profile, concurrency, progress_cb))
