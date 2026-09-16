"""
Tailor Shiva's resume summary + bullets for one specific job posting.

Hard constraint: only reorders/rewords real profile content. Never invents
experience, skills, or metrics. Standing rules from profile.json are enforced
by prompt AND by a post-generation checklist scan.
"""
import json
import os
import re
from html import unescape

import anthropic

MODEL = "claude-sonnet-4-6"

BANNED_PATTERNS = [
    r"\bopt\b", r"\bh-?1b\b", r"visa", r"sponsorship", r"work authoriz",
    r"farmside",
]


def _clean_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _violates_rules(text: str) -> list[str]:
    hits = []
    low = text.lower()
    for pat in BANNED_PATTERNS:
        if re.search(pat, low):
            hits.append(pat)
    return hits


def tailor_resume(job: dict, profile: dict) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    posting_text = _clean_text(job.get("description_html", ""))[:6000]

    system = (
        "You write tailored resume content by reordering and rewording a "
        "candidate's REAL, existing profile content to match a specific job "
        "posting. You never invent skills, employers, metrics, or experience "
        "not present in the profile JSON. Follow every rule in the profile's "
        "standing_rules list exactly. Respond with ONLY valid JSON, no prose."
    )

    user = f"""
CANDIDATE PROFILE (JSON, source of truth -- do not add anything not in here):
{json.dumps(profile, indent=2)}

TARGET JOB POSTING:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Description:
{posting_text}

Produce tailored resume content as JSON with exactly these keys:
{{
  "summary": "<2-3 sentence tailored summary, factual, no buzzword soup>",
  "bullets_kwikjobs": ["<reworded/reordered bullets from experience[0], same facts>"],
  "top_projects_to_lead_with": ["<project names from profile.projects, ordered by relevance>"],
  "skills_to_surface_first": ["<subset of profile.skills most relevant to this posting>"],
  "keyword_gap_note": "<honest note on any posting keywords the profile genuinely doesn't support -- never stuffed in>"
}}
"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```json|```$", "", raw).strip()
    result = json.loads(raw)

    # Post-generation safety check against standing rules
    full_text = json.dumps(result)
    violations = _violates_rules(full_text)
    result["_standing_rules_violations"] = violations
    if violations:
        result["_WARNING"] = (
            "Generated content matched banned patterns: "
            f"{violations}. Review before using."
        )

    return result
