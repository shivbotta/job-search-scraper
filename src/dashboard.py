"""
Dashboard: daily brief (Part 5), 4-tab app shell (Part 8), and per-bucket
source/industry filters.

One page with client-side tab navigation. Tab content is rendered
server-side per page load; actions (mark applied, status/notes edits,
research+tailor, profile updates) and the feed filters hit small JSON
endpoints in server.py.

Filtering is server-side on purpose: the feed is paginated, so filtering
only the ~25 cards currently in the DOM would silently hide matching jobs
deeper in the bucket. Facet counts are computed over the whole bucket.
"""
import datetime
import html as htmlmod

from datehelpers import parse_posted_at
from scoring.bands import fit_label, BAND_KEYS
import hidden as hidden_mod
import tracker as tracker_mod
import skillsgap
import taxonomy

MAX_AGE_DAYS = 30
PAGE_SIZE = 25

UNDATED = "No posting date"

BUCKET_ORDER = [
    "Posted in the last hour",
    "Posted in the last 24 hours",
    "This week",
    "This month",
    UNDATED,
]

BUCKET_KEY_BY_NAME = {
    "Posted in the last hour": "hour",
    "Posted in the last 24 hours": "24h",
    "This week": "week",
    "This month": "month",
    UNDATED: "undated",
}
BUCKET_NAME_BY_KEY = {v: k for k, v in BUCKET_KEY_BY_NAME.items()}

# Status-file keys -> the labels taxonomy.source_label() uses on cards, so
# the sources panel and the filter chips name things the same way.
STATUS_LABELS = {
    "greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workday": "Workday",
    "smartrecruiters": "SmartRecruiters", "workable": "Workable",
    "linkedin": "LinkedIn", "indeed": "Indeed", "google_ats": "Google site: search",
}

# Boards named in the build spec that have no scraper yet. Listed on the
# dashboard so a missing source reads as a known gap, not a silent failure.
NOT_BUILT = ["ZipRecruiter", "Glassdoor", "Simplify", "Y Combinator", "Jobright",
             "Otta", "Welcome to the Jungle", "Built In", "USAJOBS", "WayUp"]

EXT = 'target="_blank" rel="noopener noreferrer"'


# ----------------------------------------------------------------- data

def _score_for_sort(job: dict):
    ai = (job.get("ai_score") or {}).get("fit_score")
    det = (job.get("deterministic_score") or {}).get("composite_score")
    if isinstance(ai, (int, float)):
        return ai
    if isinstance(det, (int, float)):
        return det
    return -1


def _bucket(posted_dt, now):
    # Some boards don't give a machine-readable date at all -- LinkedIn
    # shows relative time ("2 hours ago"), and page-scraped SmartRecruiters/
    # Workable postings have none. Those used to fall out of every bucket
    # and vanish from the dashboard entirely, which conflicts with the
    # standing rule that a job is never hidden. They get their own group
    # instead, ranked last since their freshness is unknown.
    if posted_dt is None:
        return UNDATED
    age = now - posted_dt
    if age <= datetime.timedelta(hours=1):
        return "Posted in the last hour"
    if age <= datetime.timedelta(hours=24):
        return "Posted in the last 24 hours"
    if age <= datetime.timedelta(days=7):
        return "This week"
    if age <= datetime.timedelta(days=MAX_AGE_DAYS):
        return "This month"
    return None


def build_view(jobs: dict, hidden_path: str) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    hidden_store = hidden_mod.load(hidden_path)

    buckets = {name: [] for name in BUCKET_ORDER}
    for job in jobs.values():
        if hidden_mod.is_hidden(hidden_store, job.get("company", ""), job.get("title", ""),
                                 job.get("posted_at")):
            continue
        bucket_name = _bucket(parse_posted_at(job.get("posted_at")), now)
        if bucket_name is None:
            continue
        buckets[bucket_name].append(job)

    for bucket_jobs in buckets.values():
        bucket_jobs.sort(key=_score_for_sort, reverse=True)
    return buckets


def _facets(bucket_jobs: list) -> dict:
    sources, industries = {}, {}
    for job in bucket_jobs:
        sources[taxonomy.source_label(job)] = sources.get(taxonomy.source_label(job), 0) + 1
        ind = taxonomy.industry_label(job)
        industries[ind] = industries.get(ind, 0) + 1
    return {
        "sources": sorted(sources.items(), key=lambda kv: (-kv[1], kv[0])),
        "industries": sorted(
            industries.items(),
            key=lambda kv: (taxonomy.INDUSTRY_ORDER.index(kv[0])
                             if kv[0] in taxonomy.INDUSTRY_ORDER else 99),
        ),
    }


def _apply_filters(bucket_jobs: list, source: str = "", industry: str = "") -> list:
    out = bucket_jobs
    if source:
        out = [j for j in out if taxonomy.source_label(j) == source]
    if industry:
        out = [j for j in out if taxonomy.industry_label(j) == industry]
    return out


def build_daily_brief(jobs: dict, hidden_path: str, tracker_path: str, status: dict) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    today = now.date()

    discovered_today = great = strong = decent = unrated = 0
    posted_1h = posted_24h = 0
    per_source = {}

    for job in jobs.values():
        discovered_dt = parse_posted_at(job.get("discovered_at"))
        if discovered_dt and discovered_dt.date() == today:
            discovered_today += 1

        label = fit_label(job)
        if label == "Great Fit":
            great += 1
        elif label == "Strong Fit":
            strong += 1
        elif label == "Decent Fit":
            decent += 1
        elif label == "Not rated yet":
            unrated += 1

        src = taxonomy.source_label(job)
        per_source[src] = per_source.get(src, 0) + 1

        posted_dt = parse_posted_at(job.get("posted_at"))
        if posted_dt:
            age = now - posted_dt
            if age <= datetime.timedelta(hours=1):
                posted_1h += 1
            if age <= datetime.timedelta(hours=24):
                posted_24h += 1

    rows = tracker_mod.read_all(tracker_path)
    week_ago = today - datetime.timedelta(days=7)
    applied_this_week = sum(
        1 for r in rows
        if r.get("status") == "applied" and r.get("last_updated")
        and datetime.date.fromisoformat(r["last_updated"]) >= week_ago
    )
    awaiting_response = sum(1 for r in rows if r.get("status") in ("applied", "screening"))

    # One row per source: jobs it has contributed, plus what its last run
    # actually did (from data/source_status.json) -- so "LinkedIn is
    # missing" can be told apart from "LinkedIn ran and got blocked".
    sources = []
    seen = set()
    for key, label in STATUS_LABELS.items():
        st = status.get(key)
        if st is None and label not in per_source:
            continue
        seen.add(label)
        sources.append({
            "label": label,
            "jobs": per_source.get(label, 0),
            "state": (st or {}).get("state", "no run logged"),
            "detail": (st or {}).get("detail", ""),
            "last_run": (st or {}).get("last_run", ""),
        })
    for label, n in per_source.items():
        if label not in seen:
            sources.append({"label": label, "jobs": n, "state": "ok", "detail": "", "last_run": ""})
    sources.sort(key=lambda s: -s["jobs"])

    return {
        "date_label": now.strftime("%a %b %d"),
        "discovered_today": discovered_today,
        "great": great,
        "strong": strong,
        "decent": decent,
        "unrated": unrated,
        "posted_1h": posted_1h,
        "posted_24h": posted_24h,
        "applied_this_week": applied_this_week,
        "awaiting_response": awaiting_response,
        "sources": sources,
    }


