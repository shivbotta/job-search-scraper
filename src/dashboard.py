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
from scoring.bands import score_band
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

BAND_CLASS = {
    "Excellent match": "excellent",
    "Strong match": "strong",
    "Worth applying": "worth",
    "Stretch": "stretch",
    "Long shot": "longshot",
    "Unscored": "unscored",
}


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


def build_daily_brief(jobs: dict, hidden_path: str, tracker_path: str, sources_status: dict) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    today = now.date()

    discovered_today = excellent = strong = worth_applying = 0
    posted_1h = posted_24h = 0

    for job in jobs.values():
        discovered_dt = parse_posted_at(job.get("discovered_at"))
        if discovered_dt and discovered_dt.date() == today:
            discovered_today += 1

        band = score_band(_score_for_sort(job) if _score_for_sort(job) >= 0 else None)
        if band == "Excellent match":
            excellent += 1
        elif band == "Strong match":
            strong += 1
        elif band == "Worth applying":
            worth_applying += 1

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

    return {
        "date_label": now.strftime("%a %b %d"),
        "discovered_today": discovered_today,
        "excellent": excellent,
        "strong": strong,
        "worth_applying": worth_applying,
        "posted_1h": posted_1h,
        "posted_24h": posted_24h,
        "applied_this_week": applied_this_week,
        "awaiting_response": awaiting_response,
        "sources_live": sum(1 for ok in sources_status.values() if ok),
        "sources_total": len(sources_status),
        "failed_sources": [n for n, ok in sources_status.items() if not ok],
    }


# ------------------------------------------------------------- rendering

def _esc(v) -> str:
    return htmlmod.escape(str(v if v is not None else ""))


def _job_card_html(job: dict) -> str:
    ai = job.get("ai_score") or {}
    det = job.get("deterministic_score") or {}
    ai_score = ai.get("fit_score")
    det_score = det.get("composite_score")

    band_score = ai_score if isinstance(ai_score, (int, float)) else det_score
    band = score_band(band_score)
    band_cls = BAND_CLASS.get(band, "unscored")

    score_bits = []
    if isinstance(ai_score, (int, float)):
        score_bits.append(f"AI {ai_score}")
    if isinstance(det_score, (int, float)):
        score_bits.append(f"KW {det_score}")
    score_text = " · ".join(score_bits) or "unscored"

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

    return f"""
    <article class="card band-{band_cls}" id="card-{job_id}">
      <header class="card-top">
        <div class="card-ident">
          <div class="company">{_esc(taxonomy.company_label(job.get("company", "")))}</div>
          <h3 class="role">{_esc(job.get("title", ""))}</h3>
        </div>
        <div class="card-score">
          <span class="badge badge-{band_cls}">{_esc(band)}</span>
          <span class="score-nums">{score_text}</span>
        </div>
      </header>
      <div class="meta">{" · ".join(meta_bits)} {dup}</div>
      {notes}
      <div class="actions">
        <button class="btn btn-primary" onclick="researchAndTailor('{job_id}')">Research + Tailor</button>
        <button class="btn btn-applied" onclick="markApplied('{job_id}')">Mark Applied</button>
        <a class="btn btn-ghost" href="{_esc(job.get("url", "#"))}" target="_blank" rel="noopener">View posting</a>
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


def render_feed_tab(jobs: dict, hidden_path: str, tracker_path: str, sources_status: dict) -> str:
    buckets = build_view(jobs, hidden_path)
    brief = build_daily_brief(jobs, hidden_path, tracker_path, sources_status)

    failed = ""
    if brief["failed_sources"]:
        failed = " · " + ", ".join(_esc(s) for s in brief["failed_sources"]) + " not configured"

    stats = [
        ("Discovered today", brief["discovered_today"], ""),
        ("Excellent (80+)", brief["excellent"], ""),
        ("Strong (65-79)", brief["strong"], ""),
        ("Worth applying", brief["worth_applying"], ""),
        ("Posted &lt; 1 hour", brief["posted_1h"], "is-urgent"),
        ("Posted &lt; 24 hours", brief["posted_24h"], ""),
        ("Applied this week", brief["applied_this_week"], ""),
        ("Awaiting response", brief["awaiting_response"], ""),
    ]
    stat_html = "".join(
        f'<div class="stat {cls}"><div class="stat-n">{v}</div>'
        f'<div class="stat-l">{label}</div></div>'
        for label, v, cls in stats
    )

    brief_html = f"""
    <section class="brief">
      <div class="brief-head">
        <span class="brief-title">Today</span>
        <span class="brief-date">{_esc(brief["date_label"])}</span>
        <span class="brief-sources">Sources live {brief["sources_live"]}/{brief["sources_total"]}{failed}</span>
      </div>
      <div class="stat-grid">{stat_html}</div>
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
          <td><a class="btn btn-ghost btn-sm" href="{_esc(r.get('url','#'))}" target="_blank" rel="noopener">Open</a></td>
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


