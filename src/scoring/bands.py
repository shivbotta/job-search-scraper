"""
Plain-language fit labels -- the one thing a job card leads with.

Labels come from the AI fit score only. The keyword-match score is a
different measure (share of profile keywords that appear in the JD) and
tops out around 35-40 even for good matches, so labelling a card "Long
Shot" from it would mislead. A job the AI hasn't rated yet says so
instead of borrowing the keyword number.

Thresholds: the AI scorer is deliberately strict -- its prompt tells it
most postings should NOT reach 80 -- so "Great Fit" starts at 85 rather
than 90, or it would essentially never appear.
"""

BANDS = [
    (85, 100, "Great Fit"),
    (70, 84, "Strong Fit"),
    (50, 69, "Decent Fit"),
    (30, 49, "Worth a Shot"),
    (0, 29, "Long Shot"),
]
NOT_RATED = "Not rated yet"

BAND_KEYS = {
    "Great Fit": "great",
    "Strong Fit": "strong",
    "Decent Fit": "decent",
    "Worth a Shot": "shot",
    "Long Shot": "long",
    NOT_RATED: "unrated",
}


def score_band(score) -> str:
    if not isinstance(score, (int, float)):
        return NOT_RATED
    for lo, hi, label in BANDS:
        if lo <= score <= hi:
            return label
    return NOT_RATED


def fit_label(job: dict) -> str:
    return score_band((job.get("ai_score") or {}).get("fit_score"))