# ------------------------------------------------------------- rendering

def _esc(v) -> str:
    return htmlmod.escape(str(v if v is not None else ""))


def _job_card_html(job: dict) -> str:
    ai = job.get("ai_score") or {}
    det = job.get("deterministic_score") or {}
    ai_score = ai.get("fit_score")
    det_score = det.get("composite_score")

    label = fit_label(job)
    band_cls = BAND_KEYS.get(label, "unrated")

    # The label leads; the numbers sit one click away for anyone who wants
    # them, written out in words rather than "AI 28 · KW 23".
    detail_lines = []
    if isinstance(ai_score, (int, float)):
        detail_lines.append(f"<b>AI fit score {ai_score}/100</b> -- how well the role matches "
                            "your experience and level overall.")
    else:
        detail_lines.append("<b>Not rated by AI yet.</b> Run Research + Tailor, or "
                            "<code>python cli.py score --job-id ...</code>, to get a fit rating.")
    if isinstance(det_score, (int, float)):
        detail_lines.append(f"Keyword match {det_score}/100 -- share of your profile's keywords "
                            "that appear in the posting. Runs low by design, even for good matches.")
    hover = (f"AI fit {ai_score}/100" if isinstance(ai_score, (int, float)) else "Not AI-rated") + \
            (f" · keyword match {det_score}/100" if isinstance(det_score, (int, float)) else "")

    meta_bits = [b for b in [
        _esc(job.get("location", "")),
        _esc(taxonomy.source_label(job)),
        _esc(taxonomy.industry_label(job)),
    ] if b]
    dup = ""
    if job.get("duplicate") and job.get("also_found_on"):
        dup = f'<span class="tag">also on {_esc(" + ".join(job["also_found_on"]))}</span>'

    why = _esc(ai.get("why", ""))
    partial = _esc(ai.get("partial_match_rationale", "") or "")
    brief = _esc(job.get("company_brief", ""))
    job_id = _esc(job.get("job_id", ""))

    notes = ""
    if brief:
        notes += f'<p class="note">{brief}</p>'
    if why:
        notes += f'<p class="note">{why}</p>'
    if partial:
        notes += f'<p class="note note-partial">{partial}</p>'

    url = _esc(job.get("url", "#"))
    return f"""
    <article class="card band-{band_cls}" id="card-{job_id}">
      <header class="card-top">
        <div class="card-ident">
          <div class="company">{_esc(taxonomy.company_label(job.get("company", "")))}</div>
          <h3 class="role"><a href="{url}" {EXT}>{_esc(job.get("title", ""))}</a></h3>
        </div>
        <div class="card-score">
          <button class="fit fit-{band_cls}" title="{_esc(hover)}"
                  onclick="toggleScore('{job_id}')" aria-expanded="false">{_esc(label)}</button>
        </div>
      </header>
      <div class="score-detail" id="score-{job_id}">{"<br>".join(detail_lines)}</div>
      <div class="meta">{" · ".join(meta_bits)} {dup}</div>
      {notes}
      <div class="actions">
        <button class="btn btn-primary" onclick="researchAndTailor('{job_id}')">Research + Tailor</button>
        <button class="btn btn-applied" onclick="markApplied('{job_id}')">Mark Applied</button>
        <a class="btn btn-ghost" href="{url}" {EXT}>View posting</a>
      </div>
      <div class="result" id="result-{job_id}"></div>
    </article>
    """


def _chips_html(bucket_key: str, kind: str, items: list) -> str:
    """kind is 'source' or 'industry'. The 'All' chip clears that dimension."""
    chips = [
        f'<button class="chip is-active" data-kind="{kind}" data-value="" '
        f'onclick="setFilter(this, \'{bucket_key}\', \'{kind}\', \'\')">All</button>'
    ]
    for label, count in items:
        safe = _esc(label).replace("'", "&#39;")
        chips.append(
            f'<button class="chip" data-kind="{kind}" data-value="{safe}" '
            f'onclick="setFilter(this, \'{bucket_key}\', \'{kind}\', \'{safe}\')">'
            f'{_esc(label)}<span class="chip-n">{count}</span></button>'
        )
    return "".join(chips)


def _load_more_html(bucket_key: str, next_offset: int, remaining: int) -> str:
    if remaining <= 0:
        return ""
    return (
        f'<button class="btn btn-more" data-bucket="{bucket_key}" data-offset="{next_offset}" '
        f'onclick="loadMoreCards(this)">Load {min(remaining, PAGE_SIZE)} more '
        f'<span class="more-n">{remaining} left</span></button>'
    )


def _sources_html(sources: list) -> str:
    rows = ""
    for s in sources:
        state = s["state"]
        state_cls = "ok" if state == "ok" else ("warn" if state in ("blocked", "failed") else "idle")
        title = _esc(f'{s["detail"]} {("· last run " + s["last_run"]) if s["last_run"] else ""}'.strip())
        rows += (f'<div class="src" title="{title}"><span class="src-name">{_esc(s["label"])}</span>'
                 f'<span class="src-n">{s["jobs"]:,}</span>'
                 f'<span class="src-state src-{state_cls}">{_esc(state)}</span></div>')
    rows += "".join(
        f'<div class="src src-dim"><span class="src-name">{_esc(n)}</span>'
        f'<span class="src-n">&ndash;</span><span class="src-state src-idle">not built</span></div>'
        for n in NOT_BUILT
    )
    return f'<div class="sources"><div class="sources-head">Sources</div><div class="src-grid">{rows}</div></div>'


