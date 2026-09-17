"""
Source and industry labels for the Jobs Feed filters.

Source comes straight from how a posting was ingested. Industry is
inferred -- there's no industry field on a job posting -- so it's a
keyword classifier seeded from profile.json's industry_priority tiers,
plus a small map of companies that appear often enough in the data to be
worth pinning down exactly. Inference is best-effort by nature: a posting
that matches nothing lands in "Other" rather than being forced into a
bucket it doesn't belong in.
"""
import re
from html import unescape

# job["source"] -> display label
_SOURCE_LABELS = {
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "workday": "Workday",
    "linkedin": "LinkedIn",
    "indeed": "Indeed",
    "manual": "Added manually",
}

# For postings ingested by the google_ats discovery scraper, the actual
# board is in discovered_via.
_PLATFORM_LABELS = {
    "smartrecruiters.com": "SmartRecruiters",
    "apply.workable.com": "Workable",
    "myworkdayjobs.com": "Workday",
    "boards.greenhouse.io": "Greenhouse",
    "jobs.lever.co": "Lever",
    "jobs.ashbyhq.com": "Ashby",
}


# Companies are stored as ATS board tokens ("doordashusa"), which is what
# the APIs return. Those read badly as the most prominent text on a card,
# so known ones get their real name and the rest are tidied generically.
_COMPANY_NAMES = {
    "doordashusa": "DoorDash", "scaleai": "Scale AI", "perplexityai": "Perplexity",
    "sonyinteractiveentertainmentglobal": "Sony Interactive Entertainment",
    "1password": "1Password", "checkout.com": "Checkout.com", "kraken.com": "Kraken",
    "super.com": "Super.com", "field-ai": "Field AI", "palo-it": "Palo IT",
    "smart-working-solutions": "Smart Working Solutions", "hugging-face": "Hugging Face",
    "weightsandbiases": "Weights & Biases", "mistralai": "Mistral AI",
    "runwayml": "Runway", "shieldai": "Shield AI", "oscarhealth": "Oscar Health",
    "devotedhealth": "Devoted Health", "modernTreasury": "Modern Treasury",
    "openai": "OpenAI", "mongodb": "MongoDB", "gitlab": "GitLab", "github": "GitHub",
    "ebanx": "EBANX", "gofundme": "GoFundMe", "cfgi": "CFGI", "g2i": "G2i",
    "flosports": "FloSports", "junipersquare": "Juniper Square",
    "magicschool": "MagicSchool", "sewer-ai": "SewerAI", "spector-ai": "Spector AI",
    "pylon-labs": "Pylon", "risklabs": "Risk Labs", "outcomesai": "OutcomesAI",
    "deepgenomics": "Deep Genomics", "redoxengine": "Redox", "launchsquad": "LaunchSquad",
    "coderpad": "CoderPad", "onehouse": "Onehouse", "truelogic": "Truelogic",
    "sonarsource": "SonarSource", "netlify": "Netlify", "tenstorrent": "Tenstorrent",
    "labelbox": "Labelbox", "teamworks": "Teamworks", "givebutter": "Givebutter",
    "blockworks": "Blockworks", "commure": "Commure", "abridge": "Abridge",
    "protegrity": "Protegrity", "virtualitics": "Virtualitics", "paytm": "Paytm",
}


def company_label(company: str) -> str:
    raw = (company or "").strip()
    key = raw.lower()
    if key in _COMPANY_NAMES:
        return _COMPANY_NAMES[key]
    if not raw:
        return "Unknown"
    # Generic tidy-up: hyphen/underscore tokens become spaced words, and an
    # all-lowercase token gets title-cased. Names that already look
    # deliberate (mixed case, dots) are left exactly as they are.
    if raw.islower():
        cleaned = re.sub(r"[-_]+", " ", raw)
        return cleaned.title() if "." not in cleaned else cleaned
    return raw


def source_label(job: dict) -> str:
    source = (job.get("source") or "").lower()
    if source == "google_ats":
        via = job.get("discovered_via", "")
        platform = via.split(":", 1)[1] if ":" in via else ""
        return _PLATFORM_LABELS.get(platform, "Google site: search")
    return _SOURCE_LABELS.get(source, source.title() or "Unknown")


