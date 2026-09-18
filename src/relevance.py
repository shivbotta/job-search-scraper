"""
Title-first relevance gate, applied at ingest before anything is scored.

The old behaviour let a posting through on a single keyword anywhere in
its description, so "Finance Operations Analyst" got in because the JD
mentioned SQL once. This gate judges the ROLE, mostly from the title,
the way a person skimming a job board would:

  1. Title names a non-engineering function (sales, finance, recruiting,
     product/program management, ...) or an excluded track from
     profile.json -> drop. Nothing in the description overrides this:
     "Account Executive, AI Native" is a sales job regardless of how much
     AI the JD talks about.
  2. Title names a clear software/AI/data engineering role -> keep.
  3. Title names a non-software engineering discipline (mechanical, RF,
     PCB, ...) with no software signal -> drop.
  4. Title is technical but ambiguous ("Security Engineer", "Platform
     Intelligence Engineer") -> keep only if the description shows the
     job is primarily hands-on engineering work: several distinct
     engineering signals, not one passing mention.
  5. Anything else -> drop.

Each decision carries a reason so the ingest log can show why volume
changed.
"""
import re
from html import unescape


def _rx(words: list[str]) -> re.Pattern:
    return re.compile(r"\b(?:" + "|".join(words) + r")\b", re.IGNORECASE)


# Rule 2 -- the title alone makes this a software/AI/data engineering role.
STRONG_TITLE = _rx([
    r"software", r"developer", r"programmer", r"swe", r"sde", r"sdet",
    r"full[\s-]?stack", r"back[\s-]?end", r"front[\s-]?end",
    r"machine learning", r"ml", r"ai", r"a\.i\.", r"artificial intelligence",
    r"llm", r"genai", r"gen ai", r"deep learning", r"nlp", r"computer vision",
    r"perception", r"data engineer(?:ing)?", r"analytics engineer",
    r"data scientist", r"data science", r"applied scientist",
    r"research (?:engineer|scientist)", r"member of technical staff",
    r"(?:mobile|ios|android|web) (?:engineer|developer)", r"android", r"ios",
    r"platform engineer", r"infrastructure engineer", r"cloud engineer",
    r"devops", r"site reliability", r"sre", r"forward deployed engineer",
    r"api", r"automation engineer",
    # Autonomy (planning/control/behaviors) and kernel (ML/accelerator
    # performance) engineering are software work despite not saying so --
    # found as false drops when checking the gate against real postings.
    r"autonomy", r"kernel",
])

# Rule 1 -- non-engineering functions, matched against the ROLE part of
# the title only (see _role_part). Hard ones always drop.
FUNCTION_HARD = _rx([
    r"sales", r"account executive", r"account manager", r"account director",
    r"business development", r"bdr", r"sdr", r"partner manager",
    r"marketing", r"growth marketer", r"brand", r"public relations",
    r"copywriter", r"social media", r"community manager",
    r"recruit(?:er|ing|ment)", r"talent", r"sourcer", r"people (?:ops|operations|partner)",
    r"human resources", r"hr", r"payroll",
    r"account(?:ant|ing)", r"controller", r"finance", r"financial", r"fp&a", r"tax",
    r"audit(?:or)?", r"billing", r"procurement", r"purchasing",
    r"legal", r"counsel", r"paralegal", r"attorney",
    r"customer success", r"customer support", r"customer experience",
    r"help desk", r"service desk", r"desktop support", r"it support",
    r"revenue", r"chief of staff",
    r"product manager", r"product management", r"program manager", r"project manager",
    r"product owner",
    r"designer", r"design lead", r"ux researcher", r"user researcher",
    r"executive assistant", r"administrative", r"office manager", r"receptionist",
    r"facilities", r"mission manager", r"proposal manager",
    r"territory manager", r"fraud researcher", r"underwriter", r"actuar(?:y|ial)",
])

# Softer function words: drop only when the role part has no strong
# engineering signal, so "ML Operations Engineer" survives while
# "Revenue Operations Lead" and "Implementation Consultant" don't.
FUNCTION_SOFT = _rx([
    r"operations", r"ops lead", r"strategy", r"specialist", r"consultant",
    r"coordinator", r"representative", r"content", r"events?", r"communications",
    r"compliance", r"policy", r"partnerships?", r"scrum master", r"delivery manager",
    r"workplace", r"benefits",
])

# "IT" has to be matched case-sensitively -- lowercased it's just "it".
_IT_ROLE = re.compile(r"\bIT\b")

# The role's head noun (its last word, ignoring a level suffix like "II" or
# "L3"). When that's engineer/developer/scientist, a function word earlier
# in the role is describing the domain, not the job: "Recruiting Analytics
# Data Engineer" is a data engineer, while "Recruiting Coordinator" isn't.
_ENG_HEAD = re.compile(
    r"\b(?:engineer|developer|programmer|scientist|sdet|swe|sde)"
    r"(?:\s+(?:i{1,3}|iv|v|[1-5]|l\d))?\s*$",
    re.IGNORECASE,
)