def render_feed_tab(jobs: dict, hidden_path: str, tracker_path: str, status: dict) -> str:
    buckets = build_view(jobs, hidden_path)
    brief = build_daily_brief(jobs, hidden_path, tracker_path, status)

    stats = [
        ("Discovered today", brief["discovered_today"], ""),
        ("Great fit", brief["great"], ""),
        ("Strong fit", brief["strong"], ""),
        ("Decent fit", brief["decent"], ""),
        ("Posted &lt; 1 hour", brief["posted_1h"], "is-urgent"),
        ("Posted &lt; 24 hours", brief["posted_24h"], ""),
        ("Applied this week", brief["applied_this_week"], ""),
        ("Awaiting response", brief["awaiting_response"], ""),
    ]
    stat_html = "".join(
        f'<div class="stat {cls}"><div class="stat-n">{v:,}</div>'
        f'<div class="stat-l">{label}</div></div>'
        for label, v, cls in stats
    )

    brief_html = f"""
    <section class="brief">
      <div class="brief-head">
        <span class="brief-title">Today</span>
        <span class="brief-date">{_esc(brief["date_label"])}</span>
        <span class="brief-sources">{brief["unrated"]:,} jobs not AI-rated yet</span>
      </div>
      <div class="stat-grid">{stat_html}</div>
      {_sources_html(brief["sources"])}
    </section>
    """

    sections = ""
    for name in BUCKET_ORDER:
        bucket_jobs = buckets.get(name, [])
        if not bucket_jobs:
            continue
        key = BUCKET_KEY_BY_NAME[name]
        facets = _facets(bucket_jobs)
        page = bucket_jobs[:PAGE_SIZE]
        cards = "\n".join(_job_card_html(j) for j in page)
        remaining = len(bucket_jobs) - len(page)
        urgent = " is-urgent" if key == "hour" else ""

        sections += f"""
        <section class="bucket" id="bucket-{key}" data-source="" data-industry="">
          <div class="bucket-head{urgent}">
            <h2>{_esc(name)}</h2>
            <span class="bucket-count" id="count-{key}">{len(bucket_jobs)}</span>
          </div>
          <div class="filters">
            <div class="filter-row">
              <span class="filter-label">Source</span>
              <div class="chips" data-kind="source">{_chips_html(key, "source", facets["sources"])}</div>
            </div>
            <div class="filter-row">
              <span class="filter-label">Industry</span>
              <div class="chips" data-kind="industry">{_chips_html(key, "industry", facets["industries"])}</div>
            </div>
          </div>
          <div class="cards" id="bucket-cards-{key}">{cards}</div>
          <div class="load-more" id="load-more-{key}">{_load_more_html(key, PAGE_SIZE, remaining)}</div>
        </section>
        """

    if not sections:
        sections = ('<p class="empty">No jobs to show. Run <code>python cli.py scrape</code> '
                    'then <code>python cli.py score</code>.</p>')

    return brief_html + sections


def render_more_cards(jobs: dict, hidden_path: str, bucket_key: str, offset: int,
                       source: str = "", industry: str = "") -> dict:
    """Backs /api/feed/more -- used both for pagination and for filtering
    (a filter change re-requests offset 0 and replaces the list). The
    bucketed, score-sorted view is deterministic for a given jobs dict, so
    slicing lines up with what was already rendered."""
    bucket_name = BUCKET_NAME_BY_KEY.get(bucket_key)
    if not bucket_name:
        return {"html": "", "has_more": False, "next_offset": offset, "total": 0, "remaining": 0}

    bucket_jobs = _apply_filters(build_view(jobs, hidden_path).get(bucket_name, []), source, industry)
    page = bucket_jobs[offset:offset + PAGE_SIZE]
    next_offset = offset + len(page)
    remaining = max(len(bucket_jobs) - next_offset, 0)
    return {
        "html": "\n".join(_job_card_html(j) for j in page),
        "has_more": remaining > 0,
        "next_offset": next_offset,
        "total": len(bucket_jobs),
        "remaining": remaining,
        "load_more_html": _load_more_html(bucket_key, next_offset, remaining),
    }


def render_applied_tab(tracker_path: str) -> str:
    rows = tracker_mod.read_all(tracker_path)
    rows.sort(key=lambda r: r.get("last_updated", ""), reverse=True)
    if not rows:
        return '<p class="empty">Nothing tracked yet. Mark a job applied from the Jobs Feed.</p>'

    statuses = ["applied", "screening", "interview", "rejected", "offer"]
    body = ""
    for r in rows:
        jid = _esc(r["job_id"])
        options = "".join(
            f'<option value="{s}"{" selected" if r.get("status") == s else ""}>{s}</option>'
            for s in statuses
        )
        body += f"""
        <tr data-status="{_esc(r.get('status',''))}">
          <td class="t-company">{_esc(taxonomy.company_label(r.get('company','')))}</td>
          <td>{_esc(r.get('title',''))}</td>
          <td class="t-muted">{_esc(r.get('last_updated',''))}</td>
          <td><select class="input" onchange="updateApplied('{jid}', 'status', this.value); this.closest('tr').dataset.status=this.value;">{options}</select></td>
          <td><input class="input" type="text" placeholder="Notes" value="{_esc(r.get('notes',''))}"
                     onchange="updateApplied('{jid}', 'notes', this.value)"></td>
          <td><a class="btn btn-ghost btn-sm" href="{_esc(r.get('url','#'))}" {EXT}>Open posting</a></td>
        </tr>"""

    filter_opts = "".join(f'<option value="{s}">{s}</option>' for s in statuses)
    return f"""
    <div class="panel">
      <div class="panel-head">
        <h2>Applications</h2>
        <select class="input" id="applied-filter" onchange="filterApplied()">
          <option value="">All statuses</option>{filter_opts}
        </select>
      </div>
      <table class="table" id="applied-table">
        <thead><tr><th>Company</th><th>Role</th><th>Updated</th><th>Status</th><th>Notes</th><th></th></tr></thead>
        <tbody>{body}</tbody>
      </table>
    </div>
    """


def render_skills_gap_tab(tailored_dir: str) -> str:
    data = skillsgap.aggregate(tailored_dir)
    if data["total_resumes_analyzed"] == 0:
        return ('<p class="empty">No tailored resumes yet. Run Research + Tailor on a job, '
                'or <code>python cli.py tailor --job-id X</code>.</p>')

    rows = "".join(
        f'<tr><td class="t-company">{_esc(s["label"])}</td>'
        f'<td class="t-num">{s["count"]}</td>'
        f'<td><span class="effort effort-{_esc(s["effort"])}">{_esc(s["effort"])}</span></td></tr>'
        for s in data["top_skills_to_learn"]
    )
    certs = "".join(
        f'<li>{_esc(c["label"])} <span class="t-muted">({c["count"]}x)</span></li>'
        for c in data["certifications_missing"]
    ) or '<li class="t-muted">None flagged</li>'

    return f"""
    <div class="panel">
      <div class="panel-head">
        <h2>Skills to learn</h2>
        <span class="t-muted">from {data['total_resumes_analyzed']} tailored resume(s)</span>
      </div>
      <table class="table">
        <thead><tr><th>Skill / gap</th><th class="t-num">Jobs</th><th>Effort</th></tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div class="panel">
      <div class="panel-head"><h2>Certifications missing</h2></div>
      <ul class="list">{certs}</ul>
    </div>
    """


