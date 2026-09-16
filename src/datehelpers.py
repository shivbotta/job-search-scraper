"""
Shared date parsing.

Greenhouse gives ISO strings with offsets, Lever gives epoch milliseconds,
Ashby gives ISO strings, manual entries give a plain YYYY-MM-DD. This
normalizes all of them to a naive UTC datetime (or None if unparseable).
"""
import datetime


def parse_posted_at(value):
    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(value / 1000, tz=datetime.timezone.utc).replace(tzinfo=None)
        except (ValueError, OverflowError, OSError):
            return None

    if isinstance(value, str):
        s = value.strip()
        if s.isdigit() and len(s) >= 12:  # looks like epoch milliseconds
            try:
                return datetime.datetime.fromtimestamp(int(s) / 1000, tz=datetime.timezone.utc).replace(tzinfo=None)
            except (ValueError, OverflowError, OSError):
                return None
        s = s.replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(s)
            if dt.tzinfo is not None:
                dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
            return dt
        except ValueError:
            pass
        try:
            return datetime.datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            return None

    return None