_ROLE_SPLIT = re.compile(r",|\s[-–—]\s|\(|\||:")


def _role_part(title: str) -> str:
    """Titles usually read "Role, Team" / "Role - Team" / "Role (Team)".
    Function words are judged on the role only, so a real SWE job on a
    finance or revenue team ("Software Engineer, Revenue Platform") isn't
    mistaken for a finance job."""
    return _ROLE_SPLIT.split(title, maxsplit=1)[0].strip()

# Rule 3 -- engineering, but not software.
DISCIPLINE_NEGATIVE = _rx([
    r"mechanical", r"electrical", r"hardware", r"pcb", r"rtl", r"asic", r"fpga",
    r"dft", r"physical design", r"silicon", r"analog", r"rf", r"signal integrity",
    r"power (?:electronics|engineer)", r"manufacturing", r"civil", r"chemical",
    r"process engineer", r"packaging", r"supply chain", r"quality engineer",
    r"design verification", r"verification engineer", r"emulation",
    r"field application", r"sales engineer", r"solutions? engineer",
    r"support engineer", r"technical services", r"customer engineer",
    r"success engineer",
    r"implementation engineer", r"network engineer", r"systems administrator",
    r"sysadmin", r"avionics", r"propulsion", r"structures",
    r"thermal", r"optical", r"test engineer", r"reliability engineer",
    r"integration engineer", r"flight", r"gnc", r"mission systems",
])

# Rule 4 -- technical enough to be worth checking the description.
TECHNICAL_NOUN = _rx([
    r"engineer", r"engineering", r"scientist", r"architect", r"technologist",
    r"technical staff", r"firmware", r"embedded",
])

# Distinct signals that a JD's day-to-day is hands-on engineering. A role
# needs several of these, not one -- a single "SQL" or "Python" mention is
# exactly the keyword collision this gate exists to stop.
ENGINEERING_SIGNALS = [
    "python", "java", "javascript", "typescript", "golang", " go ", "c++", "rust",
    "react", "node.js", "kubernetes", "docker", "terraform", "aws", "gcp", "azure",
    "microservices", "distributed systems", "rest api", "graphql", "backend",
    "frontend", "codebase", "code review", "pull request", "ci/cd", "unit test",
    "write code", "writing code", "software development", "software engineering",
    "machine learning", "pytorch", "tensorflow", "llm", "model training",
    "data pipeline", "spark", "airflow", "kafka", "postgres", "system design",
    "scalable", "production systems", "algorithms", "data structures",
]
DESCRIPTION_OVERRIDE_MIN = 5


def _description_signals(job: dict) -> int:
    text = re.sub(r"<[^>]+>", " ", job.get("description_html", "") or "")
    text = " " + re.sub(r"\s+", " ", unescape(text)).lower() + " "
    return sum(1 for s in ENGINEERING_SIGNALS if s in text)


def _excluded_tracks_pattern(profile: dict):
    tracks = profile.get("excluded_tracks", {}).get("never_target", [])
    return _rx([re.escape(t) for t in tracks]) if tracks else None


def assess(job: dict, profile: dict) -> tuple[bool, str]:
    """Returns (keep, reason)."""
    title = (job.get("title") or "").strip()
    if not title:
        return False, "no title"
    role = _role_part(title)

    excluded = _excluded_tracks_pattern(profile)
    if excluded and excluded.search(role):
        return False, "excluded track"

    m = FUNCTION_HARD.search(role)
    if m and not _ENG_HEAD.search(role):
        return False, f"non-engineering function ({m.group(0).lower()})"

    strong_in_role = bool(STRONG_TITLE.search(role))

    m = FUNCTION_SOFT.search(role)
    if m and not strong_in_role:
        return False, f"non-engineering function ({m.group(0).lower()})"

    # A non-software discipline in the ROLE beats a software word that only
    # appears in the team name: "Support Engineer, AI Infrastructure" is a
    # support job on an AI team, not an AI engineering job.
    if not strong_in_role:
        if _IT_ROLE.search(role):
            return False, "non-software discipline (IT)"
        m = DISCIPLINE_NEGATIVE.search(role)
        if m:
            return False, f"non-software discipline ({m.group(0).lower()})"

    if STRONG_TITLE.search(title):
        return True, "engineering title"

    m = DISCIPLINE_NEGATIVE.search(title)
    if m:
        return False, f"non-software discipline ({m.group(0).lower()})"

    if TECHNICAL_NOUN.search(title):
        n = _description_signals(job)
        if n >= DESCRIPTION_OVERRIDE_MIN:
            return True, f"technical title, engineering-heavy JD ({n} signals)"
        return False, f"technical title, JD not primarily engineering ({n} signals)"

    return False, "title not a technical role"


def filter_jobs(jobs: list, profile: dict) -> tuple[list, list]:
    """Splits into (kept, dropped); dropped items are (job, reason)."""
    kept, dropped = [], []
    for job in jobs:
        ok, reason = assess(job, profile)
        (kept if ok else dropped).append(job if ok else (job, reason))
    return kept, dropped