def render_profile_tab(profile: dict) -> str:
    groups = "".join(f'<option value="{_esc(g)}">{_esc(g)}</option>'
                      for g in profile.get("skills", {}).keys())
    certs = "".join(f'<li>{_esc(c)}</li>' for c in profile.get("certifications_earned", []))
    projects = "".join(f'<li>{_esc(p.get("name",""))}</li>' for p in profile.get("projects", []))

    return f"""
    <div class="panel">
      <div class="panel-head"><h2>Add a skill</h2></div>
      <form class="form-row" onsubmit="return addSkill(event)">
        <select class="input" id="skill-group">{groups}</select>
        <input class="input" type="text" id="skill-name" placeholder="e.g. Kubernetes" required>
        <button class="btn btn-primary" type="submit">Add skill</button>
      </form>
    </div>

    <div class="panel">
      <div class="panel-head"><h2>Add a certification</h2></div>
      <form class="form-row" onsubmit="return addCert(event)">
        <input class="input" type="text" id="cert-name" placeholder="Certification name" required>
        <button class="btn btn-primary" type="submit">Add certification</button>
      </form>
      <ul class="list list-compact">{certs}</ul>
    </div>

    <div class="panel">
      <div class="panel-head"><h2>Add a project</h2></div>
      <form class="form-col" onsubmit="return addProject(event)">
        <input class="input" type="text" id="project-name" placeholder="Project name" required>
        <input class="input" type="text" id="project-desc" placeholder="One-line description" required>
        <input class="input" type="text" id="project-link" placeholder="Link (optional)">
        <button class="btn btn-primary" type="submit">Add project</button>
      </form>
      <ul class="list list-compact">{projects}</ul>
    </div>

    <p class="t-muted footnote">Changes write straight to profile.json. The next
    Research + Tailor run picks them up immediately, no restart.</p>
    """


# ------------------------------------------------------------ page shell

