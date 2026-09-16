# MASTER BUILD PROMPT — Shiva's Job Search System

Paste everything below the `═══` line into Claude Code, opened inside the
`shiva-job-search/` folder.

---

## What this system is

An on-demand job discovery and application-prep engine. You run it, it scrapes
every reachable source in the US tech market, scores every posting against your
profile aggressively, researches who to contact at each company, and generates
a keyword-optimized resume per posting. You apply and send outreach yourself.

**Its task in one line:** surface every AI/software job in the US you could
plausibly get, within hours of it going live, with a tailored resume and a
named human to contact — so your only remaining job is to hit send.

---

## Framework

```
1. DISCOVER   6 job boards + ~120 company career pages + Google site: search
2. NORMALIZE  every posting → one schema
3. DEDUPE     same role from 2 sources → keep newest
4. SCORE      deterministic keyword + AI reasoning, side by side
5. BRIEF      daily stats panel (discovered / strong / excellent / <1hr / <24hr)
6. RESEARCH   company brief + recruiter/hiring-manager identification
7. TAILOR     per-JD resume with measured ATS keyword coverage before/after
8. TRACK      mark applied → hides until reposted
```

---

═══════════════════════════════════════════════════════════════════
## THE PROMPT (everything below goes into Claude Code)
═══════════════════════════════════════════════════════════════════

You are building out the `shiva-job-search/` project. Read `CLAUDE.md`,
`profile.json`, `cli.py`, `server.py`, `src/dashboard.py`, `src/tracker.py`,
`src/tailor.py`, `src/scoring/deterministic.py`, and `src/scoring/ai_scorer.py`
before writing anything. A working scaffold exists — extend it, don't rewrite it.

### Hard rules (non-negotiable, override anything else in this prompt)

1. **Secondary accounts only** for LinkedIn/Indeed scraping. Log in per run,
   log out cleanly, destroy cookies. Never touch the primary account.
2. **Never auto-apply, never auto-send a message, never modify any external
   system.** Read-only everywhere except Shiva's own local files.
3. **Never fabricate on a resume.** Tailoring reorders, rewords, and surfaces
   real content from `profile.json`. It never invents a skill, tool, employer,
   metric, or certification. If a JD demands something Shiva doesn't have, the
   tailor reports it as a gap — it does not manufacture it. A resume that lies
   gets him through ATS and destroyed in the technical screen.
4. **Never claim guaranteed outcomes** in code comments, UI text, or output.
   No "unrejectable", no "guaranteed interview". Report measured ATS keyword
   coverage numbers instead — that's the real, honest signal.
5. **Enforce `profile.json` `standing_rules`** on every generated artifact:
   no visa/OPT/sponsorship language, no Farmside Technologies, no inflated
   metrics, no uncertified certifications.
6. **Drop excluded roles at ingest.** Any posting whose title matches
   `profile.json` `excluded_tracks.never_target` (IT Support, Help Desk, SOC,
   Security Analyst, Network/SysAdmin, etc.) is discarded during scraping and
   never reaches the dashboard. Shiva is targeting Software Engineer / AI
   Engineer roles only.
7. **Rate limit everything.** Randomized 3–8s delays. Exponential backoff on
   429 (1h → 2h → 4h). Never parallel-hammer one domain.

---

### PART 1 — Use the corrected `profile.json`

A corrected `profile.json` ships with this project. **Read it, do not rewrite it.**
It is the single source of truth and is already aligned with Shiva's Master
Background. Key facts it encodes that you must respect:

- **Four target tracks only:** Software Engineering (Entry/New Grad), AI/ML
  Engineering, Full Stack/Backend, Data Engineering.
- **`excluded_tracks.never_target`** lists 16 role types Shiva is explicitly NOT
  pursuing — IT Support, Help Desk, Desktop Support, IT Analyst, Service Desk,
  Technical Support, SOC Analyst, SOC Tier 1, Security Analyst, Security
  Operations, Network Administrator, Systems Administrator, SysAdmin, Network
  Engineer, Information Security Analyst. **Never scrape for these, never rank
  them, never tailor toward them, never suggest pivoting to them.** If a scraped
  posting's title matches any of these, drop it at ingest — it should not reach
  the dashboard at all.
- **Security/networking projects exist in the profile** (pen-testing labs, Cisco
  labs, DB security project) but each carries a `usage_note` marking it BRIEF
  MENTION ONLY, never a lead project. Respect that in tailoring.
- **KwikJobs metrics are locked at 10,000+ users / 1,000+ businesses.**
- **AWS Certified Cloud Practitioner is in `certifications_in_progress_DO_NOT_LIST`**
  — never put it on a resume in any form, not even as "in progress".
