"""
US-location filtering.

Shiva's profile.json location_scope is "United States (all states, all
cities, plus remote)" -- postings outside that scope get dropped at ingest,
the same way excluded_tracks postings are, so they never reach scoring or
the dashboard. A posting can list multiple locations (ATS boards often join
them with ";"); it counts as in-scope if ANY listed location is US-based.

This is keyword-based, not a geocoding lookup -- consistent with the rest of
the codebase's pragmatic matching (deterministic.py does the same for
keywords). A location with no recognizable signal either way is treated as
out of scope, since the ask is to focus ONLY on US postings.
"""
import re

US_STATE_ABBR = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV",
    "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN",
    "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}

US_STATE_NAMES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine",
    "maryland", "massachusetts", "michigan", "minnesota", "mississippi",
    "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota",
    "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah",
    "vermont", "virginia", "washington", "west virginia", "wisconsin",
    "wyoming",
}

# Major US tech-hub cities unambiguous enough to not collide with a
# same-named foreign city (Cambridge/Birmingham/Richmond etc. are
# deliberately left out for that reason).
MAJOR_US_CITIES = {
    "austin", "dallas", "houston", "seattle", "denver", "chicago", "boston",
    "atlanta", "miami", "phoenix", "portland", "nashville", "charlotte",
    "raleigh", "pittsburgh", "philadelphia", "detroit", "minneapolis",
    "columbus", "indianapolis", "san diego", "san jose", "san francisco",
    "los angeles", "sacramento", "las vegas", "baltimore", "brooklyn",
    "redmond", "mountain view", "palo alto", "sunnyvale", "cupertino",
    "menlo park", "santa clara", "santa monica", "st. louis", "st louis",
    "salt lake city",
}

US_INDICATOR_PHRASES = [
    "united states", "usa", "u.s.a", "u.s.", "remote - us", "remote (us)",
    "remote, us", "us remote", "(us)", "remote-us", "remote us", "remote us,",
    "district of columbia", "bay area", "silicon valley",
]


def _has_us_signal(segment: str) -> bool:
    low = segment.lower()
    if any(phrase in low for phrase in US_INDICATOR_PHRASES):
        return True
    if any(f" {name} " in f" {low} " for name in US_STATE_NAMES):
        return True
    if any(f" {city} " in f" {low} " for city in MAJOR_US_CITIES):
        return True
    # "City, ST" pattern, e.g. "Austin, TX" / "New York, NY"
    for m in re.finditer(r",\s*([A-Za-z]{2})\b", segment):
        if m.group(1).upper() in US_STATE_ABBR:
            return True
    # bare "US" as its own word/token, case-sensitive (lowercase "us" is
    # usually the pronoun, not the country, e.g. inside other words)
    if re.search(r"\bUS\b", segment):
        return True
    return False


def is_us_location(location: str) -> bool:
    """True if at least one location in a (possibly multi-location,
    semicolon-joined) location string is US-based. Blank/ambiguous
    locations return False -- strict US-only, per Shiva's request."""
    if not location or not location.strip():
        return False
    return any(_has_us_signal(seg) for seg in location.split(";"))