# Plain strings, not f-strings, so CSS/JS braces don't need doubling.
_CSS = """
  :root {
    --bg: #F7F6F3; --surface: #FFFFFF; --border: #E4E1DB; --border-strong: #D5D1C8;
    --ink: #17171A; --ink-2: #45454C; --muted: #8A867D;
    --accent: #1B3A4B; --accent-hover: #142C39; --accent-weak: #ECF1F4;
    --green: #2E6B4F; --green-weak: #EBF2ED; --warn: #7A5A26;
    --radius: 3px;
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, system-ui, sans-serif;
         font-size: 14px; line-height: 1.5; -webkit-font-smoothing: antialiased; }
  a { color: inherit; }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 22px 28px 80px; }
  .t-muted { color: var(--muted); }

  /* sticky top bar: always one click back to the feed, and Quick Apply */
  .topbar { position: sticky; top: 0; z-index: 20; background: rgba(247,246,243,0.96);
            border-bottom: 1px solid var(--border); backdrop-filter: saturate(1.2); }
  .topbar-in { max-width: 1080px; margin: 0 auto; padding: 10px 28px;
               display: flex; align-items: center; gap: 14px; }
  .home { font-family: inherit; font-size: 13px; font-weight: 600; color: var(--ink);
          background: var(--surface); border: 1px solid var(--border-strong);
          border-radius: var(--radius); padding: 6px 12px; cursor: pointer; text-decoration: none; }
  .home:hover { border-color: var(--accent); color: var(--accent); }
  .topbar .brand { font-size: 13px; color: var(--muted); }
  .topbar .spacer { flex: 1; }

  .masthead { display: flex; align-items: baseline; justify-content: space-between;
              padding: 10px 0 16px; }
  .masthead h1 { margin: 0; font-size: 19px; font-weight: 600; letter-spacing: -0.01em; }
  .masthead .t-muted { font-size: 12px; }

  .tabs { display: flex; gap: 26px; border-bottom: 1px solid var(--border); margin-bottom: 26px; }
  .tab-btn { background: none; border: 0; padding: 0 0 12px; cursor: pointer;
             font-size: 13.5px; color: var(--muted); font-family: inherit;
             border-bottom: 2px solid transparent; margin-bottom: -1px; }
  .tab-btn:hover { color: var(--ink-2); }
  .tab-btn.active { color: var(--ink); font-weight: 600; border-bottom-color: var(--accent); }
  .tab-content { display: none; }
  .tab-content.active { display: block; }

  /* confirmation banner after Mark Applied */
  .banner { display: flex; align-items: center; gap: 12px; background: var(--green-weak);
            border: 1px solid #C9DCCF; border-radius: var(--radius); padding: 11px 14px;
            margin-bottom: 18px; font-size: 13px; color: #24533D; }
  .banner .spacer { flex: 1; }
  .toast { position: fixed; left: 50%; bottom: 24px; transform: translateX(-50%);
           background: var(--ink); color: #fff; border-radius: var(--radius);
           padding: 10px 14px; font-size: 13px; display: none; gap: 12px; align-items: center;
           z-index: 40; box-shadow: 0 6px 24px rgba(0,0,0,0.12); }
  .toast.show { display: flex; }
  .toast a, .toast button { color: #fff; font: inherit; background: none; border: 0;
                            text-decoration: underline; cursor: pointer; padding: 0; }

  /* daily brief */
  .brief { background: var(--surface); border: 1px solid var(--border);
           border-radius: var(--radius); padding: 20px 22px; margin-bottom: 30px; }
  .brief-head { display: flex; align-items: baseline; gap: 10px; margin-bottom: 18px; }
  .brief-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.10em;
                 color: var(--muted); font-weight: 600; }
  .brief-date { font-size: 12px; color: var(--ink-2); }
  .brief-sources { margin-left: auto; font-size: 11.5px; color: var(--muted); }
  .stat-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px 18px; }
  .stat-n { font-size: 25px; font-weight: 600; letter-spacing: -0.02em;
            font-variant-numeric: tabular-nums; line-height: 1.15; }
  .stat-l { font-size: 11.5px; color: var(--muted); margin-top: 2px; }
  .stat.is-urgent .stat-n, .stat.is-urgent .stat-l { color: var(--accent); }
  .sources { margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--border); }
  .sources-head { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em;
                  color: var(--muted); margin-bottom: 10px; font-weight: 600; }
  .src-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px 22px; }
  .src { display: flex; align-items: baseline; gap: 8px; font-size: 12px;
         padding: 3px 0; border-bottom: 1px dotted var(--border); }
  .src-name { color: var(--ink-2); flex: 1; }
  .src-n { font-variant-numeric: tabular-nums; color: var(--ink); font-weight: 600; }
  .src-state { font-size: 10.5px; min-width: 54px; text-align: right; }
  .src-ok { color: var(--green); }
  .src-warn { color: var(--warn); font-weight: 600; }
  .src-idle { color: var(--muted); }
  .src-dim .src-name { color: var(--muted); }

  /* buckets + filters */
  .bucket { margin-bottom: 40px; }
  .bucket-head { display: flex; align-items: center; gap: 10px;
                 border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 14px; }
  .bucket-head h2 { margin: 0; font-size: 11px; text-transform: uppercase;
                    letter-spacing: 0.10em; color: var(--ink-2); font-weight: 600; }
  .bucket-head.is-urgent h2 { color: var(--accent); }
  .bucket-count { font-size: 11.5px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .filters { margin-bottom: 16px; }
  .filter-row { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 7px; }
  .filter-label { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em;
                  color: var(--muted); padding-top: 5px; min-width: 58px; }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .chip { font-family: inherit; font-size: 12px; color: var(--ink-2); background: var(--surface);
          border: 1px solid var(--border); border-radius: var(--radius); padding: 4px 9px; cursor: pointer; }
  .chip:hover { border-color: var(--border-strong); }
  .chip.is-active { background: var(--accent); border-color: var(--accent); color: #fff; }
  .chip-n { margin-left: 6px; color: var(--muted); font-variant-numeric: tabular-nums; }
  .chip.is-active .chip-n { color: rgba(255,255,255,0.7); }

  /* cards */
  .card { background: var(--surface); border: 1px solid var(--border);
          border-left: 2px solid var(--border-strong);
          border-radius: var(--radius); padding: 16px 18px; margin-bottom: 10px;
          transition: opacity .25s; }
  .card.band-great { border-left-color: #2A5E43; }
  .card.band-strong { border-left-color: #1B3A4B; }
  .card.band-decent { border-left-color: #5F7F8F; }
  .card.band-shot { border-left-color: #A8A49B; }
  .card.band-long, .card.band-unrated { border-left-color: #DDDAD3; }
  .card-top { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; }
  .company { font-size: 16px; font-weight: 600; letter-spacing: -0.01em; color: var(--ink); }
  .role { margin: 1px 0 0; font-size: 13.5px; font-weight: 400; color: var(--ink-2); }
  .role a { text-decoration: none; }
  .role a:hover { text-decoration: underline; color: var(--accent); }
  .card-score { text-align: right; white-space: nowrap; }

  /* fit label: plain words, numbers one click away */
  .fit { font-family: inherit; font-size: 12px; font-weight: 600; cursor: pointer;
         padding: 3px 9px; border-radius: var(--radius); border: 1px solid transparent; }
  .fit-great { background: #E7EFE9; color: #2A5E43; border-color: #CFE0D6; }
  .fit-strong { background: var(--accent-weak); color: var(--accent); border-color: #D3E0E7; }
  .fit-decent { background: #EEF2F4; color: #3E5F6F; border-color: #DCE4E8; }
  .fit-shot { background: #F2F1EE; color: #55534E; border-color: #E2E0DA; }
  .fit-long { background: #F5F4F2; color: var(--muted); border-color: #E8E6E1; }
  .fit-unrated { background: transparent; color: var(--muted); border-color: var(--border);
                 font-weight: 500; }
  .score-detail { display: none; margin-top: 10px; font-size: 12px; color: var(--ink-2);
                  background: #FAF9F7; border: 1px solid var(--border); border-radius: var(--radius);
                  padding: 9px 11px; line-height: 1.6; }
  .score-detail.show { display: block; }

  .meta { margin-top: 8px; font-size: 11.5px; color: var(--muted); }
  .tag { display: inline-block; font-size: 10.5px; color: var(--ink-2); background: #F3F2EF;
         border: 1px solid var(--border); border-radius: var(--radius); padding: 1px 6px; margin-left: 4px; }
  /* Rationale text can run long; clamp so cards keep an even rhythm. */
  .note { margin: 8px 0 0; font-size: 12.5px; color: var(--ink-2);
          display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .note-partial { color: var(--accent); }
  .actions { display: flex; gap: 7px; margin-top: 13px; flex-wrap: wrap; }
  .result { margin-top: 11px; font-size: 12.5px; color: var(--ink-2); white-space: pre-wrap;
            border-top: 1px solid var(--border); padding-top: 10px; display: none; }
  .result.show { display: block; }

  /* buttons */
  .btn { font-family: inherit; font-size: 12.5px; padding: 6px 12px; border-radius: var(--radius);
         cursor: pointer; border: 1px solid transparent; text-decoration: none;
         display: inline-block; line-height: 1.4; }
  .btn-primary { background: var(--accent); color: #fff; border-color: var(--accent); }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-applied { background: var(--surface); color: var(--green); border-color: #BFD4C6; }
  .btn-applied:hover { background: var(--green-weak); }
  .btn-ghost { background: var(--surface); color: var(--ink-2); border-color: var(--border); }
  .btn-ghost:hover { border-color: var(--border-strong); }
  .btn-sm { font-size: 11.5px; padding: 3px 9px; }
  .btn:disabled { opacity: 0.55; cursor: default; }
  .btn-more { background: var(--surface); color: var(--ink-2); border-color: var(--border); width: 100%; }
  .btn-more:hover { border-color: var(--border-strong); }
  .more-n { color: var(--muted); margin-left: 6px; font-variant-numeric: tabular-nums; }
  .load-more { margin-top: 12px; }

  /* panels + tables */
  .panel { background: var(--surface); border: 1px solid var(--border);
           border-radius: var(--radius); padding: 18px 20px; margin-bottom: 18px; }
  .panel-head { display: flex; align-items: baseline; gap: 12px; margin-bottom: 14px; }
  .panel-head h2 { margin: 0; font-size: 13px; font-weight: 600; letter-spacing: -0.005em; }
  .panel-head .input { margin-left: auto; }
  .table { width: 100%; border-collapse: collapse; }
  .table th { text-align: left; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em;
              color: var(--muted); font-weight: 600; padding: 0 10px 8px 0; border-bottom: 1px solid var(--border); }
  .table td { padding: 9px 10px 9px 0; border-bottom: 1px solid var(--border); font-size: 13px; vertical-align: middle; }
  .table tr:last-child td { border-bottom: 0; }
  .t-company { font-weight: 600; }
  .t-num { font-variant-numeric: tabular-nums; }
  .effort { font-size: 11px; padding: 2px 7px; border-radius: var(--radius);
            border: 1px solid var(--border); background: #F5F4F2; color: var(--ink-2); }
  .effort-easy { background: #E7EFE9; color: #2A5E43; border-color: #CFE0D6; }
  .effort-hard { background: #F4EFE2; color: #6E5A2E; border-color: #E6DCC6; }
  .list { margin: 0; padding-left: 18px; font-size: 13px; color: var(--ink-2); }
  .list-compact li { margin: 3px 0; }
  .footnote { font-size: 12px; }

  /* forms */
  .input { font-family: inherit; font-size: 13px; padding: 6px 9px; color: var(--ink);
           background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); }
  .input:focus { outline: none; border-color: var(--accent); }
  .form-row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .form-col { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; max-width: 420px; }
  .form-col .input { width: 100%; }
  .empty { color: var(--muted); padding: 30px 0; }
  code { font-size: 12px; background: #F1F0ED; padding: 1px 5px; border-radius: var(--radius); }

  /* quick apply side panel */
  .qa-panel { position: fixed; top: 0; right: 0; bottom: 0; width: 380px; max-width: 92vw;
              background: var(--surface); border-left: 1px solid var(--border);
              box-shadow: -8px 0 30px rgba(0,0,0,0.06); z-index: 30;
              transform: translateX(100%); transition: transform .2s ease;
              display: flex; flex-direction: column; }
  .qa-panel.open { transform: translateX(0); }
  .qa-head { padding: 18px 20px 12px; border-bottom: 1px solid var(--border); }
  .qa-head h2 { margin: 0; font-size: 14px; font-weight: 600; }
  .qa-head p { margin: 6px 0 0; font-size: 11.5px; color: var(--muted); line-height: 1.5; }
  .qa-close { float: right; background: none; border: 0; font-size: 12px; color: var(--muted);
              cursor: pointer; font-family: inherit; }
  .qa-body { overflow-y: auto; padding: 8px 20px 20px; }
  .qa-row { display: flex; align-items: center; gap: 10px; padding: 9px 0;
            border-bottom: 1px solid var(--border); }
  .qa-k { font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.06em;
          color: var(--muted); width: 88px; flex-shrink: 0; }
  .qa-v { font-size: 12.5px; color: var(--ink); flex: 1; word-break: break-all; }
  .qa-copy { font-family: inherit; font-size: 11px; padding: 3px 9px; cursor: pointer;
             background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius);
             color: var(--ink-2); min-width: 58px; }
  .qa-copy:hover { border-color: var(--accent); color: var(--accent); }
  .qa-copy.done { background: var(--green-weak); border-color: #BFD4C6; color: var(--green); }

  /* job view page */
  .job-head { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; }
  .job-company { font-size: 24px; font-weight: 600; letter-spacing: -0.02em; }
  .job-title { font-size: 16px; color: var(--ink-2); margin-top: 2px; }
  .kv { display: grid; grid-template-columns: 150px 1fr; gap: 6px 14px; font-size: 13px; }
  .kv dt { color: var(--muted); }
  .kv dd { margin: 0; }
  .copybox { display: flex; gap: 10px; align-items: flex-start; background: #FAF9F7;
             border: 1px solid var(--border); border-radius: var(--radius); padding: 10px 12px;
             font-size: 13px; margin-bottom: 8px; }
  .copybox div { flex: 1; white-space: pre-wrap; }
  .resume-frame { width: 100%; height: 1000px; border: 1px solid var(--border);
                  border-radius: var(--radius); background: #fff; }
"""