- Several projects carry a `missing_data` field (thread pool benchmark numbers,
  model accuracy/F1, GitHub links). Keep those bullets qualitative and surface
  the missing item as needed input. Never estimate.

If Shiva completes a certification or project later, he adds it via
`python cli.py profile-add` and everything downstream picks it up on the next run.

### PART 2 — Company career page registry

Create `config/companies.yaml` with the roster below. These get scraped directly
via their ATS public APIs (no login, no ToS issue) or via their careers site.

**Important:** ATS board tokens change. For each company, verify the token by
visiting its careers page and reading the URL or the network request to the ATS
API. If a token 404s, use web search to find the current careers URL rather than
guessing. Log every failure so Shiva can see which need fixing.

```yaml
# ══ BIG TECH / FAANG+ ══
# Most run proprietary ATS -- scrape their careers site directly or via
# Google site: search. Workday-based ones use the myworkdayjobs pattern.
big_tech:
  - {name: Google, careers: "https://www.google.com/about/careers/applications/jobs/results/", ats: custom}
  - {name: Amazon, careers: "https://www.amazon.jobs/en/search", ats: custom}
  - {name: Apple, careers: "https://jobs.apple.com/en-us/search", ats: custom}
  - {name: Microsoft, careers: "https://jobs.careers.microsoft.com/global/en/search", ats: custom}
  - {name: Meta, careers: "https://www.metacareers.com/jobs", ats: custom}
  - {name: Netflix, careers: "https://explore.jobs.netflix.net/careers", ats: custom}
  - {name: IBM, careers: "https://www.ibm.com/careers/search", ats: custom}
  - {name: Oracle, careers: "https://careers.oracle.com/jobs", ats: custom}
  - {name: Salesforce, careers: "https://careers.salesforce.com/en/jobs/", ats: custom}
  - {name: Adobe, careers: "https://careers.adobe.com/us/en/search-results", ats: workday}
  - {name: Cisco, careers: "https://jobs.cisco.com/jobs/SearchJobs", ats: custom}
  - {name: Dell, careers: "https://jobs.dell.com/search-jobs", ats: custom}
  - {name: HP, careers: "https://jobs.hp.com/search-jobs", ats: custom}
  - {name: Intel, careers: "https://jobs.intel.com/en/search-jobs", ats: custom}
  - {name: Qualcomm, careers: "https://careers.qualcomm.com/careers", ats: custom}
  - {name: Texas Instruments, careers: "https://careers.ti.com/search-jobs/", ats: custom}
  - {name: Broadcom, careers: "https://www.broadcom.com/company/careers", ats: workday}
  - {name: VMware, careers: "https://careers.vmware.com/main/jobs", ats: custom}
  - {name: SAP, careers: "https://jobs.sap.com/search/", ats: custom}
  - {name: ServiceNow, careers: "https://careers.servicenow.com/jobs/", ats: custom}
  - {name: Workday, careers: "https://workday.wd5.myworkdayjobs.com/Workday", ats: workday}
  - {name: Uber, careers: "https://www.uber.com/us/en/careers/list/", ats: custom}
  - {name: Lyft, careers: "https://www.lyft.com/careers", ats: greenhouse}
  - {name: Airbnb, careers: "https://careers.airbnb.com/positions/", ats: greenhouse}
  - {name: DoorDash, careers: "https://careers.doordash.com/", ats: greenhouse}
  - {name: Pinterest, careers: "https://www.pinterestcareers.com/jobs/", ats: custom}
  - {name: Snap, careers: "https://careers.snap.com/jobs", ats: custom}
  - {name: Spotify, careers: "https://www.lifeatspotify.com/jobs", ats: custom}
  - {name: Dropbox, careers: "https://jobs.dropbox.com/all-jobs", ats: greenhouse}
  - {name: Block/Square, careers: "https://block.xyz/careers/jobs", ats: smartrecruiters}
  - {name: eBay, careers: "https://jobs.ebayinc.com/us/en/search-results", ats: custom}
  - {name: PayPal, careers: "https://careers.pypl.com/search-results", ats: workday}
  - {name: Intuit, careers: "https://jobs.intuit.com/search-jobs", ats: workday}
  - {name: Cloudflare, careers: "https://www.cloudflare.com/careers/jobs/", ats: greenhouse}
  - {name: Atlassian, careers: "https://www.atlassian.com/company/careers/all-jobs", ats: custom}
  - {name: Twilio, careers: "https://www.twilio.com/en-us/company/jobs", ats: greenhouse}
  - {name: Zoom, careers: "https://careers.zoom.us/jobs/search", ats: custom}
  - {name: Slack, careers: "https://slack.com/careers", ats: greenhouse}

# ══ SEMICONDUCTOR / HARDWARE / AI COMPUTE ══
semiconductor:
  - {name: NVIDIA, careers: "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite", ats: workday}
  - {name: AMD, careers: "https://careers.amd.com/careers-home/jobs", ats: custom}
  - {name: Micron, careers: "https://micron.eightfold.ai/careers", ats: eightfold}
  - {name: Applied Materials, careers: "https://careers.appliedmaterials.com/jobs", ats: custom}
  - {name: Lam Research, careers: "https://careers.lamresearch.com/", ats: custom}
  - {name: Analog Devices, careers: "https://careers.analog.com/", ats: workday}
  - {name: Marvell, careers: "https://www.marvell.com/company/careers.html", ats: workday}
  - {name: Arm, careers: "https://careers.arm.com/", ats: workday}
  - {name: Western Digital, careers: "https://jobs.westerndigital.com/", ats: custom}
  - {name: Seagate, careers: "https://www.seagate.com/careers/", ats: workday}

# ══ AI LABS & AI-NATIVE COMPANIES ══
ai_companies:
  - {name: Anthropic, token: anthropic, ats: greenhouse}
  - {name: OpenAI, careers: "https://openai.com/careers/search/", ats: ashby}
  - {name: Scale AI, careers: "https://scale.com/careers", ats: greenhouse}
  - {name: Databricks, careers: "https://www.databricks.com/company/careers/open-positions", ats: greenhouse}
  - {name: Hugging Face, careers: "https://apply.workable.com/huggingface/", ats: workable}
  - {name: Cohere, careers: "https://cohere.com/careers", ats: lever}
  - {name: Perplexity, careers: "https://www.perplexity.ai/careers", ats: ashby}
  - {name: Runway, careers: "https://runwayml.com/careers/", ats: greenhouse}
  - {name: Adept, careers: "https://www.adept.ai/careers", ats: ashby}
  - {name: Mistral AI, careers: "https://mistral.ai/careers", ats: ashby}
  - {name: Together AI, careers: "https://www.together.ai/careers", ats: ashby}
  - {name: Weights & Biases, careers: "https://wandb.ai/site/careers", ats: greenhouse}
  - {name: LangChain, careers: "https://www.langchain.com/careers", ats: ashby}
  - {name: Pinecone, careers: "https://www.pinecone.io/careers/", ats: greenhouse}
  - {name: Glean, careers: "https://www.glean.com/careers", ats: greenhouse}
  - {name: Harvey, careers: "https://www.harvey.ai/careers", ats: ashby}
  - {name: Sierra, careers: "https://sierra.ai/careers", ats: ashby}
  - {name: Cursor/Anysphere, careers: "https://cursor.com/careers", ats: ashby}
  - {name: Replit, careers: "https://replit.com/careers", ats: ashby}
  - {name: Notion, careers: "https://www.notion.so/careers", ats: greenhouse}
  - {name: Figma, careers: "https://www.figma.com/careers/", ats: greenhouse}
  - {name: Vercel, careers: "https://vercel.com/careers", ats: ashby}
  - {name: Supabase, careers: "https://supabase.com/careers", ats: ashby}
  - {name: MongoDB, careers: "https://www.mongodb.com/careers", ats: greenhouse}
  - {name: Snowflake, careers: "https://careers.snowflake.com/us/en/search-results", ats: custom}
  - {name: Palantir, careers: "https://www.palantir.com/careers/", ats: lever}

# ══ TIER 1: FINANCE / FINTECH / BANKING (HIGHEST PRIORITY) ══
finance_tier1:
  - {name: JPMorgan Chase, careers: "https://careers.jpmorgan.com/us/en/students/programs", ats: custom}
  - {name: Morgan Stanley, careers: "https://www.morganstanley.com/careers/career-opportunities-search", ats: custom}
  - {name: Goldman Sachs, careers: "https://higher.gs.com/roles", ats: custom}
  - {name: BlackRock, careers: "https://careers.blackrock.com/early-careers/", ats: workday}
  - {name: Citadel, careers: "https://www.citadel.com/careers/open-opportunities/", ats: greenhouse}
  - {name: Two Sigma, careers: "https://careers.twosigma.com/careers/SearchJobs", ats: custom}
  - {name: Jane Street, careers: "https://www.janestreet.com/join-jane-street/open-roles/", ats: custom}
  - {name: Bank of America, careers: "https://careers.bankofamerica.com/en-us/students-and-graduates", ats: custom}
  - {name: Wells Fargo, careers: "https://www.wellsfargojobs.com/en/jobs/", ats: custom}
  - {name: Citi, careers: "https://jobs.citi.com/search-jobs", ats: custom}
  - {name: Capital One, careers: "https://www.capitalonecareers.com/search-jobs", ats: custom}
  - {name: American Express, careers: "https://aexp.eightfold.ai/careers", ats: eightfold}
  - {name: Charles Schwab, careers: "https://www.schwabjobs.com/search-jobs", ats: custom}
  - {name: Fidelity, careers: "https://jobs.fidelity.com/search-jobs", ats: custom}
  - {name: Visa, careers: "https://corporate.visa.com/en/jobs/", ats: workday}
  - {name: Mastercard, careers: "https://careers.mastercard.com/us/en/search-results", ats: workday}
  - {name: Stripe, careers: "https://stripe.com/jobs/search", ats: greenhouse}
  - {name: Plaid, careers: "https://plaid.com/careers/openings/", ats: greenhouse}
  - {name: Robinhood, careers: "https://careers.robinhood.com/", ats: greenhouse}
  - {name: Coinbase, careers: "https://www.coinbase.com/careers/positions", ats: greenhouse}
  - {name: Affirm, careers: "https://www.affirm.com/careers/open-roles", ats: greenhouse}
  - {name: Chime, careers: "https://careers.chime.com/", ats: greenhouse}
  - {name: Brex, careers: "https://www.brex.com/careers", ats: greenhouse}
  - {name: Ramp, careers: "https://ramp.com/careers", ats: ashby}
  - {name: Fiserv, careers: "https://www.fiserv.com/en/about-fiserv/careers.html", ats: workday}
  - {name: FIS, careers: "https://careers.fisglobal.com/us/en/search-results", ats: workday}
  - {name: Nasdaq, careers: "https://www.nasdaq.com/careers", ats: workday}
  - {name: Bloomberg, careers: "https://careers.bloomberg.com/job/search", ats: custom}
  - {name: S&P Global, careers: "https://careers.spglobal.com/", ats: workday}
  - {name: Vanguard, careers: "https://www.vanguardjobs.com/", ats: custom}

# ══ DEFENSE / AEROSPACE / SPACE ══
defense_aerospace:
  - {name: Lockheed Martin, careers: "https://www.lockheedmartinjobs.com/search-jobs", ats: custom}
  - {name: Northrop Grumman, careers: "https://www.northropgrumman.com/jobs/", ats: custom}
  - {name: Raytheon/RTX, careers: "https://careers.rtx.com/global/en/search-results", ats: workday}
  - {name: Boeing, careers: "https://jobs.boeing.com/search-jobs", ats: custom}
  - {name: General Dynamics, careers: "https://www.gd.com/careers", ats: custom}
  - {name: L3Harris, careers: "https://careers.l3harris.com/search-jobs", ats: custom}
  - {name: BAE Systems, careers: "https://jobs.baesystems.com/global/en/search-results", ats: workday}
  - {name: SpaceX, careers: "https://www.spacex.com/careers/jobs/", ats: greenhouse}
  - {name: Blue Origin, careers: "https://www.blueorigin.com/careers/", ats: greenhouse}
  - {name: Rocket Lab, careers: "https://www.rocketlabusa.com/careers/", ats: greenhouse}
  - {name: Anduril, careers: "https://www.anduril.com/careers/", ats: lever}
  - {name: Relativity Space, careers: "https://www.relativityspace.com/careers", ats: greenhouse}
  - {name: Planet Labs, careers: "https://www.planet.com/company/careers/", ats: greenhouse}
  - {name: Firefly Aerospace, careers: "https://fireflyspace.com/careers/", ats: greenhouse}
  - {name: Axiom Space, careers: "https://www.axiomspace.com/careers", ats: greenhouse}
  - {name: Leidos, careers: "https://careers.leidos.com/search/jobs", ats: custom}
  - {name: Booz Allen Hamilton, careers: "https://careers.boozallen.com/", ats: custom}
  - {name: SAIC, careers: "https://jobs.saic.com/", ats: custom}
  - {name: MITRE, careers: "https://careers.mitre.org/us/en/search-results", ats: workday}

# ══ HEALTHCARE / BIOTECH / HEALTH TECH ══
healthcare:
  - {name: UnitedHealth/Optum, careers: "https://careers.unitedhealthgroup.com/search-jobs", ats: custom}
  - {name: CVS Health, careers: "https://jobs.cvshealth.com/search-jobs", ats: custom}
  - {name: Epic Systems, careers: "https://careers.epic.com/", ats: custom}
  - {name: Cerner/Oracle Health, careers: "https://careers.oracle.com/jobs", ats: custom}
  - {name: Teladoc, careers: "https://www.teladochealth.com/careers/", ats: greenhouse}
  - {name: Oscar Health, careers: "https://www.hioscar.com/careers", ats: greenhouse}
  - {name: Tempus, careers: "https://www.tempus.com/careers/", ats: greenhouse}
  - {name: Flatiron Health, careers: "https://flatiron.com/careers/open-positions", ats: greenhouse}
  - {name: Moderna, careers: "https://modernatx.eightfold.ai/careers", ats: eightfold}
  - {name: Illumina, careers: "https://www.illumina.com/company/careers.html", ats: workday}

# ══ INSURANCE ══
insurance:
  - {name: Progressive, careers: "https://www.progressive.com/careers/", ats: custom}
  - {name: State Farm, careers: "https://www.statefarm.com/careers", ats: custom}
  - {name: Allstate, careers: "https://www.allstate.jobs/", ats: custom}
  - {name: Liberty Mutual, careers: "https://jobs.libertymutualgroup.com/", ats: custom}
  - {name: Travelers, careers: "https://careers.travelers.com/", ats: workday}
  - {name: USAA, careers: "https://www.usaajobs.com/", ats: custom}
  - {name: Lemonade, careers: "https://www.lemonade.com/careers", ats: greenhouse}
  - {name: Root Insurance, careers: "https://www.joinroot.com/careers/", ats: greenhouse}

# ══ AUTOMOTIVE / MOBILITY ══
automotive:
  - {name: Tesla, careers: "https://www.tesla.com/careers/search/", ats: custom}
  - {name: Rivian, careers: "https://careers.rivian.com/", ats: greenhouse}
  - {name: Lucid Motors, careers: "https://careers.lucidmotors.com/", ats: greenhouse}
  - {name: Ford, careers: "https://corporate.ford.com/careers.html", ats: workday}
  - {name: General Motors, careers: "https://search-careers.gm.com/en/jobs/", ats: workday}
  - {name: Waymo, careers: "https://careers.withwaymo.com/jobs/search", ats: greenhouse}
  - {name: Cruise, careers: "https://getcruise.com/careers/jobs/", ats: greenhouse}
  - {name: Aurora, careers: "https://aurora.tech/careers", ats: greenhouse}
  - {name: Zoox, careers: "https://zoox.com/careers", ats: greenhouse}

# ══ SPORTS / MEDIA / GAMING ══
sports_media_gaming:
  - {name: ESPN/Disney, careers: "https://jobs.disneycareers.com/search-jobs", ats: custom}
  - {name: DraftKings, careers: "https://careers.draftkings.com/", ats: greenhouse}
  - {name: FanDuel, careers: "https://www.fanduel.careers/open-positions/", ats: greenhouse}
  - {name: Nike, careers: "https://jobs.nike.com/", ats: custom}
  - {name: Under Armour, careers: "https://careers.underarmour.com/", ats: workday}
  - {name: Riot Games, careers: "https://www.riotgames.com/en/work-with-us/jobs", ats: greenhouse}
  - {name: Electronic Arts, careers: "https://ea.gr8people.com/jobs", ats: custom}
  - {name: Epic Games, careers: "https://www.epicgames.com/site/en-US/careers", ats: greenhouse}
  - {name: Roblox, careers: "https://careers.roblox.com/jobs", ats: greenhouse}
  - {name: Unity, careers: "https://careers.unity.com/", ats: greenhouse}

# ══ ENTERPRISE / CONSULTING / OTHER ══
enterprise_other:
  - {name: Accenture, careers: "https://www.accenture.com/us-en/careers/jobsearch", ats: custom}
  - {name: Deloitte, careers: "https://apply.deloitte.com/careers/SearchJobs", ats: custom}
  - {name: EY, careers: "https://careers.ey.com/ey/search/", ats: custom}
  - {name: PwC, careers: "https://jobs.us.pwc.com/search-jobs", ats: custom}
  - {name: KPMG, careers: "https://www.kpmguscareers.com/search-jobs/", ats: custom}
  - {name: Infosys, careers: "https://career.infosys.com/joblist", ats: custom}
  - {name: Cognizant, careers: "https://careers.cognizant.com/global-en/jobs/", ats: custom}
  - {name: TCS, careers: "https://www.tcs.com/careers", ats: custom}
  - {name: Walmart Global Tech, careers: "https://careers.walmart.com/technology", ats: workday}
  - {name: Target, careers: "https://corporate.target.com/careers/corporate/technology", ats: workday}
  - {name: Home Depot, careers: "https://careers.homedepot.com/", ats: workday}
  - {name: FedEx, careers: "https://careers.fedex.com/", ats: custom}
  - {name: UPS, careers: "https://www.jobs-ups.com/", ats: custom}
  - {name: John Deere, careers: "https://careers.deere.com/", ats: workday}
  - {name: Caterpillar, careers: "https://careers.caterpillar.com/en/jobs/", ats: custom}
  - {name: GE, careers: "https://jobs.gecareers.com/global/en/search-results", ats: workday}
  - {name: Honeywell, careers: "https://careers.honeywell.com/us/en/search-results", ats: workday}
  - {name: Siemens, careers: "https://jobs.siemens.com/careers", ats: custom}
```

