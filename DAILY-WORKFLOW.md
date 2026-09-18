# Daily Workflow — Job Search Dashboard

## Every Day (5 min)

```bash
./daily.sh
```

This does three things:
1. **Scrapes** fresh jobs from Greenhouse, Lever, Ashby, SmartRecruiters, Workable, LinkedIn, Indeed (≤ 1 min)
2. **Scores** them with AI fit + keyword match (≤ 3 min)
3. **Starts the dashboard** at http://localhost:9009

Then:

## In the Dashboard

### 🔍 Browse
- **Jobs Feed** tab (default)
  - See today's brief (discovered/great/strong/decent fit counts)
  - Jobs grouped by recency: last 1h, 24h, week, month
  - Filter by **Source** (Greenhouse, LinkedIn, Indeed, etc.)
  - Filter by **Industry** (AI/ML, Fintech, Tech, Enterprise, etc.)
  - Filters work together (e.g., "Greenhouse + AI/ML")

### 📋 Evaluate
- Look at **fit label** (Great Fit, Strong Fit, Decent Fit, Worth a Shot, Long Shot)
- Click the label to see raw AI score + keyword match %
- Click **View posting** to read the actual job description
- Scroll down to see company brief (if already researched)

### 🔬 Research + Tailor
- Click **Research + Tailor** button on any card
- Wait 30–60 seconds
  - Company brief appears on the card
  - Hiring contacts (name, title, LinkedIn)
  - Draft connection message
  - Draft follow-up message
  - **Open full research + resume** link appears
- Click that link to see:
  - Full research (contacts, search queries, messages)
  - Tailored resume PDF
  - Honest gaps (what the JD asks for that you don't have)

### ✅ Mark Applied
- Click **Mark Applied** when you've applied
- Card fades out, count updates
- Job appears in **Applied** tab
- Auto-hides from feed (won't show again unless they repost)

### 📊 Track Applications
- **Applied** tab shows all applications with status
- Update status dropdown: applied → screening → interview → offer/rejected
- Add notes (salary, contacts, next steps)
- Click **Open posting** to revisit the JD

### 🎯 Skills Gap
- **Skills Gap** tab shows most-requested missing skills
- Ranked by ROI (how many jobs ask for it, how hard to learn, impact)
- Add skills as you learn them in **Profile** tab

### 👤 Profile Updates
- **Profile** tab: add skills, certifications, projects
- Write directly to `profile.json`
- Next Research + Tailor picks them up immediately (no restart)

---

## Weekly (optional)

### Refresh the ATS board tokens
If you notice a company's jobs stopped appearing:
```bash
# Test if a specific source's token is still live
python3 cli.py pull --companies config/companies.yaml
```

### Check source health
Look at the **Sources** panel in the brief:
- Green (ok) = working
- Yellow (blocked) = CAPTCHA or auth wall hit (LinkedIn/Indeed)
- Red (failed) = token dead or API error

If a source is red, it means that source didn't contribute jobs in this run. Check `.env` credentials for LinkedIn/Indeed.

---

## Full CLI Reference

| Command | When to use |
|---------|------------|
| `./daily.sh` | Every day (scrape + score + start dashboard) |
| `python3 cli.py scrape --skip-google` | Scrape without using web-search credits (faster) |
| `python3 cli.py scrape` | Full scrape + Google site: search (slower, more comprehensive) |
| `python3 cli.py score` | Re-score all jobs (when you've updated profile.json) |
| `python3 cli.py pull` | Direct ATS pulls only (no scrapers, no Google search) |
| `python3 cli.py tailor --job-id X` | Manual tailor (CLI version of dashboard button) |
| `python3 cli.py refilter --dry-run` | Test relevance gate on stored jobs (don't write) |

---

## Troubleshooting

**Q: Dashboard won't start**
```bash
# Make sure venv is activated
source venv/bin/activate
python3 server.py
```

**Q: Jobs disappeared from feed**
- They're either >30 days old (auto-filtered) or marked applied (in Applied tab)
- Check **Applied** tab to see what you've already applied to

**Q: LinkedIn/Indeed showing "blocked" status**
- They hit a CAPTCHA or rate limit
- You may need to manually log in to those accounts and solve the CAPTCHA
- Once cleared, run scrape again

**Q: Want to see source/industry breakdown?**
- Look at the **Sources** panel in the daily brief
- It shows job counts per source and whether they're healthy

**Q: Need to add a new company's ATS board?**
- Find the career page URL (e.g., `https://jobs.lever.co/acmecorp`)
- Extract the token (`acmecorp`)
- Add it to `config/companies.yaml` under the right section (greenhouse/lever/ashby)
- Run `./daily.sh` again

---

## Key Numbers to Remember

- **Scrape filter**: Posted in last 30 days only (older jobs hidden)
- **Relevance gate**: ~72% of raw scrapes are dropped (non-engineering roles)
- **Dashboard**: Shows ALL surviving jobs, even long-shots
- **Scoring**: AI score is 0–100 (honest). Keyword match 0–100 (transparent).
- **Fit bands**:
  - Great Fit: 85–100
  - Strong Fit: 70–84
  - Decent Fit: 50–69
  - Worth a Shot: 30–49
  - Long Shot: <30

---

## That's it!

Every day: `./daily.sh`

Then spend time in the dashboard finding, researching, and applying to jobs. The system handles:
- Finding fresh postings across 7+ sources
- Scoring them fairly (no hidden jobs)
- Researching each one (company brief, hiring contacts)
- Tailoring your resume per job (keyword coverage tracked)
- Tracking applications (status, notes, timeline)
