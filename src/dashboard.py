"""
Builds the dashboard view (recency-bucketed, score-sorted, hidden jobs
filtered out unless reposted) and renders it to HTML.

Sort logic matches what Shiva asked for: primary grouping by how recently
the job was posted (last 24h at the top), score-sorted within each group.
Anything older than MAX_AGE_DAYS is dropped from the default view entirely.
"""
import datetime
import html as htmlmod

from datehelpers import parse_posted_at
import hidden as hidden_mod

MAX_AGE_DAYS = 30

BUCKET_ORDER = ["Posted in the last 24 hours", "This week", "This month"]


def _score_for_sort(job: dict) -> float:
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
    if age <= datetime.timedelta(hours=24):
        return "Posted in the last 24 hours"
    if age <= datetime.timedelta(days=7):
        return "This week"
    if age <= datetime.timedelta(days=MAX_AGE_DAYS):
        return "This month"
    return None  # older than a month -- out of scope per spec


def build_view(jobs: dict, hidden_path: str) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    hidden_store = hidden_mod.load(hidden_path)

    buckets = {name: [] for name in BUCKET_ORDER}

    for job in jobs.values():
        company = job.get("company", "")
        title = job.get("title", "")
        posted_raw = job.get("posted_at")

        if hidden_mod.is_hidden(hidden_store, company, title, posted_raw):
            continue

        posted_dt = parse_posted_at(posted_raw)
        bucket_name = _bucket(posted_dt, now)
        if bucket_name is None:
            continue

        buckets[bucket_name].append(job)

    for bucket_jobs in buckets.values():
        bucket_jobs.sort(key=_score_for_sort, reverse=True)

    return buckets


def _job_card_html(job: dict) -> str:
    ai = job.get("ai_score") or {}
    det = job.get("deterministic_score") or {}
    ai_score = ai.get("fit_score")

    if isinstance(ai_score, (int, float)):
        score_label = f"{ai_score}/100 (AI fit)"
    else:
        score_label = f"{det.get('composite_score', '?')}/100 (keyword match)"

    track = det.get("best_track") or ai.get("best_matching_track") or ""
    why = htmlmod.escape(ai.get("why", ""))
    title = htmlmod.escape(job.get("title", ""))
    company = htmlmod.escape(job.get("company", ""))
    location = htmlmod.escape(job.get("location", ""))
    url = htmlmod.escape(job.get("url", "#"))
    job_id = htmlmod.escape(job.get("job_id", ""))

    why_html = f'<p class="why">{why}</p>' if why else ""

    return f"""
    <div class="card" id="card-{job_id}">
      <div class="card-header">
        <span class="score">{score_label}</span>
        <span class="track">{htmlmod.escape(track)}</span>
      </div>
      <h3>{title}</h3>
      <div class="meta">{company} &middot; {location}</div>
      {why_html}
      <div class="actions">
        <a href="{url}" target="_blank" class="btn-view">View posting</a>
        <button class="btn-apply" onclick="markApplied('{job_id}')">Mark Applied</button>
      </div>
    </div>
    """


def render_html(buckets: dict) -> str:
    sections = ""
    for name in BUCKET_ORDER:
        jobs = buckets.get(name, [])
        if not jobs:
            continue
        cards = "\n".join(_job_card_html(j) for j in jobs)
        sections += (
            f'<h2 class="bucket-title">{htmlmod.escape(name)} '
            f'<span class="count">({len(jobs)})</span></h2>\n{cards}\n'
        )

    if not sections:
        sections = (
            '<p class="empty">No jobs to show. Run <code>python cli.py pull</code> '
            'and <code>python cli.py score</code> first.</p>'
        )

    generated = datetime.datetime.now().strftime("%a %b %d, %I:%M %p")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Shiva's Job Dashboard</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", sans-serif; max-width: 900px;
          margin: 40px auto; padding: 0 20px; background: #fafafa; color: #1a1a1a; }}
  h1 {{ font-size: 22px; }}
  .subtitle {{ color: #777; font-size: 13px; }}
  .bucket-title {{ margin-top: 32px; font-size: 16px; text-transform: uppercase;
                    letter-spacing: 0.03em; color: #555; border-bottom: 1px solid #ddd;
                    padding-bottom: 6px; }}
  .count {{ color: #999; font-weight: normal; }}
  .card {{ background: white; border: 1px solid #e2e2e2; border-radius: 8px;
           padding: 16px; margin: 12px 0; }}
  .card-header {{ display: flex; justify-content: space-between; font-size: 12px; color: #666; }}
  .score {{ font-weight: 600; color: #0a7d3c; }}
  .card h3 {{ margin: 6px 0 4px; font-size: 17px; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 8px; }}
  .why {{ font-size: 13px; color: #333; }}
  .actions {{ margin-top: 10px; display: flex; gap: 8px; }}
  .btn-view, .btn-apply {{ padding: 6px 14px; border-radius: 6px; font-size: 13px;
                            cursor: pointer; text-decoration: none; border: 1px solid #ccc; }}
  .btn-view {{ background: #f0f0f0; color: #1a1a1a; }}
  .btn-apply {{ background: #1a1a1a; color: white; border: none; }}
  .btn-apply:disabled {{ background: #999; cursor: default; }}
  .empty {{ color: #777; margin-top: 40px; }}
</style>
</head>
<body>
<h1>Shiva's Job Dashboard</h1>
<p class="subtitle">Generated {generated}. Sorted by how recently posted, then match score.</p>
{sections}
<script>
function markApplied(jobId) {{
  fetch('/apply/' + jobId, {{ method: 'POST' }})
    .then(r => r.json())
    .then(data => {{
      const card = document.getElementById('card-' + jobId);
      if (data.ok) {{
        card.style.opacity = '0.4';
        const btn = card.querySelector('.btn-apply');
        btn.textContent = 'Applied \\u2713';
        btn.disabled = true;
      }} else {{
        alert('Failed to mark applied: ' + (data.error || 'unknown error'));
      }}
    }})
    .catch(() => alert('Could not reach the local server. Run: python server.py'));
}}
</script>
</body>
</html>"""