**Startup coverage beyond this list:** most VC-backed startups use
Greenhouse, Lever, or Ashby. Rather than enumerating thousands, use the
Google `site:` technique in Part 3 — it reaches every one of them.

---

### PART 3 — Discovery layer

Build `src/scrapers/` with a `BoardScraper` base class. Every scraper returns
the same schema:

```json
{
  "source": "linkedin | indeed | ziprecruiter | handshake | wayfloor |
             greenhouse | lever | ashby | workday | google_ats | manual",
  "company": "...", "job_id": "...", "title": "...", "location": "...",
  "url": "...", "posted_at": "ISO8601", "description_html": "...",
  "discovered_at": "ISO8601"
}
```

**Sources to build, in this order:**

**3a. ATS public APIs** (already partly wired in `src/sources/`) — extend to
cover Greenhouse, Lever, Ashby, SmartRecruiters, Workable, and Workday's public
`myworkdayjobs` JSON endpoints. These need no login and no scraping.

**3b. Google `site:` ATS search** — the highest-leverage source, reaches every
startup and mid-size company not in the roster. Build `src/scrapers/google_ats.py`
using Claude Code's web search. Query pattern:

```
site:boards.greenhouse.io ("software engineer" OR "ai engineer" OR "new grad") past 24 hours
site:jobs.lever.co (...)
site:jobs.ashbyhq.com (...)
site:myworkdayjobs.com (...)
site:smartrecruiters.com (...)
site:apply.workable.com (...)
site:icims.com (...)
site:jobvite.com (...)
```