# Shared by the dashboard and the job view page.
_SHARED_JS = """
function copyText(btn, text) {
  const done = () => {
    btn.textContent = 'Copied'; btn.classList.add('done');
    setTimeout(() => { btn.textContent = 'Copy'; btn.classList.remove('done'); }, 1400);
  };
  // localhost is a secure context, so the async clipboard API is available;
  // the textarea fallback covers anything that still refuses it.
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done, () => legacyCopy(text, done));
  } else {
    legacyCopy(text, done);
  }
}
function legacyCopy(text, done) {
  const ta = document.createElement('textarea');
  ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
  document.body.appendChild(ta); ta.select();
  try { document.execCommand('copy'); done(); } catch (e) {}
  document.body.removeChild(ta);
}
function toggleQuickApply(open) {
  const p = document.getElementById('qa-panel');
  p.classList.toggle('open', open === undefined ? !p.classList.contains('open') : open);
}
document.addEventListener('keydown', e => { if (e.key === 'Escape') toggleQuickApply(false); });
"""


def render_quick_apply(profile: dict) -> str:
    """Copy helper for application forms. Deliberately not autofill: a
    local dashboard can't type into another site's form (different origin,
    browser security model) -- that would take a separate browser
    extension. The panel says so, so nobody expects otherwise."""
    links = profile.get("links", {})
    edu = profile.get("education", {})
    exp = (profile.get("experience") or [{}])[0]
    name = profile.get("name", "")
    first, _, last = name.partition(" ")
    fields = [
        ("Full name", name), ("First name", first), ("Last name", last),
        ("Email", profile.get("email", "")), ("Phone", profile.get("phone", "")),
        ("Location", profile.get("location", "")),
        ("LinkedIn", links.get("linkedin", "")), ("GitHub", links.get("github", "")),
        ("Website", links.get("portfolio", "")), ("Hugging Face", links.get("huggingface", "")),
        ("School", edu.get("school", "")), ("Degree", edu.get("degree", "")),
        ("Graduated", edu.get("graduated", "")),
        ("GPA", str(edu["gpa"]) if edu.get("gpa") else ""),
        ("Current role", f'{exp.get("title", "")}, {exp.get("org", "")}' if exp.get("org") else ""),
    ]
    rows = ""
    for label, value in fields:
        if not value:
            continue
        js_value = _esc(value).replace("\\", "\\\\").replace("'", "\\'")
        rows += (f'<div class="qa-row"><span class="qa-k">{_esc(label)}</span>'
                 f'<span class="qa-v">{_esc(value)}</span>'
                 f'<button class="qa-copy" onclick="copyText(this, \'{js_value}\')">Copy</button></div>')
    return f"""
    <aside class="qa-panel" id="qa-panel" aria-label="Quick Apply Info">
      <div class="qa-head">
        <button class="qa-close" onclick="toggleQuickApply(false)">Close</button>
        <h2>Quick Apply Info &mdash; copy &amp; paste</h2>
        <p>A copy helper, not autofill. This dashboard runs locally and can't fill in
        forms on other websites &mdash; browsers block that between sites; it would need a
        separate browser extension. Click Copy, then paste into the application form.</p>
      </div>
      <div class="qa-body">{rows}</div>
    </aside>
    """


def _topbar(right_label: str = "") -> str:
    return f"""
    <div class="topbar"><div class="topbar-in">
      <a class="home" href="/">&larr; Jobs Feed</a>
      <span class="brand">{_esc(right_label)}</span>
      <span class="spacer"></span>
      <button class="btn btn-ghost" onclick="toggleQuickApply()">Quick Apply Info</button>
    </div></div>
    """