def render_app_html(feed_html: str, applied_html: str, skills_gap_html: str, profile_html: str) -> str:
    generated = datetime.datetime.now().strftime("%a %b %d, %-I:%M %p")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Job Dashboard</title>
<style>
  :root {{
    --bg: #F7F6F3;
    --surface: #FFFFFF;
    --border: #E4E1DB;
    --border-strong: #D5D1C8;
    --ink: #17171A;
    --ink-2: #45454C;
    --muted: #8A867D;
    --accent: #1B3A4B;
    --accent-hover: #142C39;
    --accent-weak: #ECF1F4;
    --green: #2E6B4F;
    --green-weak: #EBF2ED;
    --radius: 3px;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, system-ui, sans-serif;
    font-size: 14px; line-height: 1.5;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 1080px; margin: 0 auto; padding: 36px 28px 80px; }}

  .masthead {{ display: flex; align-items: baseline; justify-content: space-between;
               padding-bottom: 18px; }}
  .masthead h1 {{ margin: 0; font-size: 19px; font-weight: 600; letter-spacing: -0.01em; }}
  .masthead .t-muted {{ font-size: 12px; }}
  .t-muted {{ color: var(--muted); }}

  /* tabs */
  .tabs {{ display: flex; gap: 26px; border-bottom: 1px solid var(--border); margin-bottom: 26px; }}
  .tab-btn {{ background: none; border: 0; padding: 0 0 12px; cursor: pointer;
              font-size: 13.5px; color: var(--muted); font-family: inherit;
              border-bottom: 2px solid transparent; margin-bottom: -1px; }}
  .tab-btn:hover {{ color: var(--ink-2); }}
  .tab-btn.active {{ color: var(--ink); font-weight: 600; border-bottom-color: var(--accent); }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}

  /* daily brief */
  .brief {{ background: var(--surface); border: 1px solid var(--border);
            border-radius: var(--radius); padding: 20px 22px; margin-bottom: 30px; }}
  .brief-head {{ display: flex; align-items: baseline; gap: 10px; margin-bottom: 18px; }}
  .brief-title {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.10em;
                  color: var(--muted); font-weight: 600; }}
  .brief-date {{ font-size: 12px; color: var(--ink-2); }}
  .brief-sources {{ margin-left: auto; font-size: 11.5px; color: var(--muted); }}
  .stat-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px 18px; }}
  .stat-n {{ font-size: 25px; font-weight: 600; letter-spacing: -0.02em;
             font-variant-numeric: tabular-nums; line-height: 1.15; }}
  .stat-l {{ font-size: 11.5px; color: var(--muted); margin-top: 2px; }}
  .stat.is-urgent .stat-n {{ color: var(--accent); }}
  .stat.is-urgent .stat-l {{ color: var(--accent); }}

  /* buckets */
  .bucket {{ margin-bottom: 40px; }}
  .bucket-head {{ display: flex; align-items: center; gap: 10px;
                  border-bottom: 1px solid var(--border); padding-bottom: 8px; margin-bottom: 14px; }}
  .bucket-head h2 {{ margin: 0; font-size: 11px; text-transform: uppercase;
                     letter-spacing: 0.10em; color: var(--ink-2); font-weight: 600; }}
  .bucket-head.is-urgent h2 {{ color: var(--accent); }}
  .bucket-count {{ font-size: 11.5px; color: var(--muted); font-variant-numeric: tabular-nums; }}

  /* filters */
  .filters {{ margin-bottom: 16px; }}
  .filter-row {{ display: flex; align-items: flex-start; gap: 12px; margin-bottom: 7px; }}
  .filter-label {{ font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em;
                   color: var(--muted); padding-top: 5px; min-width: 58px; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 5px; }}
  .chip {{ font-family: inherit; font-size: 12px; color: var(--ink-2);
           background: var(--surface); border: 1px solid var(--border);
           border-radius: var(--radius); padding: 4px 9px; cursor: pointer; }}
  .chip:hover {{ border-color: var(--border-strong); }}
  .chip.is-active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
  .chip-n {{ margin-left: 6px; color: var(--muted); font-variant-numeric: tabular-nums; }}
  .chip.is-active .chip-n {{ color: rgba(255,255,255,0.7); }}

  /* cards */
  .card {{ background: var(--surface); border: 1px solid var(--border);
           border-left: 2px solid var(--border-strong);
           border-radius: var(--radius); padding: 16px 18px; margin-bottom: 10px; }}
  .card.band-excellent {{ border-left-color: #2A5E43; }}
  .card.band-strong {{ border-left-color: #1B3A4B; }}
  .card.band-worth {{ border-left-color: #8A7433; }}
  .card.band-stretch {{ border-left-color: #A8A49B; }}
  .card.band-longshot {{ border-left-color: #DDDAD3; }}
  .card-top {{ display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; }}
  .company {{ font-size: 16px; font-weight: 600; letter-spacing: -0.01em; color: var(--ink); }}
  .role {{ margin: 1px 0 0; font-size: 13.5px; font-weight: 400; color: var(--ink-2); }}
  .card-score {{ text-align: right; white-space: nowrap; }}
  .badge {{ display: inline-block; font-size: 10.5px; letter-spacing: 0.02em;
            padding: 2px 7px; border-radius: var(--radius); border: 1px solid transparent; }}
  .badge-excellent {{ background: #E7EFE9; color: #2A5E43; border-color: #CFE0D6; }}
  .badge-strong {{ background: var(--accent-weak); color: var(--accent); border-color: #D3E0E7; }}
  .badge-worth {{ background: #F4EFE2; color: #6E5A2E; border-color: #E6DCC6; }}
  .badge-stretch {{ background: #F0EFEC; color: #55534E; border-color: #E2E0DA; }}
  .badge-longshot {{ background: #F5F4F2; color: var(--muted); border-color: #E8E6E1; }}
  .badge-unscored {{ background: #F5F4F2; color: var(--muted); border-color: #E8E6E1; }}
  .score-nums {{ display: block; margin-top: 4px; font-size: 11px; color: var(--muted);
                 font-variant-numeric: tabular-nums; }}
  .meta {{ margin-top: 8px; font-size: 11.5px; color: var(--muted); }}
  .tag {{ display: inline-block; font-size: 10.5px; color: var(--ink-2);
          background: #F3F2EF; border: 1px solid var(--border); border-radius: var(--radius);
          padding: 1px 6px; margin-left: 4px; }}
  /* Rationale text can run long; clamp so cards stay scannable and the
     list keeps an even rhythm rather than each card being a different height. */
  .note {{ margin: 8px 0 0; font-size: 12.5px; color: var(--ink-2);
           display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
           overflow: hidden; }}
  .note-partial {{ color: var(--accent); }}
  .actions {{ display: flex; gap: 7px; margin-top: 13px; }}
  .result {{ margin-top: 11px; font-size: 12.5px; color: var(--ink-2); white-space: pre-wrap;
             border-top: 1px solid var(--border); padding-top: 10px; display: none; }}
  .result.show {{ display: block; }}

  /* buttons */
  .btn {{ font-family: inherit; font-size: 12.5px; padding: 6px 12px; border-radius: var(--radius);
          cursor: pointer; border: 1px solid transparent; text-decoration: none;
          display: inline-block; line-height: 1.4; }}
  .btn-primary {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  .btn-primary:hover {{ background: var(--accent-hover); }}
  .btn-applied {{ background: var(--surface); color: var(--green); border-color: #BFD4C6; }}
  .btn-applied:hover {{ background: var(--green-weak); }}
  .btn-ghost {{ background: var(--surface); color: var(--ink-2); border-color: var(--border); }}
  .btn-ghost:hover {{ border-color: var(--border-strong); }}
  .btn-sm {{ font-size: 11.5px; padding: 3px 9px; }}
  .btn:disabled {{ opacity: 0.55; cursor: default; }}
  .btn-more {{ background: var(--surface); color: var(--ink-2); border-color: var(--border); width: 100%; }}
  .btn-more:hover {{ border-color: var(--border-strong); }}
  .more-n {{ color: var(--muted); margin-left: 6px; font-variant-numeric: tabular-nums; }}
  .load-more {{ margin-top: 12px; }}

  /* panels + tables */
  .panel {{ background: var(--surface); border: 1px solid var(--border);
            border-radius: var(--radius); padding: 18px 20px; margin-bottom: 18px; }}
  .panel-head {{ display: flex; align-items: baseline; gap: 12px; margin-bottom: 14px; }}
  .panel-head h2 {{ margin: 0; font-size: 13px; font-weight: 600; letter-spacing: -0.005em; }}
  .panel-head .input {{ margin-left: auto; }}
  .table {{ width: 100%; border-collapse: collapse; }}
  .table th {{ text-align: left; font-size: 10.5px; text-transform: uppercase;
               letter-spacing: 0.08em; color: var(--muted); font-weight: 600;
               padding: 0 10px 8px 0; border-bottom: 1px solid var(--border); }}
  .table td {{ padding: 9px 10px 9px 0; border-bottom: 1px solid var(--border); font-size: 13px;
               vertical-align: middle; }}
  .table tr:last-child td {{ border-bottom: 0; }}
  .t-company {{ font-weight: 600; }}
  .t-num {{ font-variant-numeric: tabular-nums; }}
  .effort {{ font-size: 11px; padding: 2px 7px; border-radius: var(--radius);
             border: 1px solid var(--border); background: #F5F4F2; color: var(--ink-2); }}
  .effort-easy {{ background: #E7EFE9; color: #2A5E43; border-color: #CFE0D6; }}
  .effort-hard {{ background: #F4EFE2; color: #6E5A2E; border-color: #E6DCC6; }}
  .list {{ margin: 0; padding-left: 18px; font-size: 13px; color: var(--ink-2); }}
  .list-compact li {{ margin: 3px 0; }}
  .footnote {{ font-size: 12px; }}

  /* forms */
  .input {{ font-family: inherit; font-size: 13px; padding: 6px 9px; color: var(--ink);
            background: var(--surface); border: 1px solid var(--border);
            border-radius: var(--radius); }}
  .input:focus {{ outline: none; border-color: var(--accent); }}
  .form-row {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
  .form-col {{ display: flex; flex-direction: column; gap: 8px; align-items: flex-start; max-width: 420px; }}
  .form-col .input {{ width: 100%; }}
  .empty {{ color: var(--muted); padding: 30px 0; }}
  code {{ font-size: 12px; background: #F1F0ED; padding: 1px 5px; border-radius: var(--radius); }}
</style>
</head>
<body>
<div class="wrap">
  <div class="masthead">
    <h1>Job Dashboard</h1>
    <span class="t-muted">{generated}</span>
  </div>

  <nav class="tabs">
    <button class="tab-btn active" onclick="showTab('feed', this)">Jobs Feed</button>
    <button class="tab-btn" onclick="showTab('applied', this)">Applied</button>
    <button class="tab-btn" onclick="showTab('skills-gap', this)">Skills Gap</button>
    <button class="tab-btn" onclick="showTab('profile', this)">Profile</button>
  </nav>

  <div id="tab-feed" class="tab-content active">{feed_html}</div>
  <div id="tab-applied" class="tab-content">{applied_html}</div>
  <div id="tab-skills-gap" class="tab-content">{skills_gap_html}</div>
  <div id="tab-profile" class="tab-content">{profile_html}</div>
</div>

<script>
function showTab(name, btn) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
}}

function feedQuery(bucket, offset) {{
  const sec = document.getElementById('bucket-' + bucket);
  const p = new URLSearchParams({{bucket: bucket, offset: offset}});
  if (sec.dataset.source) p.set('source', sec.dataset.source);
  if (sec.dataset.industry) p.set('industry', sec.dataset.industry);
  return '/api/feed/more?' + p.toString();
}}

function setFilter(btn, bucket, kind, value) {{
  const sec = document.getElementById('bucket-' + bucket);
  sec.dataset[kind] = value;
  sec.querySelectorAll('.chips[data-kind="' + kind + '"] .chip')
     .forEach(c => c.classList.toggle('is-active', c.dataset.value === value));

  const cards = document.getElementById('bucket-cards-' + bucket);
  cards.style.opacity = '0.45';
  fetch(feedQuery(bucket, 0))
    .then(r => r.json())
    .then(data => {{
      cards.innerHTML = data.html || '<p class="empty">No jobs match these filters.</p>';
      cards.style.opacity = '1';
      document.getElementById('count-' + bucket).textContent = data.total;
      document.getElementById('load-more-' + bucket).innerHTML = data.load_more_html || '';
    }})
    .catch(() => {{ cards.style.opacity = '1'; }});
}}

function loadMoreCards(btn) {{
  const bucket = btn.dataset.bucket;
  btn.disabled = true;
  btn.textContent = 'Loading...';
  fetch(feedQuery(bucket, btn.dataset.offset))
    .then(r => r.json())
    .then(data => {{
      document.getElementById('bucket-cards-' + bucket)
              .insertAdjacentHTML('beforeend', data.html);
      document.getElementById('load-more-' + bucket).innerHTML = data.load_more_html || '';
    }})
    .catch(() => {{ btn.disabled = false; btn.textContent = 'Retry'; }});
}}

function markApplied(jobId) {{
  // Reload on success: Applied, the brief counts and hide-until-reposted on
  // the feed all render server-side per page load.
  fetch('/api/apply/' + jobId, {{ method: 'POST' }})
    .then(r => r.json())
    .then(data => data.ok ? location.reload()
                          : alert('Failed: ' + (data.error || 'unknown error')))
    .catch(() => alert('Could not reach the local server.'));
}}

function researchAndTailor(jobId) {{
  const el = document.getElementById('result-' + jobId);
  el.classList.add('show');
  el.textContent = 'Researching and tailoring... up to a minute.';
  fetch('/api/research-tailor/' + jobId, {{ method: 'POST' }})
    .then(r => r.json())
    .then(data => {{
      if (!data.ok) {{ el.textContent = 'Failed: ' + (data.error || 'unknown error'); return; }}
      const t = data.tailor || {{}}, r2 = data.research || {{}};
      let out = '';
      if (t.baseline_coverage_pct !== undefined)
        out += 'Keyword coverage ' + t.baseline_coverage_pct + '% → ' + (t.tailored_coverage_pct ?? '?') + '%\\n';
      if (t.honest_gaps && t.honest_gaps.length)
        out += 'Gaps: ' + t.honest_gaps.slice(0, 3).join('; ') + '\\n';
      if (r2.company_brief) out += r2.company_brief + '\\n';
      if (r2.contacts && r2.contacts.length)
        out += 'Contacts: ' + r2.contacts.map(c => c.name + ' (' + c.title + ')').join(', ') + '\\n';
      el.textContent = out || 'Done.';
      if (t.pdf_url) {{
        const a = document.createElement('a');
        a.href = t.pdf_url; a.target = '_blank'; a.className = 'btn btn-ghost btn-sm';
        a.textContent = 'Open tailored resume';
        el.appendChild(document.createElement('br'));
        el.appendChild(a);
      }}
    }})
    .catch(() => {{ el.textContent = 'Could not reach the local server.'; }});
}}

function updateApplied(jobId, field, value) {{
  const body = {{}}; body[field] = value;
  fetch('/api/applied/' + jobId, {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)
  }});
}}

function filterApplied() {{
  const val = document.getElementById('applied-filter').value;
  document.querySelectorAll('#applied-table tbody tr').forEach(row => {{
    row.style.display = (!val || row.dataset.status === val) ? '' : 'none';
  }});
}}

function postProfile(url, payload) {{
  return fetch(url, {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload)
  }}).then(() => location.reload());
}}

function addSkill(ev) {{
  ev.preventDefault();
  postProfile('/api/profile/skill', {{
    group: document.getElementById('skill-group').value,
    skill: document.getElementById('skill-name').value
  }});
  return false;
}}

function addCert(ev) {{
  ev.preventDefault();
  postProfile('/api/profile/cert', {{ name: document.getElementById('cert-name').value }});
  return false;
}}

function addProject(ev) {{
  ev.preventDefault();
  postProfile('/api/profile/project', {{
    name: document.getElementById('project-name').value,
    description: document.getElementById('project-desc').value,
    link: document.getElementById('project-link').value
  }});
  return false;
}}
</script>
</body>
</html>"""