Rotate through every role keyword from `target_tracks`. Use the search tool's
date filter for the last 24h where available. Fetch each hit to get the full JD.

**3c. Job boards with secondary-account login** — LinkedIn, Indeed, Handshake
via Playwright. ZipRecruiter and Wayfloor may work without login; check first.
Filter to last 48h at ingest. Use `posted_within_hours=48`.

**3d. Big-tech custom career sites** — Google, Amazon, Apple, Microsoft, Meta,
Oracle, IBM, NVIDIA etc. run proprietary search. Most expose an internal JSON
endpoint their own frontend calls — find it via the network tab pattern and use
it. Where that fails, fall back to the Google `site:` approach against their
careers domain. Log which companies fall back so Shiva knows coverage gaps.

**3e. Dedupe** — same role from multiple sources. Match on normalized
company+title, then on URL. Keep the record with the newest `posted_at` and
merge source lists so the dashboard can show "found on LinkedIn + Greenhouse".

---

### PART 4 — Scoring (extend both existing scorers)

Keep the dual-score architecture. Changes:

**Deterministic (`src/scoring/deterministic.py`):**
- Apply `weight` per target track from the new taxonomy
- Add industry tier bonus: tier_1 +8, tier_2 +3, tier_3 +0 (never negative)
- Add a recency bonus: posted <1h +5, <6h +3, <24h +1
- Add an experience-fit penalty: if the JD demands more years than
  `experience_ceiling_years`, subtract proportionally — but never exclude.
  Shiva applies anyway; the score just ranks it lower.

