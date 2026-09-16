# Shiva's Job Search Tool

Finds fresh Software/AI job postings across 11+ sources, scores them two
ways against your real profile, tailors an ATS-optimized resume PDF per
posting with measured keyword coverage, and preps outreach research
(one-line company brief, hiring contacts, draft messages). Never auto-applies
anywhere, never sends a message on your behalf — every output is a draft you
review and send yourself.

**Full build spec:** `MASTER-BUILD-PROMPT.md` — this is what you paste into
Claude Code to build the whole system. `CLAUDE.md` is a quick-reference
summary Claude Code reads automatically once it's built.

## What it does

| Step | Command | What happens |
|---|---|---|
| Scrape | `python cli.py scrape` | Pulls from all 11+ sources, dedupes, filters to last 24h (falls back to 48h) |
| Score | `python cli.py score` | Deterministic keyword score + AI reasoning score, side by side, nothing hidden |
| Tailor | `python cli.py tailor --job-id ID --format pdf` | Full tailored resume PDF, measured coverage (e.g. 41% → 78%), honest gaps listed |
| Research | (bundled into tailor / dashboard button) | One-line company brief, hiring contacts, draft outreach messages |
| Track | `python cli.py track --job-id ID --status applied` | Logs to `data/tracker.csv`, hides the job until reposted |
| Applied list | `python cli.py applied` | Everything you've marked applied, most recent first |
| Add to profile | `python cli.py profile-add` | Interactively add a new skill/cert/project — same as Tab 4 on the dashboard |
| Dashboard | `python server.py` | Full 4-tab interface at `localhost:9009` |

## The dashboard (4 tabs)

`python server.py` → **http://localhost:9009**

1. **Jobs Feed** — daily brief panel, then jobs grouped by recency
   (<1h / <24h / this week / this month), sorted by AI score within each
   group. Every job shows regardless of score — nothing is hidden, long
   shots (<25) just render lower and grayed out. Duplicate postings found on
   2+ sources get a `Duplicate` badge. Buttons per card: `View posting`,
   `Research + Tailor`, `Mark Applied`.
2. **Applied Jobs** — your full application history: company, title, date,
   scores at time of application, status (editable), notes.
3. **Skills Gap Analysis** — aggregates the honest gaps from every tailored
   resume, ranks the top 10 missing skills by how often they block you,
   flags missing certifications, suggests what to learn first.
4. **Your Profile Updates** — add a skill, certification, or project the
   moment you finish it. Writes straight to `profile.json`. The very next
   tailored resume picks it up — no rebuild, no restart.

`Mark Applied` hides that posting and logs it to the Applied Jobs tab. If the
same company reposts the same role with a newer date, it reappears — they're
hiring again, worth a fresh look.

## Setup

```bash
cd shiva-job-search
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium     # needed for LinkedIn/Indeed/Workday/etc scraping
cp .env.example .env            # then fill in your real values, see below
```

**You need three things in `.env`:**
1. `ANTHROPIC_API_KEY` — from https://console.anthropic.com/settings/keys
   (separate from your claude.ai subscription, billed per token, a few cents
   per job scored/tailored)
2. `SCRAPER_LINKEDIN_USERNAME` / `SCRAPER_LINKEDIN_PASSWORD` — a **secondary**
   LinkedIn account, never your real one
3. `SCRAPER_INDEED_USERNAME` / `SCRAPER_INDEED_PASSWORD` — a **secondary**
   Indeed account, never your real one

Every other source (Greenhouse, Lever, Ashby, SmartRecruiters, Workday,
Google `site:` search, WayUp, ZipRecruiter, Glassdoor, Simplify, Y
Combinator, Jobright, Otta, Welcome to the Jungle, Built In, USAJOBS.gov)
needs no login at all.

**`.env` is already in `.gitignore` — it will never get committed.**

## Using it with Claude Code

```bash
claude .
```

Then paste the full contents of `MASTER-BUILD-PROMPT.md`. Tell it to start
with Part 3a (the Google `site:` search scraper) and stop to show you real
jobs before building the rest — that's the fastest way to confirm the
approach works before investing in every other scraper.

Claude Code reads `CLAUDE.md` for the ongoing workflow and `profile.json` for
your standing rules (no OPT/visa language, no Farmside, no inflated metrics,
no fabricated skills, etc.) and enforces them on every generated resume or
outreach draft.

## Adding companies to track

`config/companies.yaml` has a starter list of 30+ pre-verified Greenhouse
tokens. It is explicitly **not a ceiling** — the Google `site:` search
scraper finds any company on Greenhouse/Lever/Ashby/Workday regardless of
whether it's in this file, and the file itself grows over time as Claude
Code (or you) find more tokens. If you're using Claude Code, just ask it to
look up the token for a specific company and add it.

## Matching philosophy — aggressive, no mercy

Any posting with "Software" or "AI" in the title or description gets
surfaced and tailored, even at 40% overlap with your profile. See
`profile.json` → `target_tracks` for the full expanded keyword list (SWE,
AI/ML, Full Stack/Backend, Data Engineering, Agentic AI, GenAI, LLM, etc.)
and `excluded_tracks` for what's explicitly filtered out (IT Support, SOC,
Help Desk, Network Admin — dropped at ingest, before scoring).

## A note on scope

Every output here is a draft. You review it, you click apply, you send the
message. Rate limiting is built in (3–8s random delays, exponential backoff)
specifically so the secondary LinkedIn/Indeed accounts don't get flagged —
but if one does get flagged anyway, that's the point of using a secondary
account: replace it, your real profile is never at risk.

## Suggested daily rhythm

1. `python cli.py scrape` — morning, ~15–20 min for a full pass
2. `python server.py` — open the dashboard, check the daily brief
3. Work down the "Posted < 1 hour" and "< 24 hours" sections first —
   that's your first-applicant window
4. `Research + Tailor` on anything worth applying to, download the PDF,
   apply manually, send the drafted outreach
5. `Mark Applied` as you go
6. Repeat in the evening — two passes a day is how you stay inside the
   24-hour posting window
7. Check the Skills Gap tab weekly, update your profile in Tab 4 the moment
   you finish a cert or project
