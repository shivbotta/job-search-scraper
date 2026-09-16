"""
Outreach research for a specific job posting.

This module does NOT log into LinkedIn, scrape LinkedIn, or fetch LinkedIn
URLs programmatically -- that violates LinkedIn's User Agreement and risks
the account. Instead it:
  1. Suggests the job titles Shiva should search for himself on LinkedIn
  2. Drafts a connection-request note and a short follow-up message
  3. Pulls 2-3 concrete personalization angles from the posting text itself

Shiva finds the actual person and sends the message himself.
"""
import json
import os
import re
from html import unescape

import anthropic

MODEL = "claude-sonnet-4-6"

LIKELY_TITLES = [
    "Technical Recruiter",
    "Talent Acquisition Partner",
    "University Recruiter",
    "Recruiter",
    "Engineering Manager",
    "Hiring Manager",
]


def _clean_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def build_outreach_brief(job: dict, profile: dict) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    posting_text = _clean_text(job.get("description_html", ""))[:5000]

    system = (
        "You draft short, specific LinkedIn outreach messages. No generic "
        "'I'd love to connect' filler. Reference something real and specific "
        "from the job posting or company. Follow the candidate's standing_rules "
        "exactly -- especially no visa/OPT/sponsorship language. Respond with "
        "ONLY valid JSON, no prose."
    )

    user = f"""
CANDIDATE PROFILE (JSON):
{json.dumps(profile, indent=2)}

JOB POSTING:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Description:
{posting_text}

Search titles to try on LinkedIn at this company: {LIKELY_TITLES}

Return JSON with exactly these keys:
{{
  "search_titles": ["<2-4 titles from the list above most likely to actually respond>"],
  "connection_request_note": "<under 300 chars, specific, references the posting or company, no visa/OPT language>",
  "followup_message": "<a short message to send 3-4 days after connecting, if no reply to the note>",
  "personalization_angles": ["<2-3 specific, concrete details from the posting or company to reference>"]
}}
"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=800,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```json|```$", "", raw).strip()
    result = json.loads(raw)
    result["job_id"] = job["job_id"]
    result["_reminder"] = (
        "Search LinkedIn manually for these titles at "
        f"{job.get('company', '')}. This tool never logs in or scrapes LinkedIn."
    )
    return result