**AI (`src/scoring/ai_scorer.py`):**
- Keep it blunt and honest — it must not inflate. Most jobs should not score 80+.
- Add to its returned JSON: `"partial_match_rationale"` — for jobs scoring
  40–65, explain specifically what transferable angle makes it worth applying to
  anyway. Shiva's instruction is to surface partial matches, not hide them.

**Score bands** (use these labels everywhere):
- 80–100 → **Excellent match**
- 65–79 → **Strong match**
- 45–64 → **Worth applying**
- 25–44 → **Stretch**
- <25 → **Long shot**

**Nothing is hidden, ever.** Shiva's instruction is explicit: no mercy
filtering, show every job regardless of score, clearly labeled by band. A
<25 job still renders on the dashboard, just visually deprioritized (gray,
bottom of its recency group) — never removed from the default view.

---

### PART 5 — Daily brief panel

Add to the top of the dashboard, computed live in `src/dashboard.py`:

```
────────────────────────────────────────────────
  TODAY · Mon Sep 15
  
  Jobs discovered today ............ 87
  Excellent matches (80+) ..........  6
  Strong matches (65-79) ...........  14
  Worth applying (45-64) ...........  31
  
  Posted < 1 hour ..................  9   ← apply now
  Posted < 24 hours ................  31
  
  Applied this week ................  12
  Awaiting response ................  9
  
  Sources live: 8/9   (Handshake failed - check login)
────────────────────────────────────────────────
```

