"""
Dashboard: daily brief (Part 5) + 4-tab app shell (Part 8).

One page, tab navigation client-side -- not four separate tools. Tab
content is rendered server-side on each full load; actions (mark applied,
update status/notes, add a skill, research+tailor) hit small JSON
endpoints in server.py and either patch the DOM in place or reload.
"""
import datetime
import html as htmlmod

from datehelpers import parse_posted_at
from scoring.bands import score_band
import hidden as hidden_mod
import tracker as tracker_mod
import skillsgap

MAX_AGE_DAYS = 30
PAGE_SIZE = 25  # cards rendered per bucket before a "Load more" button appears

BUCKET_ORDER = [
    "Posted in the last hour",
    "Posted in the last 24 hours",
    "This week",
    "This month",
]

# Short, URL-safe keys for the pagination endpoint -- avoids passing the
# raw display name (with spaces) through a query string.
BUCKET_KEY_BY_NAME = {
    "Posted in the last hour": "hour",
    "Posted in the last 24 hours": "24h",
    "This week": "week",
    "This month": "month",
}
BUCKET_NAME_BY_KEY = {v: k for k, v in BUCKET_KEY_BY_NAME.items()}


def _score_for_sort(job: dict):
    ai = (job.get("ai_score") or {}).get("fit_score")
    det = (job.get("deterministic_score") or {}).get("composite_score")
    if isinstance(ai, (int, float)):
        return ai
    if isinstance(det, (int, float)):
        return det
    return -1


def _bucket(posted_dt, now):
    if posted_dt is None:
        return None
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


def build_daily_brief(jobs: dict, hidden_path: str, tracker_path: str, sources_status: dict) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    today = now.date()

    discovered_today = excellent = strong = worth_applying = 0
    posted_1h = posted_24h = 0

    for job in jobs.values():
        discovered_dt = parse_posted_at(job.get("discovered_at"))
        if discovered_dt and discovered_dt.date() == today:
            discovered_today += 1

        score = _score_for_sort(job)
        band = score_band(score if score >= 0 else None)
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

    live_count = sum(1 for ok in sources_status.values() if ok)
    failed_sources = [name for name, ok in sources_status.items() if not ok]

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
        "sources_live": live_count,
        "sources_total": len(sources_status),
        "failed_sources": failed_sources,
    }


def _job_card_html(job: dict) -> str:
    ai = job.get("ai_score") or {}
    det = job.get("deterministic_score") or {}
    ai_score = ai.get("fit_score")
    det_score = det.get("composite_score")

    band_score = ai_score if isinstance(ai_score, (int, float)) else det_score
    band = score_band(band_score)
    band_class = "band-" + band.lower().replace(" ", "-")

    scores_line = f"det={det_score if det_score is not None else '?'}"
    if isinstance(ai_score, (int, float)):
        scores_line += f" &middot; ai={ai_score}"

    track = det.get("best_track") or ai.get("best_matching_track") or ""
    why = htmlmod.escape(ai.get("why", ""))
    partial = htmlmod.escape(ai.get("partial_match_rationale", "") or "")
    title = htmlmod.escape(job.get("title", ""))
    company = htmlmod.escape(job.get("company", ""))
    location = htmlmod.escape(job.get("location", ""))
    url = htmlmod.escape(job.get("url", "#"))
    job_id = htmlmod.escape(job.get("job_id", ""))
    company_brief = htmlmod.escape(job.get("company_brief", ""))

    dup_badge = ""
    also_found_on = job.get("also_found_on")
    if job.get("duplicate") and also_found_on:
        sources_txt = " + ".join(htmlmod.escape(s) for s in also_found_on)
        dup_badge = f'<span class="badge-dup">Also on {sources_txt}</span>'

    why_html = f'<p class="why">{why}</p>' if why else ""
    partial_html = f'<p class="partial">Partial match: {partial}</p>' if partial else ""
    brief_html = f'<p class="brief">{company_brief}</p>' if company_brief else ""

    return f"""
    <div class="card" id="card-{job_id}">
      <div class="card-header">
        <span class="score {band_class}">{band} &middot; {scores_line}</span>
        <span class="track">{htmlmod.escape(track)}</span>
      </div>
      <h3>{title}</h3>
      <div class="meta">{company} &middot; {location} {dup_badge}</div>
      {brief_html}
      {why_html}
      {partial_html}
      <div class="actions">
        <a href="{url}" target="_blank" class="btn btn-view">View posting</a>
        <button class="btn btn-tailor" onclick="researchAndTailor('{job_id}')">Research + Tailor</button>
        <button class="btn btn-apply" onclick="markApplied('{job_id}')">Mark Applied</button>
      </div>
      <div class="result" id="result-{job_id}"></div>
    </div>
    """


