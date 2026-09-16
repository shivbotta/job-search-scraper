# Shiva's Job Search Tool

This project finds fresh SWE/AI job postings across 11+ sources, scores them
against Shiva's real profile, tailors a resume PDF per posting with measured
keyword coverage, and preps outreach research (company brief, hiring contacts,
draft messages). It does **not** auto-apply anywhere and does **not** send any
message on Shiva's behalf — every output is a draft he reviews and sends himself.

**Full build spec:** see `MASTER-BUILD-PROMPT.md` in the project root. This file
is a quick-reference summary; the build prompt is the source of truth for what
to build and in what order.

## Candidate profile

The full structured profile lives in `profile.json`. Always read it before
scoring or tailoring anything. It contains `standing_rules` — treat these as
hard constraints on every resume, cover letter, or outreach message generated:

- No work authorization / visa / OPT / sponsorship language, anywhere, ever
- No mention of Farmside Technologies or India-based work experience
- No metrics beyond what's in the profile — KwikJobs is locked at
  **10,000+ users / 1,000+ businesses**, never inflate
- No certifications listed as earned unless they're in `certifications_earned`
  — AWS Certified Cloud Practitioner is in `certifications_in_progress_DO_NOT_LIST`,
  never include it in any form
- No generic AI-sounding phrasing, no founder-bragging tone
- No fabricated skills — reorder/rephrase real profile content only. If a JD
  demands something not in `profile.json`, it goes in `honest_gaps`, never on
  the resume itself
- `excluded_tracks.never_target` lists roles Shiva is NOT pursuing (IT Support,
  Help Desk, SOC, Security Analyst, Network Admin, SysAdmin) — drop these at
  scrape ingest, never surface them on the dashboard

## Matching philosophy — aggressive, no mercy

Shiva wants EVERY posting with "Software" or "AI" in the title or description
surfaced and tailored, even at 40% overlap with his profile. Do not apply
strict filtering. Score honestly, but don't hide anything — every job appears
on the dashboard, even long-shots, clearly labeled by score band. See
`profile.json` -> `target_tracks` for the full expanded keyword list (SWE,
AI/ML, Full Stack/Backend, Data Engineering, Agentic AI, GenAI, LLM, etc.)

## Sources (11+, open-ended company list)

**Public APIs, no login:**
Greenhouse, Lever, Ashby, SmartRecruiters -- tokens in `config/companies.yaml`
(a starter list -- verify tokens live and add more as you find them)

**Web scrape via Google site: search (no login, no fixed company list):**
This is what makes company coverage open-ended. Query pattern:
`site:boards.greenhouse.io ("software engineer" OR "ai engineer" OR ...)`
Rotate through role keywords from `profile.json` -> `target_tracks`. This finds
ANY company on these ATS platforms, not just ones pre-listed in companies.yaml.

**Secondary-account login required (credentials in .env):**
LinkedIn, Indeed -- use `SCRAPER_LINKEDIN_USERNAME/PASSWORD` and
`SCRAPER_INDEED_USERNAME/PASSWORD`. These are throwaway accounts, never
Shiva's real ones. Rate limit hard: 3-8s random delays, exponential backoff
on any 429/block signal, log in once per run, log out cleanly.

**Web scrape, no login:**
WayUp, ZipRecruiter, Glassdoor, Simplify Jobs, Y Combinator Work at a Startup,
Jobright, Otta, Welcome to the Jungle, Built In, USAJOBS.gov (federal -- has a
free public API instead of scraping)

## Workflow

### 1. Scrape everything
```
python cli.py scrape
```
Pulls from all sources, dedupes (same posting from 2 sources -> kept once,
flagged `duplicate: true` with the source list), filters to last 24h primary
/ 48h fallback, writes to `data/jobs_seen.json`.

### 2. Score
```
python cli.py score
```
Dual score per job: deterministic keyword match (transparent, shows matched/
missing keywords) + AI reasoning score (0-100, via Anthropic API, explains
partial-match angles for weak scores). Both stored, both shown on dashboard.
**Nothing gets hidden** -- every job shows, even below 25.

### 3. Dashboard
```
python server.py
```
Serves at `localhost:9009`, four tabs:
- **Jobs Feed** -- daily brief + jobs grouped by recency (<1h, <24h, week,
  month), sorted by AI score within each group
- **Applied Jobs** -- application tracker (company, title, date, status, notes)
- **Skills Gap Analysis** -- aggregates `honest_gaps` across all tailored
  resumes, ranks missing skills by ROI (frequency x ease x impact), suggests
  a learning path
- **Your Profile Updates** -- add a newly learned skill / earned cert /
  completed project here; writes directly to `profile.json`; next tailored
  resume picks it up immediately, no rebuild needed

### 4. Research + tailor (per job, from dashboard button or CLI)
```
python cli.py tailor --job-id <id> --format pdf
```
Token-optimized research output: one-line company brief (what they do, field,
size -- NOT a paragraph), hiring contacts (name/title/LinkedIn/email if public,
confidence level), search queries if no named contact found, connection note
draft (<300 chars), follow-up note draft. No "why this role exists" essay, no
3-bullet role summary -- those were cut to spend more tokens on the resume
itself.

Resume tailoring: extract JD keywords -> measure baseline coverage -> map each
keyword to real profile evidence (direct match / equivalent rephrase / no
match) -> rewrite bullets with real content only -> measure tailored coverage
(target 70%+) -> ATS format check (single column, standard font, Month YYYY
dates, hyperlinked contact line) -> verify keywords survived by re-extracting
the PDF text -> scan against `standing_rules` before showing output.

**PDF only, no DOCX.**

### 5. Mark applied
Dashboard button or:
```
python cli.py track --job-id <id> --status applied
```
Hides from Jobs Feed, logs to Applied Jobs tab, prevents the same posting
reappearing unless that company reposts the same role with a newer date.

### 6. Check application history
```
python cli.py applied
```

## Hard rules (non-negotiable, enforced at code level not just prompt level)

1. Never touch Shiva's real LinkedIn/Indeed accounts -- secondary accounts only
2. Never auto-apply, never send a message automatically -- everything is a
   draft Shiva sends himself
3. Never fabricate a skill, metric, or claim not in `profile.json` or told to
   you directly in a session -- put it in `honest_gaps` instead
4. Never exceed KwikJobs locked metrics (10,000+ / 1,000+)
5. Never list AWS Cloud Practitioner as earned
6. Never include OPT/visa/sponsorship/Farmside language anywhere
7. Never hide a job from the dashboard regardless of score
8. Rate limit every scraper: 3-8s random delay, exponential backoff on errors
9. Drop excluded-track postings (IT Support/SOC/etc.) at ingest, before they
   ever reach scoring or the dashboard