Every number is a clickable filter. "Posted < 1 hour" is visually loudest —
that's the first-applicant window.

---

### PART 6 — Company + contact research (token-optimized, deliberately minimal)

Build `src/research.py`. Shiva explicitly cut the heavier research fields to
reinvest those tokens into deeper resume tailoring (Part 7). Do NOT add back
"why this role exists" or a multi-bullet role summary — both were tried and
removed on purpose. For a given job, produce only:

```json
{
  "company_brief": "ONE line: what they do | field | rough size, e.g. 'OpenAI | AI research lab | 500+ employees'",
  "where_to_apply": "direct application URL",
  "contacts": [
    {"name": "...", "title": "...", "linkedin_url": "...", "email": "if publicly listed, else omit",
     "source": "company team page | press release | job posting byline | github org",
     "confidence": "high | medium | low"}
  ],
  "search_queries_for_shiva": [
    "site:linkedin.com/in \"CompanyName\" \"technical recruiter\"",
    "site:linkedin.com/in \"CompanyName\" \"engineering manager\" austin"
  ],
  "connection_note": "<300 chars, specific, no visa language>",
  "followup_note": "<send 3-4 days later if no reply>"
}
```

Note `email` was added per Shiva's request — if a contact's email is publicly
listed anywhere (company site, GitHub profile, conference bio, press release),
include it so he can send a cold email in addition to LinkedIn outreach. Never
guess an email pattern (e.g. first.last@company.com) unless you have direct
evidence it's correct — a wrong guessed email is worse than none. Dropped
`personalization_angles` as a separate field — fold anything essential into
`connection_note` instead of a standalone list nobody reads.

