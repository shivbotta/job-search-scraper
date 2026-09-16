"""
Deterministic, transparent job-fit scoring.

Why not just ask an LLM for a 0-100 score? Because it clusters everything
around 80-something and isn't inspectable. This scorer instead:
  1. Strips HTML, lowercases the posting text
  2. Counts hits against each target track's keyword list, weighted by
     that track's profile.json weight
  3. Counts hits against the full skills list
  4. Adds an industry-tier bonus, a recency bonus, and an experience-fit
     penalty (Part 4)
  5. Returns a composite score + the matched/missing terms, fully auditable

Nothing here ever excludes a posting -- CLAUDE.md's matching philosophy is
"no mercy filtering, score honestly, show everything." Penalties lower rank,
they never zero out or drop a job.
"""
import re
from html import unescape

from datehelpers import parse_posted_at
import datetime

# Years-of-experience phrasing commonly seen in JDs: "3+ years", "5-7 years
# of experience", "minimum of 4 years". Takes the largest number mentioned
# near "year(s)" as the requirement -- a JD asking for "3-5 years" should be
# judged against the harder end, not the easier one.
_YEARS_PATTERN = re.compile(r"(\d+)\+?\s*(?:-\s*\d+\s*)?\+?\s*years?", re.IGNORECASE)


def _clean_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).lower()


def _industry_bonus(text: str, industry_priority: dict) -> tuple[int, str]:
    for tier, bonus in (("tier_1", 8), ("tier_2", 3), ("tier_3", 0)):
        keywords = industry_priority.get(tier, [])
        if any(kw.lower() in text for kw in keywords):
            return bonus, tier
    return 0, ""


def _recency_bonus(posted_at) -> int:
    posted_dt = parse_posted_at(posted_at)
    if posted_dt is None:
        return 0
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    age = now - posted_dt
    if age <= datetime.timedelta(hours=1):
        return 5
    if age <= datetime.timedelta(hours=6):
        return 3
    if age <= datetime.timedelta(hours=24):
        return 1
    return 0


def _experience_penalty(text: str, ceiling_years: int) -> tuple[int, int | None]:
    """Never excludes -- just ranks a posting lower when it asks for more
    years than the profile's ceiling. Returns (penalty, required_years)."""
    years_mentioned = [int(m.group(1)) for m in _YEARS_PATTERN.finditer(text)]
    plausible = [y for y in years_mentioned if y <= 20]  # drop noise ("100 years in business")
    if not plausible:
        return 0, None
    required = max(plausible)
    if required <= ceiling_years:
        return 0, required
    overage = required - ceiling_years
    penalty = min(20, overage * 5)  # capped so it demotes, never zeroes out
    return penalty, required


def score_job(job: dict, profile: dict) -> dict:
    text = _clean_text(job.get("description_html", "")) + " " + job.get("title", "").lower()

    # Score against each target track separately, weighted per profile.json
    track_scores = []
    for track in profile["target_tracks"]:
        kws = track["keywords"]
        hits = [kw for kw in kws if kw.lower() in text]
        raw_pct = round(100 * len(hits) / max(len(kws), 1))
        weighted_pct = round(raw_pct * track.get("weight", 1.0))
        track_scores.append({
            "track": track["name"],
            "score": raw_pct,
            "weighted_score": weighted_pct,
            "weight": track.get("weight", 1.0),
            "matched_keywords": hits,
            "missing_keywords": [kw for kw in kws if kw not in hits],
        })
    track_scores.sort(key=lambda t: t["weighted_score"], reverse=True)

    # Score against full skills inventory (flat list across all groups)
    all_skills = [s for group in profile["skills"].values() for s in group]
    skill_hits = [s for s in all_skills if s.lower() in text]
    skill_pct = round(100 * len(skill_hits) / max(len(all_skills), 1))

    best_track = track_scores[0]
    industry_bonus, industry_tier = _industry_bonus(text, profile.get("industry_priority", {}))
    recency_bonus = _recency_bonus(job.get("posted_at"))
    experience_penalty, required_years = _experience_penalty(
        text, profile.get("experience_ceiling_years", 3)
    )

    base = round(0.7 * best_track["weighted_score"] + 0.3 * skill_pct)
    composite = base + industry_bonus + recency_bonus - experience_penalty
    composite = max(0, min(100, composite))

    return {
        "job_id": job["job_id"],
        "best_track": best_track["track"],
        "best_track_score": best_track["score"],
        "track_scores": track_scores,
        "skill_overlap_score": skill_pct,
        "matched_skills": skill_hits,
        "industry_bonus": industry_bonus,
        "industry_tier": industry_tier,
        "recency_bonus": recency_bonus,
        "experience_penalty": experience_penalty,
        "required_years_mentioned": required_years,
        "composite_score": composite,
    }
