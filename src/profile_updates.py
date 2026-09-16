"""
Profile self-updates (Part 8, Tab 4).

Writes directly to profile.json. Shiva is the only user of this tool --
no approval step, since it's his own data about himself. The very next
tailor run reads profile.json fresh (no caching), so a skill added here is
usable immediately.
"""
import json


def _load(profile_path: str) -> dict:
    with open(profile_path) as f:
        return json.load(f)


def _save(profile_path: str, profile: dict):
    with open(profile_path, "w") as f:
        json.dump(profile, f, indent=2)


def add_skill(profile_path: str, group: str, skill: str):
    profile = _load(profile_path)
    skills = profile.setdefault("skills", {})
    bucket = skills.setdefault(group, [])
    if skill not in bucket:
        bucket.append(skill)
    _save(profile_path, profile)


def add_certification(profile_path: str, name: str):
    profile = _load(profile_path)
    certs = profile.setdefault("certifications_earned", [])
    if name not in certs:
        certs.append(name)
    _save(profile_path, profile)


def add_project(profile_path: str, name: str, description: str, link: str = ""):
    profile = _load(profile_path)
    projects = profile.setdefault("projects", [])
    entry = {"name": name, "bullets": [description]}
    if link:
        entry["link"] = link
    projects.append(entry)
    _save(profile_path, profile)