def _render_brief_html(brief: dict) -> str:
    failed = ""
    if brief["failed_sources"]:
        failed = " (" + ", ".join(htmlmod.escape(s) for s in brief["failed_sources"]) + " failed - check login)"
    return f"""
    <div class="brief-panel">
      <div class="brief-title">TODAY &middot; {brief['date_label']}</div>
      <div class="brief-grid">
        <div class="brief-stat"><span class="n">{brief['discovered_today']}</span> Jobs discovered today</div>
        <div class="brief-stat"><span class="n">{brief['excellent']}</span> Excellent matches (80+)</div>
        <div class="brief-stat"><span class="n">{brief['strong']}</span> Strong matches (65-79)</div>
        <div class="brief-stat"><span class="n">{brief['worth_applying']}</span> Worth applying (45-64)</div>
        <div class="brief-stat loud"><span class="n">{brief['posted_1h']}</span> Posted &lt; 1 hour &larr; apply now</div>
        <div class="brief-stat"><span class="n">{brief['posted_24h']}</span> Posted &lt; 24 hours</div>
        <div class="brief-stat"><span class="n">{brief['applied_this_week']}</span> Applied this week</div>
        <div class="brief-stat"><span class="n">{brief['awaiting_response']}</span> Awaiting response</div>
      </div>
      <div class="brief-sources">Sources live: {brief['sources_live']}/{brief['sources_total']}{failed}</div>
    </div>
    """


def _load_more_button(bucket_key: str, next_offset: int, remaining: int) -> str:
    return (
        f'<button class="btn btn-load-more" data-bucket="{bucket_key}" '
        f'data-offset="{next_offset}" onclick="loadMoreCards(this)">'
        f'Load {min(remaining, PAGE_SIZE)} more ({remaining} remaining)</button>'
    )


def render_feed_tab(jobs: dict, hidden_path: str, tracker_path: str, sources_status: dict) -> str:
    buckets = build_view(jobs, hidden_path)
    brief = build_daily_brief(jobs, hidden_path, tracker_path, sources_status)

    sections = ""
    for name in BUCKET_ORDER:
        bucket_jobs = buckets.get(name, [])
        if not bucket_jobs:
            continue
        bucket_key = BUCKET_KEY_BY_NAME[name]
        page = bucket_jobs[:PAGE_SIZE]
        cards = "\n".join(_job_card_html(j) for j in page)
        loud_class = " loud-heading" if name == "Posted in the last hour" else ""
        remaining = len(bucket_jobs) - len(page)
        load_more = (f'<div class="load-more-row" id="load-more-{bucket_key}">'
                      f'{_load_more_button(bucket_key, PAGE_SIZE, remaining)}</div>'
                     ) if remaining > 0 else ""
        sections += (
            f'<h2 class="bucket-title{loud_class}">{htmlmod.escape(name)} '
            f'<span class="count">({len(bucket_jobs)})</span></h2>\n'
            f'<div class="bucket-cards" id="bucket-cards-{bucket_key}">{cards}</div>\n{load_more}\n'
        )
    if not sections:
        sections = ('<p class="empty">No jobs to show. Run <code>python cli.py scrape</code> '
                    'and <code>python cli.py score</code> first.</p>')

    return _render_brief_html(brief) + sections


