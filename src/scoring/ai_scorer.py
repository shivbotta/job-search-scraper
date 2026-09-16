"""
AI-based job fit scoring via the Claude API.

Complements deterministic.py -- this one reasons about fit qualitatively
(seniority mismatch, culture signals, career trajectory) rather than just
counting keywords. Always shown side by side with the deterministic score,
never in place of it. Requires ANTHROPIC_API_KEY in the environment.
"""
import json
import os
import re
from html import unescape

import anthropic

MODEL = "claude-sonnet-4-6"  # update if a newer default model is preferred


def _clean_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def score_job(job: dict, profile: dict) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

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
  "seniority_flag": "<'entry-level fit' | 'likely underqualified' | 'likely overqualified' | 'unclear'>"
}}
"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    raw = resp.content[0].text.strip()
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
        }

    parsed["job_id"] = job["job_id"]
    return parsed