**How to find contacts without scraping LinkedIn:** use web search against
public sources — the company's own team/about page, press releases, conference
speaker lists, GitHub org members, engineering blog author bylines, and the
recruiter name sometimes printed in the job posting itself. Return
`confidence: low` rather than guessing. Always return `search_queries_for_shiva`
— Google queries Shiva runs himself to find the person on LinkedIn manually.

If Shiva later provides a Hunter.io or Apollo.io API key, wire it in as an
additional source. Do not build that until he provides a key.

---

### PART 7 — Resume tailoring engine

This is the highest-stakes component. Extend `src/tailor.py`.

**The objective:** maximize ATS keyword coverage and recruiter readability
using only true content. Report coverage as a measured number.

**Pipeline:**

1. **Extract the JD's keyword set.** Parse required skills, preferred skills,
   tools, and exact phrasings. Weight by where they appear (title > requirements
   > nice-to-have > boilerplate).

2. **Measure baseline coverage.** Run the base resume against that keyword set.
   Output: `baseline_coverage: 41%`.

3. **Map each JD keyword to real profile evidence.** For each keyword, find
   what in `profile.json` genuinely supports it. Three outcomes:
   - **Direct match** — profile has it explicitly → surface it, use the JD's
     exact phrasing (if the JD says "LLM fine-tuning" and the profile says
     "fine-tuned BERT and DistilBERT", use "LLM fine-tuning" as the header term)
   - **Equivalent match** — profile has the same thing under a different name →
     rephrase to the JD's vocabulary (profile "React Native" ↔ JD "React")
   - **No match** — profile genuinely lacks it → **leave it out and list it in
     `honest_gaps`**. Never invent it.

4. **Rewrite bullets** using real KwikJobs/HypeSquad/project content, reordered
   so the most JD-relevant work is first. Each bullet: action verb + what was
   built + tech used + outcome. Keep every number truthful
   (KwikJobs = 10,000+ users / 1,000+ businesses — never more).

5. **Measure tailored coverage.** Output: `tailored_coverage: 78%`,
   `keywords_added: [...]`, `honest_gaps: [...]`.