def render_more_cards(jobs: dict, hidden_path: str, bucket_key: str, offset: int) -> dict:
    """Backs the /api/feed/more AJAX endpoint. Recomputes the same bucketed,
    score-sorted view build_view already produces -- deterministic given
    the same jobs dict, so slicing [offset:offset+PAGE_SIZE] lines up
    exactly with what the initial page render already showed before it."""
    bucket_name = BUCKET_NAME_BY_KEY.get(bucket_key)
    if not bucket_name:
        return {"html": "", "has_more": False, "next_offset": offset}

    buckets = build_view(jobs, hidden_path)
    bucket_jobs = buckets.get(bucket_name, [])
    page = bucket_jobs[offset:offset + PAGE_SIZE]
    html = "\n".join(_job_card_html(j) for j in page)
    next_offset = offset + len(page)
    remaining = len(bucket_jobs) - next_offset
    return {
        "html": html,
        "has_more": remaining > 0,
        "next_offset": next_offset,
        "remaining": max(remaining, 0),
    }


def render_applied_tab(tracker_path: str) -> str:
    rows = tracker_mod.read_all(tracker_path)
    rows.sort(key=lambda r: r.get("last_updated", ""), reverse=True)

    if not rows:
        return '<p class="empty">No applications tracked yet.</p>'

    statuses = ["applied", "screening", "interview", "rejected", "offer"]
    body_rows = ""
    for r in rows:
        jid = htmlmod.escape(r["job_id"])
        options = "".join(
            f'<option value="{s}"{" selected" if r.get("status") == s else ""}>{s}</option>'
            for s in statuses
        )
        body_rows += f"""
        <tr>
          <td>{htmlmod.escape(r.get('company',''))}</td>
          <td>{htmlmod.escape(r.get('title',''))}</td>
          <td><a href="{htmlmod.escape(r.get('url','#'))}" target="_blank">link</a></td>
          <td>{htmlmod.escape(r.get('last_updated',''))}</td>
          <td><select onchange="updateApplied('{jid}', 'status', this.value)">{options}</select></td>
          <td><input type="text" value="{htmlmod.escape(r.get('notes',''))}"
                     onchange="updateApplied('{jid}', 'notes', this.value)"></td>
        </tr>"""

    return f"""
    <div class="filter-row">
      Filter: <select id="applied-filter" onchange="filterApplied()">
        <option value="">All statuses</option>
        {''.join(f'<option value="{s}">{s}</option>' for s in statuses)}
      </select>
    </div>
    <table class="applied-table" id="applied-table">
      <thead><tr><th>Company</th><th>Title</th><th>URL</th><th>Last updated</th>
      <th>Status</th><th>Notes</th></tr></thead>
      <tbody>{body_rows}</tbody>
    </table>
    """


def render_skills_gap_tab(tailored_dir: str) -> str:
    data = skillsgap.aggregate(tailored_dir)
    if data["total_resumes_analyzed"] == 0:
        return ('<p class="empty">No tailored resumes yet. Run '
                '<code>python cli.py tailor --job-id X</code> to generate the first one.</p>')

    top_rows = "".join(
        f'<tr><td>{htmlmod.escape(s["label"])}</td><td>{s["count"]}</td>'
        f'<td>{s["effort"]}</td></tr>'
        for s in data["top_skills_to_learn"]
    )
    cert_rows = "".join(
        f'<li>{htmlmod.escape(c["label"])} ({c["count"]}x)</li>'
        for c in data["certifications_missing"]
    ) or "<li>None</li>"

    return f"""
    <p class="subtitle">Aggregated from {data['total_resumes_analyzed']} tailored resume(s).</p>
    <h2 class="bucket-title">Top 10 Skills to Learn</h2>
    <table class="applied-table">
      <thead><tr><th>Skill / gap</th><th># jobs demanding it</th><th>Effort</th></tr></thead>
      <tbody>{top_rows}</tbody>
    </table>
    <h2 class="bucket-title">Certifications Missing</h2>
    <ul>{cert_rows}</ul>
    """


