"""
Resume tailoring engine (Part 7) -- the highest-stakes component.

Hard constraint: only reorders/rewords real profile content. Never invents
experience, skills, employers, or metrics. Standing rules from profile.json
are enforced by prompt AND by a post-generation checklist scan.

Pipeline:
  1. Extract the JD's keyword set (one AI call also does keyword-to-profile
     mapping and the actual rewrite, to keep this to a single request)
  2. Measure baseline coverage against the UNTAILORED resume (every
     experience/project bullet and skill, exactly as profile.json has them)
  3. Map each keyword to real evidence: direct match / equivalent rephrase /
     no match -> no match becomes an honest_gaps entry, never fabricated
  4. Render the tailored PDF (src/pdfgen.py, ATS-safe layout)
  5. Re-extract the PDF's own text and measure tailored coverage against
     THAT -- the real ATS-passability check, not the pre-render JSON
  6. Scan the tailored content against standing_rules before returning
"""
import json
import os
import re
from html import unescape

import anthropic
from pypdf import PdfReader

import coverage
import pdfgen

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


def _baseline_text(profile: dict) -> str:
    """The resume exactly as profile.json has it, untailored -- used to
    measure how much of a JD's keyword set is already covered before any
    reordering/rewording happens."""
    parts = []
    for exp in profile.get("experience", []):
        parts.append(exp.get("title", ""))
        parts.append(exp.get("org", ""))
        parts.extend(exp.get("bullets", []))
    for proj in profile.get("projects", []):
        parts.append(proj.get("name", ""))
        parts.extend(proj.get("bullets", []))
    for group in profile.get("skills", {}).values():
        parts.extend(group)
    parts.extend(profile.get("certifications_earned", []))
    edu = profile.get("education", {})
    parts.append(edu.get("degree", ""))
    parts.extend(edu.get("coursework_ordered_by_relevance", []))
    return " ".join(parts)


def _ask_model_to_tailor(job: dict, profile: dict) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    posting_text = _clean_text(job.get("description_html", ""))[:6000]

    system = (
        "You extract a job posting's real keyword requirements, honestly map "
        "each one to a candidate's actual profile, and rewrite resume content "
        "using ONLY real, existing profile content -- reordered and reworded, "
        "never invented. You never add a skill, tool, employer, metric, or "
        "certification that isn't in the profile JSON. If the JD needs "
        "something the profile genuinely lacks, that's an honest gap, not "
        "something to paper over. Follow every standing_rules entry exactly. "
        "Respond with ONLY valid JSON, no prose, no markdown fences."
    )

    user = f"""
CANDIDATE PROFILE (JSON, source of truth -- do not add anything not in here):
{json.dumps(profile, indent=2)}

TARGET JOB POSTING:
Title: {job.get('title', '')}
Company: {job.get('company', '')}
Description:
{posting_text}

Do the following and return JSON with exactly these keys:

1. Extract the JD's real keyword/requirement set (skills, tools, exact
   phrasings) -- weight mentally by where they appear (title > requirements
   > nice-to-have > boilerplate) and only include the ones that actually
   matter for matching, not generic filler words. Each keyword MUST be a
   single atomic term or exact short phrase -- never a slash-joined list of
   alternatives (write "Firebase" and "Firestore" as two separate keywords,
   never "Firebase / Firestore" as one; write "CI/CD" and "testing"
   separately, never "CI/CD / testing" as one). A compound keyword can never
   match a resume that lists the same skills individually, which would make
   coverage measurement wrong.

2. For each keyword, decide: "direct" (profile has it explicitly -- use the
   JD's own phrasing), "equivalent" (profile has the same thing under
   different words -- rephrase to the JD's vocabulary), or "none" (profile
   genuinely doesn't support it).

3. Write tailored resume content using ONLY real profile content:
   reorder/reword existing bullets, choose which 2-3 projects to lead with
   (skip anything whose usage_note says brief-mention-only or de-emphasized
   unless truly needed), and order skills by relevance to this posting.
   Only include KwikJobs and HypeSquad under experience unless the Campus
   Employment entry is specifically needed per its own usage_note.

   CRITICAL, this is the actual point of tailoring: for every keyword you
   marked "direct" or "equivalent" in step 2, the rewritten bullets/summary
   MUST actually use that keyword's exact wording somewhere -- not just
   describe the same underlying work in your own words. Identifying an
   equivalence in keyword_mapping without using the JD's term in the
   content is pointless; it accomplishes nothing for the applicant. Example:
   if you mapped "observability" as equivalent to "Sentry for error
   monitoring," the bullet must contain the word "observability," not just
   describe monitoring. Do this for every direct/equivalent match you found.

4. LENGTH LIMITS -- these are hard, and they exist because the resume is
   typeset to one page and an over-long bullet wraps to three lines, which
   reads as unedited. Write to fit:
     - summary: at most 2 sentences, 280 characters TOTAL
     - every experience bullet: at most 150 characters
     - every project bullet: at most 140 characters
     - at most 4 bullets per experience entry, 2 per project
     - skills_to_surface_first: at most 22 skills
   Tighten wording to hit these -- cut filler ("responsible for", "worked
   on", "helped to"), not substance or keywords. Do NOT end bullets with a
   period; keep punctuation consistent across all of them.

{{
  "jd_keywords": ["<the real keyword/requirement set from step 1>"],
  "keyword_mapping": [
    {{"keyword": "...", "match_type": "direct|equivalent|none", "evidence": "<short note, empty string if none>"}}
  ],
  "summary": "<<=2 sentences, <=280 chars, factual, no buzzword soup>",
  "experience": [
    {{"org": "KwikJobs", "title": "<from profile>", "dates": "<from profile>", "location": "<from profile>", "bullets": ["<reworded/reordered, from the REAL bullets only>"]}},
    {{"org": "HypeSquad", "title": "...", "dates": "...", "location": "...", "bullets": ["..."]}}
  ],
  "projects": [
    {{"name": "<from profile.projects>", "dates": "<from profile>", "link": "<if present in profile, else omit>", "bullets": ["<reworded/reordered, from the REAL bullets only>"]}}
  ],
  "skills_to_surface_first": ["<subset/reordering of profile.skills, comma-list order, most relevant first>"],
  "honest_gaps": ["<plain-language gap statement for each 'none' keyword -- never fabricate a fix>"]
}}
"""

    resp = client.messages.create(
        model=MODEL,
        max_tokens=6000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )

    if resp.stop_reason == "max_tokens":
        raise ValueError(
            "tailoring response was cut off at the token limit before "
            "finishing -- raise max_tokens further"
        )

    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```json|```$", "", raw).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise
        return json.loads(raw[start:end + 1])


