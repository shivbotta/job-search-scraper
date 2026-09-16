"""
Skills Gap Analysis (Part 8, Tab 3).

Aggregates every honest_gaps list ever written by the tailoring engine
(data/tailored/*/report.json) so Shiva can see which missing skills show up
most often, weighted by how good a match the job otherwise was -- a gap in
an 85-score job matters more than the same gap in a 30-score job.
"""
import glob
import json
import os
import re

CERT_HINTS = ["certification", "certified", "cert)", " aws ", "certificate"]


def _effort_label(gap_text: str) -> str:
    low = gap_text.lower()
    if any(h in low for h in CERT_HINTS):
        return "hard"
    # A single named tool/language/framework is usually learnable faster
    # than a role/process gap (e.g. "internship experience", "RAG pipeline
    # architecture") which takes real project time to build credibly.
    if len(gap_text.split()) <= 3:
        return "easy"
    return "medium"


def _gap_key(gap_text: str) -> str:
    """Normalize a gap sentence down to its leading skill/topic name so the
    same gap phrased slightly differently by different runs still groups
    together, e.g. "TypeScript: profile lists JavaScript but not
    TypeScript" -> "typescript"."""
    head = re.split(r"[:\-—]", gap_text, maxsplit=1)[0]
    return re.sub(r"\s+", " ", head).strip().lower()


def aggregate(tailored_dir: str) -> dict:
    reports = []
    for path in glob.glob(os.path.join(tailored_dir, "*", "report.json")):
        try:
            with open(path) as f:
                reports.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue

    gap_stats = {}  # key -> {"label": display text, "count": n, "weighted": sum, "effort": str}
    cert_gaps = {}

    for report in reports:
        score = report.get("job_score") or 0
        for gap in report.get("honest_gaps", []) or []:
            key = _gap_key(gap)
            if not key:
                continue
            label = gap.split(":")[0].split(" - ")[0].strip() or gap[:40]
            entry = gap_stats.setdefault(key, {
                "label": label,
                "count": 0, "weighted_score": 0,
                # Effort is judged on the short skill/topic label, not the
                # full gap sentence -- "TypeScript" should read as easy even
                # though the sentence explaining the gap is long.
                "effort": _effort_label(label),
            })
            entry["count"] += 1
            entry["weighted_score"] += score

            if entry["effort"] == "hard":
                cert_gaps.setdefault(key, entry)

    ranked = sorted(
        gap_stats.values(),
        key=lambda e: e["count"] * max(e["weighted_score"], 1),
        reverse=True,
    )

    return {
        "top_skills_to_learn": ranked[:10],
        "certifications_missing": sorted(cert_gaps.values(), key=lambda e: e["count"], reverse=True),
        "total_resumes_analyzed": len(reports),
    }