def render_profile_tab(profile: dict) -> str:
    skill_groups = "".join(f'<option value="{htmlmod.escape(g)}">{htmlmod.escape(g)}</option>'
                            for g in profile.get("skills", {}).keys())
    certs = ", ".join(htmlmod.escape(c) for c in profile.get("certifications_earned", []))
    projects = "".join(f'<li>{htmlmod.escape(p.get("name",""))}</li>' for p in profile.get("projects", []))

    return f"""
    <h2 class="bucket-title">Add a skill</h2>
    <form onsubmit="return addSkill(event)">
      <select id="skill-group">{skill_groups}</select>
      <input type="text" id="skill-name" placeholder="e.g. Kubernetes" required>
      <button class="btn btn-apply" type="submit">Add skill</button>
    </form>

    <h2 class="bucket-title">Add a certification</h2>
    <form onsubmit="return addCert(event)">
      <input type="text" id="cert-name" placeholder="Certification name" required>
      <button class="btn btn-apply" type="submit">Add certification</button>
    </form>
    <p class="subtitle">Currently earned: {certs or "none"}</p>

    <h2 class="bucket-title">Add a project</h2>
    <form onsubmit="return addProject(event)">
      <input type="text" id="project-name" placeholder="Project name" required><br>
      <input type="text" id="project-desc" placeholder="One-line description" required><br>
      <input type="text" id="project-link" placeholder="GitHub/Hugging Face link (optional)">
      <button class="btn btn-apply" type="submit">Add project</button>
    </form>
    <p class="subtitle">Current projects: {projects}</p>
    <p class="subtitle">Changes here write directly to profile.json -- the next
    Research + Tailor run picks them up immediately, no restart needed.</p>
    """


