"""
Keyword coverage measurement (Part 7).

Shared by the baseline measurement (resume as-is, before tailoring) and the
tailored measurement (re-extracted from the actual generated PDF, not the
pre-render text) so both use identical, auditable matching logic.
"""


def measure(text: str, keywords: list[str]) -> dict:
    low = (text or "").lower()
    matched = [k for k in keywords if k.lower() in low]
    missing = [k for k in keywords if k not in matched]
    pct = round(100 * len(matched) / max(len(keywords), 1))
    return {"coverage_pct": pct, "matched": matched, "missing": missing}
