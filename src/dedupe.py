"""
Shared job fingerprinting (Part 3e).

Used for cross-source dedup in cli.py (the SAME posting found via, say,
LinkedIn and a direct Greenhouse pull gets different job_id formats and
would otherwise show up twice) and by hidden.py's "hide until reposted"
feature. One normalization means both agree on identity for the same role.
"""
import re


def fingerprint(company: str, title: str) -> str:
    def norm(s):
        s = (s or "").lower().strip()
        s = re.sub(r"[^a-z0-9]+", " ", s)
        return re.sub(r"\s+", " ", s).strip()
    return f"{norm(company)}||{norm(title)}"