# Companies common in this dataset where a keyword guess would be wrong or
# ambiguous. Keeps the biggest slices of the feed correctly labelled.
_COMPANY_INDUSTRY = {
    "anthropic": "AI/ML", "openai": "AI/ML", "scaleai": "AI/ML", "perplexity": "AI/ML",
    "labelbox": "AI/ML", "together": "AI/ML", "runwayml": "AI/ML", "field-ai": "AI/ML",
    "tenstorrent": "AI/ML", "abridge": "Healthcare", "commure": "Healthcare",
    "brex": "Fintech", "ramp": "Fintech", "chime": "Fintech", "affirm": "Fintech",
    "coinbase": "Fintech", "stripe": "Fintech", "plaid": "Fintech", "mercury": "Fintech",
    "robinhood": "Fintech", "checkout.com": "Fintech", "kraken.com": "Fintech",
    "ebanx": "Fintech", "melio": "Fintech", "yuno": "Fintech", "paytm": "Fintech",
    "cfgi": "Finance", "blockworks": "Finance", "clair": "Fintech",
    "shieldai": "Defense", "palantir": "Defense",
    "samsara": "Enterprise", "veeva": "Enterprise", "sonarsource": "Enterprise",
    "twilio": "Tech", "mongodb": "Tech", "datadog": "Tech", "cloudflare": "Tech",
    "gitlab": "Tech", "netlify": "Tech", "vanta": "Tech", "1password": "Tech",
    "okta": "Tech", "elastic": "Tech", "figma": "Tech", "dropbox": "Tech",
    "discord": "Tech", "reddit": "Tech", "pinterest": "Tech", "asana": "Tech",
    "airbnb": "Tech", "doordashusa": "Tech", "spotify": "Tech",
    "tekion": "Automotive", "upside": "Automotive",
    "sonyinteractiveentertainmentglobal": "Sports/Gaming", "flosports": "Sports/Gaming",
    "teamworks": "Sports/Gaming",
    "protegrity": "Enterprise", "truelogic": "Enterprise", "palo-it": "Enterprise",
    "gofundme": "Tech", "givebutter": "Tech", "magicschool": "Tech",
}

# Checked in order -- most specific first, so "insurance" doesn't get
# swallowed by the broader "financial services" bucket and a defense
# contractor doesn't read as generic enterprise software.
_INDUSTRY_RULES = [
    ("Defense", [
        "defense", "aerospace", "national security", "security clearance",
        "ts/sci", "department of defense", "dod ", "military", "satellite",
        "spacecraft", "space systems", "warfighter",
    ]),
    ("Healthcare", [
        "healthcare", "health tech", "health system", "patient", "clinical",
        "biotech", "pharmaceutical", "medical", "ehr", "hipaa", "telehealth",
        "provider network", "life sciences",
    ]),
    ("Insurance", [
        "insurance", "insurtech", "underwriting", "actuarial", "claims processing",
        "policyholder",
    ]),
    ("Banking", [
        "retail banking", "commercial bank", "investment bank", "banking",
        "credit union", "mortgage", "consumer bank",
    ]),
    ("Fintech", [
        "fintech", "payments", "payment processing", "neobank", "digital wallet",
        "lending", "crypto", "blockchain", "web3", "card issuing", "treasury",
        "money movement", "financial infrastructure",
    ]),
    ("Finance", [
        "asset management", "hedge fund", "private equity", "capital markets",
        "trading", "wealth management", "financial services", "portfolio management",
        "venture capital",
    ]),
    ("Automotive", [
        "automotive", "autonomous driving", "self-driving", "electric vehicle",
        "fleet management", "telematics", "mobility",
    ]),
    ("Sports/Gaming", [
        "gaming", "game studio", "video game", "esports", "sportsbook", "betting",
        "sports", "playstation", "console",
    ]),
    ("AI/ML", [
        "artificial intelligence", "machine learning", "large language model",
        "foundation model", "generative ai", "genai", "llm", "deep learning",
        "computer vision", "nlp", "ai research", "model training",
    ]),
    ("Enterprise", [
        "enterprise software", "b2b saas", "erp", "crm", "consulting",
        "professional services", "supply chain", "workforce management",
        "enterprise customers",
    ]),
    ("Startup", [
        "seed stage", "series a", "series b", "early-stage startup",
        "founding engineer", "early stage",
    ]),
    ("Tech", [
        "saas", "cloud", "developer tools", "platform", "infrastructure",
        "software company", "api", "devops", "open source",
    ]),
]

INDUSTRY_ORDER = [
    "AI/ML", "Fintech", "Tech", "Enterprise", "Finance", "Banking", "Healthcare",
    "Defense", "Insurance", "Automotive", "Sports/Gaming", "Startup", "Other",
]


def _text_of(job: dict) -> str:
    raw = job.get("description_html", "") or ""
    text = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", unescape(text)).lower()[:6000]


# Scanning description text for every posting on every page render would be
# slow at this dataset's size (thousands of jobs per recency bucket), and
# the answer never changes for a given posting -- memoize per process.
_INDUSTRY_MEMO: dict[str, str] = {}


def industry_label(job: dict) -> str:
    if job.get("industry"):
        return job["industry"]
    job_id = job.get("job_id", "")
    if job_id in _INDUSTRY_MEMO:
        return _INDUSTRY_MEMO[job_id]

    company = (job.get("company") or "").strip().lower()
    if company in _COMPANY_INDUSTRY:
        label = _COMPANY_INDUSTRY[company]
    else:
        haystack = f"{company} {job.get('title','').lower()} {_text_of(job)}"
        label = "Other"
        for candidate, keywords in _INDUSTRY_RULES:
            if any(kw in haystack for kw in keywords):
                label = candidate
                break

    if job_id:
        _INDUSTRY_MEMO[job_id] = label
    return label