def applied_banner(job: dict | None) -> str:
    if not job:
        return ""
    who = f'{_esc(taxonomy.company_label(job.get("company", "")))} &mdash; {_esc(job.get("title", ""))}'
    return f"""
    <div class="banner" id="applied-banner">
      <span>Marked as applied: <b>{who}</b>. It's now in the Applied tab.</span>
      <span class="spacer"></span>
      <button class="btn btn-ghost btn-sm" onclick="openTab('applied')">View in Applied</button>
      <a class="btn btn-primary btn-sm" href="/">Back to Jobs Feed</a>
    </div>
    """


def render_app_html(feed_html: str, applied_html: str, skills_gap_html: str, profile_html: str,
                    quick_apply_html: str = "", banner_html: str = "", initial_tab: str = "feed") -> str:
    generated = datetime.datetime.now().strftime("%a %b %d, %-I:%M %p")
    if initial_tab not in ("feed", "applied", "skills-gap", "profile"):
        initial_tab = "feed"
    act = lambda t: " active" if t == initial_tab else ""  # noqa: E731
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Dashboard</title>
<style>{_CSS}</style>
</head>
<body>
{_topbar()}
<div class="wrap">
  <div class="masthead">
    <h1>Job Dashboard</h1>
    <span class="t-muted">{generated}</span>
  </div>
  {banner_html}
  <nav class="tabs">
    <button class="tab-btn{act('feed')}" data-tab="feed" onclick="openTab('feed')">Jobs Feed</button>
    <button class="tab-btn{act('applied')}" data-tab="applied" onclick="openTab('applied')">Applied</button>
    <button class="tab-btn{act('skills-gap')}" data-tab="skills-gap" onclick="openTab('skills-gap')">Skills Gap</button>
    <button class="tab-btn{act('profile')}" data-tab="profile" onclick="openTab('profile')">Profile</button>
  </nav>

  <div id="tab-feed" class="tab-content{act('feed')}">{feed_html}</div>
  <div id="tab-applied" class="tab-content{act('applied')}">{applied_html}</div>
  <div id="tab-skills-gap" class="tab-content{act('skills-gap')}">{skills_gap_html}</div>
  <div id="tab-profile" class="tab-content{act('profile')}">{profile_html}</div>
</div>
{quick_apply_html}
<div class="toast" id="toast"><span id="toast-msg"></span>
  <button onclick="openTab('applied')">View in Applied</button></div>

<script>
{_SHARED_JS}
{_DASHBOARD_JS}
</script>
</body>
</html>"""


_DASHBOARD_JS = """
let appliedStale = false;

function openTab(name) {
  // The Applied tab is rendered server-side; after marking something
  // applied in place, fetch a fresh page for it rather than show stale rows.
  if (name === 'applied' && appliedStale) { location.href = '/?tab=applied'; return; }
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el =>
    el.classList.toggle('active', el.dataset.tab === name));
  document.getElementById('tab-' + name).classList.add('active');
  window.scrollTo({top: 0});
}

function toggleScore(jobId) {
  document.getElementById('score-' + jobId).classList.toggle('show');
}

function feedQuery(bucket, offset) {
  const sec = document.getElementById('bucket-' + bucket);
  const p = new URLSearchParams({bucket: bucket, offset: offset});
  if (sec.dataset.source) p.set('source', sec.dataset.source);
  if (sec.dataset.industry) p.set('industry', sec.dataset.industry);
  return '/api/feed/more?' + p.toString();
}

function setFilter(btn, bucket, kind, value) {
  const sec = document.getElementById('bucket-' + bucket);
  sec.dataset[kind] = value;
  sec.querySelectorAll('.chips[data-kind="' + kind + '"] .chip')
     .forEach(c => c.classList.toggle('is-active', c.dataset.value === value));
  const cards = document.getElementById('bucket-cards-' + bucket);
  cards.style.opacity = '0.45';
  fetch(feedQuery(bucket, 0))
    .then(r => r.json())
    .then(data => {
      cards.innerHTML = data.html || '<p class="empty">No jobs match these filters.</p>';
      cards.style.opacity = '1';
      document.getElementById('count-' + bucket).textContent = data.total;
      document.getElementById('load-more-' + bucket).innerHTML = data.load_more_html || '';
    })
    .catch(() => { cards.style.opacity = '1'; });
}

function loadMoreCards(btn) {
  const bucket = btn.dataset.bucket;
  btn.disabled = true; btn.textContent = 'Loading...';
  fetch(feedQuery(bucket, btn.dataset.offset))
    .then(r => r.json())
    .then(data => {
      document.getElementById('bucket-cards-' + bucket).insertAdjacentHTML('beforeend', data.html);
      document.getElementById('load-more-' + bucket).innerHTML = data.load_more_html || '';
    })
    .catch(() => { btn.disabled = false; btn.textContent = 'Retry'; });
}

function markApplied(jobId) {
  // Stays on the feed at the same scroll position: the card fades out and a
  // toast confirms, instead of a full reload that throws away your place.
  fetch('/api/apply/' + jobId, { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (!data.ok) { alert('Failed: ' + (data.error || 'unknown error')); return; }
      appliedStale = true;
      const card = document.getElementById('card-' + jobId);
      const who = card ? card.querySelector('.company').textContent : 'Job';
      if (card) { card.style.opacity = '0'; setTimeout(() => card.remove(), 260); }
      document.getElementById('toast-msg').textContent = 'Marked applied: ' + who;
      const t = document.getElementById('toast');
      t.classList.add('show');
      clearTimeout(window._toastTimer);
      window._toastTimer = setTimeout(() => t.classList.remove('show'), 6000);
    })
    .catch(() => alert('Could not reach the local server.'));
}

function researchAndTailor(jobId) {
  const el = document.getElementById('result-' + jobId);
  el.classList.add('show');
  el.textContent = 'Researching and tailoring... up to a minute.';
  fetch('/api/research-tailor/' + jobId, { method: 'POST' })
    .then(r => r.json())
    .then(data => {
      if (!data.ok) { el.textContent = 'Failed: ' + (data.error || 'unknown error'); return; }
      const t = data.tailor || {}, r2 = data.research || {};
      let out = '';
      if (t.baseline_coverage_pct !== undefined)
        out += 'Keyword coverage ' + t.baseline_coverage_pct + '% -> ' + (t.tailored_coverage_pct ?? '?') + '%\\n';
      if (t.honest_gaps && t.honest_gaps.length)
        out += 'Gaps: ' + t.honest_gaps.slice(0, 3).join('; ') + '\\n';
      if (r2.company_brief) out += r2.company_brief + '\\n';
      el.textContent = out || 'Done.';
      const a = document.createElement('a');
      a.href = '/job/' + encodeURIComponent(jobId);
      a.className = 'btn btn-primary btn-sm';
      a.textContent = 'Open full research + resume';
      el.appendChild(document.createElement('br'));
      el.appendChild(a);
    })
    .catch(() => { el.textContent = 'Could not reach the local server.'; });
}