6. **ATS format constraints** — the tailored PDF must:
   - Single column, no tables, no text boxes, no headers/footers, no images
   - Standard section headings: SUMMARY, SKILLS, EXPERIENCE, PROJECTS, EDUCATION
   - Standard fonts (Calibri/Arial/Garamond), 10–12pt
   - Dates as `MMM YYYY – MMM YYYY`
   - Skills as plain comma-separated text, not graphics or ratings bars
   - Contact info in the body, never in a header
   - `.pdf` output only (per Shiva's decision — no DOCX)

7. **Verify the output parses.** After generating the PDF, re-extract its raw
   text and confirm every intended keyword survived the format. If any dropped,
   report it. This is the actual ATS-passability check.

8. **Run standing-rules scan** (existing `_violates_rules`) before showing
   anything to Shiva.

**CLI:** `python cli.py tailor --job-id <id> --format pdf`
Outputs to `data/tailored/<job-id>/` with the PDF, a coverage report, and
the honest gaps list.

**Profile updates:** Shiva will finish certifications and projects over the
coming weeks. Two ways to add them, both should exist: `python cli.py
profile-add` (interactive CLI, appends a new cert/project/skill to
`profile.json`) and the dashboard's Tab 4 (Part 8) for the same thing via a
web form. Either path writes to the same `profile.json`, and everything
downstream picks it up automatically on the next tailor run — no rebuild
needed.

---

### PART 8 — Dashboard (4 tabs)

Move the server to **port 9009** (`http://localhost:9009`). Note: ports below
1024 need admin rights, so 9009 is used rather than literal `0009`. Change in
`server.py` and every doc reference.

Build four tabs. All four live in the same dashboard app — this is one page
with tab navigation, not four separate tools.

**Tab 1 — Jobs Feed** (the default/landing tab)
1. Daily brief panel (Part 5)
2. Jobs grouped by recency: **Posted < 1 hour** (loudest, apply-now urgency),
   **< 24 hours**, **This week**, **This month**
3. Within each group, sorted by AI score descending — nothing collapsed,
   nothing hidden, all five score bands render including Long Shot (<25)
4. Each job card shows: score band + both numbers (deterministic + AI),
   company (the one-line brief once researched), title, location, source(s),
   posted-ago, a `Duplicate (also on LinkedIn + Greenhouse)` badge when a
   posting was found on 2+ sources, and three buttons:
   `[View posting]` `[Research + Tailor]` `[Mark Applied]`
5. `[Research + Tailor]` runs Parts 6 and 7 for that job and opens the result
   (research fields + tailored PDF, both shown inline or as a modal)

**Tab 2 — Applied Jobs**
Reads `data/tracker.csv`. Table view: company, title, URL, date applied,
scores at time of application, current status (applied / screening /
interview / rejected / offer — editable dropdown per row), notes (editable
text field per row). Filterable by status.

**Tab 3 — Skills Gap Analysis**
Reads every `honest_gaps` list ever written into `data/tailored/*/report.json`.
Aggregate: count how many jobs demand each missing skill, weight by that job's
score (a gap in an 85-score job counts more than one in a 30-score job).
Render:
- "Top 10 Skills to Learn" ranked by `frequency × weighted_score`, each row
  shows the skill, how many jobs demanded it, and a rough effort label
  (easy/medium/hard — infer from skill type, e.g. a language is medium, a
  paid certification is hard)
- "Certifications Missing" — pull specifically from gaps that are
  certification names, not general skills
- A simple suggested order (most-demanded + least-effort first) — this can be
  a straightforward sort, it does not need an AI call

**Tab 4 — Your Profile Updates**
A form that writes directly to `profile.json`. Three add actions:
- **Add skill** — text input, appends to the relevant `skills` sub-array
- **Add certification** — text input, appends to `certifications_earned`
- **Add project** — name, one-line description, optional GitHub/HuggingFace
  link, appends a new entry to `projects`
No approval step needed — Shiva is the only user, this is his own data. The
very next `[Research + Tailor]` call must read the updated `profile.json`, no
caching, no restart required. This is the mechanism by which Shiva keeps the
tool current as he learns things — treat it as a first-class feature, not an
afterthought settings page.

Keep the existing hide-until-reposted behavior on `[Mark Applied]`.

---

### PART 9 — Build order

Do not build everything at once. Ship in this order, and tell Shiva after each:

1. `profile.json` rewrite (Part 1) + `config/companies.yaml` (Part 2)
2. Google `site:` ATS scraper (Part 3b) — **highest coverage per hour of work**
3. ATS public API scrapers (Part 3a)
4. Scoring updates + score bands (Part 4)
5. Dashboard with daily brief on port 9009 (Parts 5, 8)
6. Resume tailoring engine with coverage measurement + PDF (Part 7)
7. Company/contact research (Part 6)
8. LinkedIn/Indeed/Handshake secondary-account scrapers (Part 3c)
9. Big-tech custom career sites (Part 3d)

**Stop after step 2 and show Shiva real scraped jobs before continuing.** If
Google `site:` search alone surfaces 50+ relevant fresh postings, that validates
the whole approach before more scrapers get built.

### Definition of done

- `python cli.py scrape` returns fresh US postings across all listed industries
- Dashboard at `localhost:9009` shows the daily brief with real counts
- A job posted under an hour ago appears in the top section
- `python cli.py tailor --job-id X --format pdf` produces a PDF with measured
  coverage lift (e.g. 41% → 78%) and an honest gaps list
- Re-extracting that PDF's text confirms the keywords survived
- Research output gives a company brief plus contact leads or the exact Google
  queries to find them
- Nothing fabricated anywhere; no visa/OPT language; no Farmside
- Marking applied hides the job until reposted
