"""
Deterministic, transparent job-fit scoring.

Why not just ask an LLM for a 0-100 score? Because it clusters everything
around 80-something and isn't inspectable. This scorer instead:
  1. Strips HTML, lowercases the posting text
  2. Counts hits against each target track's keyword list
  3. Counts hits against the full skills list
  4. Applies simple weights and returns a score + the matched/missing terms

The output is auditable: you can see exactly why a job scored what it scored.
"""
import re
from html import unescape


def _clean_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).lower()


def score_job(job: dict, profile: dict) -> dict:
    text = _clean_text(job.get("description_html", "")) + " " + job.get("title", "").lower()

    # Score against each target track separately
    track_scores = []
    for track in profile["target_tracks"]:
        kws = track["keywords"]
        hits = [kw for kw in kws if kw.lower() in text]
        pct = round(100 * len(hits) / max(len(kws), 1))
        track_scores.append({
            "track": track["name"],
            "score": pct,
            "matched_keywords": hits,
            "missing_keywords": [kw for kw in kws if kw not in hits],
        })
    track_scores.sort(key=lambda t: t["score"], reverse=True)

    # Score against full skills inventory (weighted flat list)
    all_skills = [s for group in profile["skills"].values() for s in group]
    skill_hits = [s for s in all_skills if s.lower() in text]
    skill_pct = round(100 * len(skill_hits) / max(len(all_skills), 1))

    best_track = track_scores[0]

    return {
        "job_id": job["job_id"],
        "best_track": best_track["track"],
        "best_track_score": best_track["score"],
        "track_scores": track_scores,
        "skill_overlap_score": skill_pct,
        "matched_skills": skill_hits,
        # Simple composite: weight track match higher than raw skill overlap
        "composite_score": round(0.7 * best_track["score"] + 0.3 * skill_pct),
    }