function updateApplied(jobId, field, value) {
  const body = {}; body[field] = value;
  fetch('/api/applied/' + jobId, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
}

function filterApplied() {
  const val = document.getElementById('applied-filter').value;
  document.querySelectorAll('#applied-table tbody tr').forEach(row => {
    row.style.display = (!val || row.dataset.status === val) ? '' : 'none';
  });
}

function postProfile(url, payload) {
  return fetch(url, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
  }).then(() => { location.href = '/?tab=profile'; });
}
function addSkill(ev) {
  ev.preventDefault();
  postProfile('/api/profile/skill', { group: document.getElementById('skill-group').value,
                                       skill: document.getElementById('skill-name').value });
  return false;
}
function addCert(ev) {
  ev.preventDefault();
  postProfile('/api/profile/cert', { name: document.getElementById('cert-name').value });
  return false;
}
function addProject(ev) {
  ev.preventDefault();
  postProfile('/api/profile/project', { name: document.getElementById('project-name').value,
    description: document.getElementById('project-desc').value,
    link: document.getElementById('project-link').value });
  return false;
}
"""


def render_job_page(job: dict, report: dict | None, research: dict | None,
                    quick_apply_html: str) -> str:
    """Full view of one job's research + tailored resume, with a persistent
    way back to the feed -- the output used to exist only as a few lines of
    text inside the card."""
    job_id = _esc(job.get("job_id", ""))
    url = _esc(job.get("url", "#"))
    label = fit_label(job)
    ai = job.get("ai_score") or {}

    def copybox(text):
        if not text:
            return ""
        js = _esc(text).replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        return (f'<div class="copybox"><div>{_esc(text)}</div>'
                f'<button class="qa-copy" onclick="copyText(this, \'{js}\')">Copy</button></div>')

    if research and not research.get("error"):
        contacts = "".join(
            f'<li><b>{_esc(c.get("name",""))}</b>, {_esc(c.get("title",""))} '
            f'<span class="t-muted">({_esc(c.get("confidence",""))} confidence, {_esc(c.get("source",""))})</span>'
            + (f' &middot; <a href="{_esc(c["linkedin_url"])}" {EXT}>LinkedIn</a>' if c.get("linkedin_url") else "")
            + "</li>"
            for c in research.get("contacts") or []
        ) or '<li class="t-muted">No contact found with solid public evidence.</li>'
        queries = "".join(copybox(q) for q in research.get("search_queries_for_shiva") or [])
        research_html = f"""
        <div class="panel">
          <div class="panel-head"><h2>Company</h2></div>
          <p>{_esc(research.get("company_brief", ""))}</p>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>People to contact</h2>
            <span class="t-muted">leads from public web search &mdash; verify on LinkedIn before reaching out</span></div>
          <ul class="list list-compact">{contacts}</ul>
          <p class="t-muted footnote" style="margin-top:14px">Searches to run yourself:</p>
          {queries}
        </div>
        <div class="panel">
          <div class="panel-head"><h2>Messages (drafts &mdash; you send these)</h2></div>
          <p class="t-muted footnote">Connection note</p>{copybox(research.get("connection_note", ""))}
          <p class="t-muted footnote">Follow-up, 3-4 days later</p>{copybox(research.get("followup_note", ""))}
        </div>"""
    else:
        research_html = ('<div class="panel"><p class="t-muted">No research yet for this job. '
                         'Run Research + Tailor below.</p></div>')

    if report and report.get("pdf_path"):
        gaps = "".join(f"<li>{_esc(g)}</li>" for g in report.get("honest_gaps") or []) \
            or '<li class="t-muted">None</li>'
        resume_html = f"""
        <div class="panel">
          <div class="panel-head"><h2>Tailored resume</h2>
            <span class="t-muted">keyword coverage {report.get("baseline_coverage_pct")}% &rarr;
            {report.get("tailored_coverage_pct")}%</span>
            <a class="btn btn-ghost btn-sm" style="margin-left:auto"
               href="/tailored/{job_id}/resume.pdf" {EXT}>Open PDF</a></div>
          <iframe class="resume-frame" src="/tailored/{job_id}/resume.pdf#view=FitH"></iframe>
        </div>
        <div class="panel">
          <div class="panel-head"><h2>Honest gaps</h2>
            <span class="t-muted">what the posting asks for that your profile doesn't show &mdash; not added to the resume</span></div>
          <ul class="list list-compact">{gaps}</ul>
        </div>"""
    else:
        resume_html = ""

    why = _esc(ai.get("why", ""))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(taxonomy.company_label(job.get("company","")))} &middot; {_esc(job.get("title",""))}</title>
<style>{_CSS}</style>
</head>
<body>
{_topbar("Job detail")}
<div class="wrap">
  <div class="panel">
    <div class="job-head">
      <div>
        <div class="job-company">{_esc(taxonomy.company_label(job.get("company","")))}</div>
        <div class="job-title">{_esc(job.get("title",""))}</div>
        <div class="meta">{_esc(job.get("location",""))} &middot; {_esc(taxonomy.source_label(job))}
          &middot; {_esc(taxonomy.industry_label(job))}</div>
      </div>
      <span class="fit fit-{BAND_KEYS.get(label, "unrated")}" style="cursor:default">{_esc(label)}</span>
    </div>
    {f'<p class="note" style="-webkit-line-clamp:unset">{why}</p>' if why else ""}
    <div class="actions">
      <a class="btn btn-primary" href="{url}" {EXT}>Open posting</a>
      <button class="btn btn-applied" onclick="markAppliedHere('{job_id}')">Mark Applied</button>
      <button class="btn btn-ghost" id="rt-btn" onclick="rerun('{job_id}')">
        {"Re-run" if report else "Run"} Research + Tailor</button>
      <a class="btn btn-ghost" href="/">Back to Jobs Feed</a>
    </div>
  </div>
  {research_html}
  {resume_html}
</div>
{quick_apply_html}
<script>
{_SHARED_JS}
function markAppliedHere(jobId) {{
  fetch('/api/apply/' + jobId, {{ method: 'POST' }})
    .then(r => r.json())
    .then(d => d.ok ? (location.href = '/?applied=' + encodeURIComponent(jobId))
                    : alert('Failed: ' + (d.error || 'unknown error')));
}}
function rerun(jobId) {{
  const b = document.getElementById('rt-btn');
  b.disabled = true; b.textContent = 'Working... up to a minute';
  fetch('/api/research-tailor/' + jobId, {{ method: 'POST' }})
    .then(() => location.reload())
    .catch(() => {{ b.disabled = false; b.textContent = 'Retry'; }});
}}
</script>
</body>
</html>"""