def tailor_resume(job: dict, profile: dict, pdf_out_path: str | None = None) -> dict:
    ai_result = _ask_model_to_tailor(job, profile)

    jd_keywords = ai_result.get("jd_keywords", [])
    baseline_coverage = coverage.measure(_baseline_text(profile), jd_keywords)

    content = {
        "summary": ai_result.get("summary", ""),
        "experience": ai_result.get("experience", []),
        "projects": ai_result.get("projects", []),
        "skills_line": ", ".join(ai_result.get("skills_to_surface_first", [])),
    }

    # Standing-rules scan BEFORE anything gets written to disk.
    full_text = json.dumps(content)
    violations = _violates_rules(full_text)

    result = {
        "job_id": job["job_id"],
        "baseline_coverage_pct": baseline_coverage["coverage_pct"],
        "jd_keywords": jd_keywords,
        "keyword_mapping": ai_result.get("keyword_mapping", []),
        "honest_gaps": ai_result.get("honest_gaps", []),
        "content": content,
        "_standing_rules_violations": violations,
    }
    if violations:
        result["_WARNING"] = (
            f"Generated content matched banned patterns: {violations}. "
            "PDF was NOT generated -- review before retrying."
        )
        return result

    if pdf_out_path:
        layout = pdfgen.render_resume_pdf(pdf_out_path, profile, content)
        result["layout"] = layout
        pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf_out_path).pages)
        # A long line (e.g. the skills line) wraps across PDF lines, and
        # pypdf renders that wrap as a newline -- collapse whitespace so a
        # multi-word phrase that happens to wrap doesn't false-negative on
        # substring matching. A real ATS text extractor does the same.
        pdf_text = re.sub(r"\s+", " ", pdf_text)
        tailored_coverage = coverage.measure(pdf_text, jd_keywords)
        result["tailored_coverage_pct"] = tailored_coverage["coverage_pct"]
        result["tailored_coverage_missing"] = tailored_coverage["missing"]
        result["keywords_added"] = [
            k for k in tailored_coverage["matched"] if k not in baseline_coverage["matched"]
        ]
        result["pdf_path"] = pdf_out_path

    return result