def render_app_html(feed_html: str, applied_html: str, skills_gap_html: str, profile_html: str) -> str:
    generated = datetime.datetime.now().strftime("%a %b %d, %I:%M %p")
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Shiva's Job Dashboard</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; max-width: 960px;
          margin: 30px auto; padding: 0 20px; background: #fafafa; color: #1a1a1a; }}
  h1 {{ font-size: 22px; margin-bottom: 2px; }}
  .subtitle {{ color: #777; font-size: 13px; }}

  .tabs {{ display: flex; gap: 4px; margin: 16px 0 20px; border-bottom: 2px solid #e2e2e2; }}
  .tab-btn {{ padding: 10px 18px; border: none; background: none; font-size: 14px;
              cursor: pointer; color: #666; border-bottom: 2px solid transparent;
              margin-bottom: -2px; }}
  .tab-btn.active {{ color: #1a1a1a; font-weight: 600; border-bottom-color: #1a1a1a; }}
  .tab-content {{ display: none; }}
  .tab-content.active {{ display: block; }}

  .brief-panel {{ background: #1a1a1a; color: white; border-radius: 10px; padding: 18px 22px; margin-bottom: 24px; }}
  .brief-title {{ font-size: 13px; letter-spacing: 0.08em; color: #aaa; margin-bottom: 12px; }}
  .brief-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px 24px; font-size: 14px; }}
  .brief-stat .n {{ font-weight: 700; margin-right: 6px; }}
  .brief-stat.loud {{ color: #ffd166; font-weight: 600; }}
  .brief-sources {{ margin-top: 12px; font-size: 12px; color: #999; }}

  .bucket-title {{ margin-top: 32px; font-size: 16px; text-transform: uppercase;
                    letter-spacing: 0.03em; color: #555; border-bottom: 1px solid #ddd;
                    padding-bottom: 6px; }}
  .bucket-title.loud-heading {{ color: #b8860b; }}
  .count {{ color: #999; font-weight: normal; }}

  .card {{ background: white; border: 1px solid #e2e2e2; border-radius: 8px;
           padding: 16px; margin: 12px 0; }}
  .card-header {{ display: flex; justify-content: space-between; font-size: 12px; color: #666; }}
  .score {{ font-weight: 600; padding: 2px 8px; border-radius: 4px; }}
  .band-excellent-match {{ background: #d4f4dd; color: #0a7d3c; }}
  .band-strong-match {{ background: #dcecfb; color: #0b5fa8; }}
  .band-worth-applying {{ background: #fdf3d0; color: #8a6d00; }}
  .band-stretch {{ background: #f1e4fb; color: #6a3fa0; }}
  .band-long-shot {{ background: #eee; color: #888; }}
  .card h3 {{ margin: 6px 0 4px; font-size: 17px; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 8px; }}
  .badge-dup {{ background: #eef; color: #446; border-radius: 4px; padding: 1px 6px; font-size: 11px; margin-left: 6px; }}
  .why, .brief, .partial {{ font-size: 13px; color: #333; margin: 4px 0; }}
  .partial {{ font-style: italic; color: #6a3fa0; }}
  .actions {{ margin-top: 10px; display: flex; gap: 8px; }}
  .btn {{ padding: 6px 14px; border-radius: 6px; font-size: 13px;
          cursor: pointer; text-decoration: none; border: 1px solid #ccc; background: #f0f0f0; color: #1a1a1a; }}
  .btn-apply {{ background: #1a1a1a; color: white; border: none; }}
  .btn-tailor {{ background: #0b5fa8; color: white; border: none; }}
  .btn:disabled {{ background: #999; cursor: default; }}
  .result {{ margin-top: 10px; font-size: 13px; white-space: pre-wrap; }}
  .empty {{ color: #777; margin-top: 40px; }}
  .load-more-row {{ text-align: center; margin: 16px 0 8px; }}
  .btn-load-more {{ background: white; border: 1px solid #bbb; padding: 8px 20px; }}
  .btn-load-more:disabled {{ opacity: 0.6; }}

  table.applied-table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
  table.applied-table th, table.applied-table td {{ text-align: left; padding: 8px; border-bottom: 1px solid #eee; font-size: 13px; }}
  input[type=text], select {{ padding: 6px; font-size: 13px; border: 1px solid #ccc; border-radius: 4px; margin: 4px 6px 4px 0; }}
</style>
</head>
<body>
<h1>Shiva's Job Dashboard</h1>
<p class="subtitle">Generated {generated}</p>

<div class="tabs">
  <button class="tab-btn active" onclick="showTab('feed', this)">Jobs Feed</button>
  <button class="tab-btn" onclick="showTab('applied', this)">Applied Jobs</button>
  <button class="tab-btn" onclick="showTab('skills-gap', this)">Skills Gap Analysis</button>
  <button class="tab-btn" onclick="showTab('profile', this)">Your Profile Updates</button>
</div>

<div id="tab-feed" class="tab-content active">{feed_html}</div>
<div id="tab-applied" class="tab-content">{applied_html}</div>
<div id="tab-skills-gap" class="tab-content">{skills_gap_html}</div>
<div id="tab-profile" class="tab-content">{profile_html}</div>

<script>
function showTab(name, btn) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');
}}

function loadMoreCards(btn) {{
  const bucket = btn.dataset.bucket;
  const offset = btn.dataset.offset;
  btn.disabled = true;
  btn.textContent = 'Loading...';
  fetch('/api/feed/more?bucket=' + encodeURIComponent(bucket) + '&offset=' + offset)
    .then(r => r.json())
    .then(data => {{
      const container = document.getElementById('bucket-cards-' + bucket);
      container.insertAdjacentHTML('beforeend', data.html);
      const row = document.getElementById('load-more-' + bucket);
      if (data.has_more) {{
        btn.dataset.offset = data.next_offset;
        btn.disabled = false;
        btn.textContent = 'Load ' + Math.min(data.remaining, 25) + ' more (' + data.remaining + ' remaining)';
      }} else {{
        row.remove();
      }}
    }})
    .catch(() => {{ btn.disabled = false; btn.textContent = 'Failed to load -- try again'; }});
}}

function markApplied(jobId) {{
  // Reloads on success (like the profile-update actions) rather than just
  // patching this one card -- Applied Jobs, the daily brief counts, and the
  // hide-until-reposted behavior on the Jobs Feed all need to reflect this
  // too, and they're rendered server-side once per page load, not fetched
  // live per tab.
  fetch('/api/apply/' + jobId, {{ method: 'POST' }})
    .then(r => r.json())
    .then(data => {{
      if (data.ok) {{
        location.reload();
      }} else {{
        alert('Failed to mark applied: ' + (data.error || 'unknown error'));
      }}
    }})
    .catch(() => alert('Could not reach the local server.'));
}}

function researchAndTailor(jobId) {{
  const resultEl = document.getElementById('result-' + jobId);
  resultEl.textContent = 'Researching + tailoring... this can take up to a minute.';
  fetch('/api/research-tailor/' + jobId, {{ method: 'POST' }})
    .then(r => r.json())
    .then(data => {{
      if (!data.ok) {{
        resultEl.textContent = 'Failed: ' + (data.error || 'unknown error');
        return;
      }}
      const t = data.tailor || {{}};
      const r = data.research || {{}};
      let out = '';
      if (t.baseline_coverage_pct !== undefined) {{
        out += 'Coverage: ' + t.baseline_coverage_pct + '% -> ' + (t.tailored_coverage_pct ?? '?') + '%\\n';
      }}
      if (t.honest_gaps && t.honest_gaps.length) {{
        out += 'Gaps: ' + t.honest_gaps.slice(0,3).join('; ') + '\\n';
      }}
      if (t.pdf_url) {{
        out += 'Resume: ' + t.pdf_url + '\\n';
      }}
      if (r.company_brief) {{
        out += '\\n' + r.company_brief + '\\n';
      }}
      if (r.contacts && r.contacts.length) {{
        out += 'Contacts: ' + r.contacts.map(c => c.name + ' (' + c.title + ')').join(', ') + '\\n';
      }}
      resultEl.textContent = out || 'Done.';
    }})
    .catch(() => {{ resultEl.textContent = 'Could not reach the local server.'; }});
}}

function updateApplied(jobId, field, value) {{
  const body = {{}};
  body[field] = value;
  fetch('/api/applied/' + jobId, {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify(body)
  }});
}}

function filterApplied() {{
  const val = document.getElementById('applied-filter').value;
  document.querySelectorAll('#applied-table tbody tr').forEach(row => {{
    const status = row.querySelector('select').value;
    row.style.display = (!val || status === val) ? '' : 'none';
  }});
}}

function addSkill(ev) {{
  ev.preventDefault();
  const group = document.getElementById('skill-group').value;
  const skill = document.getElementById('skill-name').value;
  fetch('/api/profile/skill', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{group, skill}})
  }}).then(() => location.reload());
  return false;
}}

function addCert(ev) {{
  ev.preventDefault();
  const name = document.getElementById('cert-name').value;
  fetch('/api/profile/cert', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{name}})
  }}).then(() => location.reload());
  return false;
}}

function addProject(ev) {{
  ev.preventDefault();
  const name = document.getElementById('project-name').value;
  const description = document.getElementById('project-desc').value;
  const link = document.getElementById('project-link').value;
  fetch('/api/profile/project', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{name, description, link}})
  }}).then(() => location.reload());
  return false;
}}
</script>
</body>
</html>"""
