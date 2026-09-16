"""
Company + contact research for a specific job posting (Part 6).

Token-optimized on purpose -- Shiva cut heavier research fields (a "why this
role exists" essay, a multi-bullet role summary) to reinvest those tokens
into deeper resume tailoring instead. Do not add them back.

This module does NOT log into LinkedIn, scrape LinkedIn, or fetch LinkedIn
URLs programmatically -- that violates LinkedIn's User Agreement and risks
the account (the LinkedIn *job search* scraper in src/scrapers/linkedin.py
is a separate, explicit exception Shiva asked for against a disposable
account; this module stays clear of it entirely). Contacts are found via
Claude's web_search tool against public sources only (company team pages,
press releases, conference speaker lists, GitHub org members, engineering
blog bylines, the posting's own byline) -- never invented. A contact with no
solid public evidence gets confidence: low rather than a guessed name.

No email address is ever surfaced, for any contact, under any confidence
level. Confirmed live during testing: even with an explicit instruction not
to, the model guessed an email by pattern ("firstname@company.com") for a
contact it hadn't actually verified via search. Per Shiva's standing rule
that a wrong guessed email is worse than none, this isn't left to prompting
-- every "email" key is stripped in code before this function returns,
regardless of what the model claims to have found.
"""
import json
import os
import re
from html import unescape

import anthropic

MODEL = "claude-sonnet-4-6"


def _clean_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _extract_final_json(resp) -> dict:
    """The model may call the web_search tool one or more times before its
    final answer -- only the LAST text block is the synthesized JSON.

    Defensive parsing: the model sometimes breaks format to add a caveat
    (confirmed live -- e.g. it wanted to flag that a sales role posting was
    outside Shiva's target tracks instead of just returning JSON for it).
    Rather than fail the whole request over one stray sentence, pull out
    the {...} substring if a direct parse fails."""
    if resp.stop_reason == "max_tokens":
        raise ValueError(
            "response was cut off at the token limit before finishing -- "
            "raise max_tokens or shorten the requested output"
        )
    text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    if not text_blocks:
        raise ValueError("model returned no text content")
    raw = text_blocks[-1].strip()
    raw = re.sub(r"^```json|```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise
        return json.loads(raw[start:end + 1])


def build_outreach_brief(job: dict, profile: dict) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    posting_text = _clean_text(job.get("description_html", ""))[:5000]
    company = job.get("company", "")

    system = (
        "You research a company and find real hiring contacts for a job "
        "applicant, using web search. Only report a contact if you found "
        "actual evidence of them (a team page, press release, conference "
        "bio, GitHub org member, or the posting's own byline) -- cite the "
        "source type. Never invent a name, title, or email. Never guess an "
        "email address by pattern (e.g. first.last@company.com) -- only "
        "include one if you found it published somewhere. If you can't find "
        "a confident contact, say so and give confidence: low, or return an "
        "empty contacts list -- always still return search_queries_for_shiva "
        "so the applicant can look manually. No visa/OPT/sponsorship "
        "language anywhere. The applicant has already decided to research "
        "this specific posting, including if it looks like a stretch or a "
        "poor fit for their background -- that judgment call is theirs, "
        "not yours, so never comment on fit or add a caveat about it. "
        "After searching, respond with ONLY a final JSON object: no prose "
        "before or after it, no markdown fences, no commentary of any kind."
    )

    user = f"""
CANDIDATE PROFILE (JSON):
{json.dumps(profile, indent=2)}

JOB POSTING:
Title: {job.get('title', '')}
Company: {company}
URL: {job.get('url', '')}
Description:
{posting_text}

Do 1-2 targeted searches MAX (this is a quick lookup, not a research report),
then find 1-3 real hiring contacts (recruiter, technical recruiter, or the
hiring manager for this team). Return JSON with EXACTLY these keys and no
others -- company_brief is a SINGLE PLAIN STRING one line long, never a
nested object with sub-fields, and contacts stay to the fields listed below
only:
{{
  "company_brief": "<ONE plain-text line, e.g. 'OpenAI | AI research lab | 500+ employees' -- not an object, not multiple sentences>",
  "where_to_apply": "<direct application URL, use the posting URL if that's the only one>",
  "contacts": [
    {{"name": "...", "title": "...", "linkedin_url": "... (if found)",
      "source": "company team page | press release | job posting byline | github org | conference bio",
      "confidence": "high | medium | low"}}
  ],
  "search_queries_for_shiva": [
    "site:linkedin.com/in \\"{company}\\" \\"technical recruiter\\"",
    "<1-3 more Google queries Shiva can run himself to find people on LinkedIn manually>"
  ],
  "connection_note": "<under 300 chars, specific, references the posting or company, no visa/OPT language>",
  "followup_note": "<short message to send 3-4 days later if no reply>"
}}

Keep the whole response compact -- this is meant to be quick reference
material, not a dossier.
"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        messages=[{"role": "user", "content": user}],
    )

    result = _extract_final_json(resp)

    # Hard guardrail, not just a prompt instruction: confirmed live that the
    # model will sometimes guess an email by pattern (e.g. "firstname@
    # company.com") even when explicitly told not to. Prompting alone isn't
    # reliable enough for a "never fabricate" rule -- strip every email
    # server-side rather than trust the model's claim that it was found.
    for contact in result.get("contacts", []) or []:
        contact.pop("email", None)

    result["job_id"] = job["job_id"]
    result["_reminder"] = (
        "Contact names/titles above are AI-suggested leads from public web "
        "search, not verified facts -- confirmed during testing that this "
        "kind of lookup can surface a name not clearly backed by the actual "
        "search results. Treat every contact as a starting point, not a "
        "confirmed person: verify their identity and current role on "
        "LinkedIn yourself before reaching out. No email address is ever "
        "included, even if the model claims to have found one -- this tool "
        "never logs into or scrapes LinkedIn for outreach research."
    )
    return result
