"""
Shared score-band labels (Part 4).

One place both scorers and the dashboard read from, so "Excellent match"
always means the same range everywhere instead of drifting per module.
"""

BANDS = [
    (80, 100, "Excellent match"),
    (65, 79, "Strong match"),
    (45, 64, "Worth applying"),
    (25, 44, "Stretch"),
    (0, 24, "Long shot"),
]


def score_band(score) -> str:
    if not isinstance(score, (int, float)):
        return "Unscored"
    for lo, hi, label in BANDS:
        if lo <= score <= hi:
            return label
    return "Unscored"
