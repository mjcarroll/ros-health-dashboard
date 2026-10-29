import html
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .store import Store

WINDOW_DAYS = 30
MATRIX_DAYS = 14

GLYPH = {"SUCCESS": "✓", "UNSTABLE": "!", "FAILURE": "✗", "RUNNING": "●", "ABORTED": "–", "NOT_BUILT": "–"}

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ROS 2 health</title>
<style>
:root {{ --fg:#1a1a1a; --bg:#fff; --muted:#666; --line:#2563eb; --rule:#e5e5e5; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --fg:#e8e8e8; --bg:#111; --muted:#999; --line:#60a5fa; --rule:#2a2a2a; }}
}}
body {{ font:15px system-ui,sans-serif; color:var(--fg); background:var(--bg); max-width:52rem; margin:2rem auto; padding:0 1rem; }}
h2 {{ margin-top:2rem; }} table {{ width:100%; border-collapse:collapse; }}
td {{ padding:.4rem .5rem; border-bottom:1px solid var(--rule); }}
td.v {{ text-align:right; font-variant-numeric:tabular-nums; }}
svg {{ stroke:var(--line); fill:none; stroke-width:1.5; vertical-align:middle; }}
.muted {{ color:var(--muted); font-size:.85em; }}
:root {{ --ok-bg:#dafbe1; --ok:#1a7f37; --warn-bg:#fff8c5; --warn:#9a6700; --bad-bg:#ffebe9; --bad:#cf222e;
  --off-bg:#eaeef2; --off:#57606a; --run-bg:#ddf4ff; --run:#0969da; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --ok-bg:#12261e; --ok:#3fb950; --warn-bg:#272115; --warn:#d29922; --bad-bg:#2d1215; --bad:#f85149;
    --off-bg:#21262d; --off:#8b949e; --run-bg:#0c2d6b; --run:#58a6ff; }}
}}
.scroll {{ overflow-x:auto; }}
table.matrix {{ width:auto; border-collapse:separate; border-spacing:2px; font-size:.85em; }}
.matrix th {{ font-weight:500; color:var(--muted); padding:.1rem .2rem; text-align:center; white-space:nowrap; }}
.matrix th.job {{ text-align:left; position:sticky; left:0; background:var(--bg); padding-right:.75rem; }}
.matrix th.job a {{ color:var(--fg); text-decoration:none; }}
.matrix th.job a:hover {{ text-decoration:underline; }}
.matrix td {{ padding:0; border:0; }}
.matrix td.n {{ color:var(--muted); padding-left:.6rem; white-space:nowrap; font-variant-numeric:tabular-nums; }}
a.c {{ display:block; min-width:2rem; text-align:center; padding:.2rem 0; border-radius:4px; text-decoration:none; font-weight:600; }}
a.c sup {{ font-weight:400; font-size:.7em; }}
.SUCCESS {{ background:var(--ok-bg); color:var(--ok); }} .UNSTABLE {{ background:var(--warn-bg); color:var(--warn); }}
.FAILURE {{ background:var(--bad-bg); color:var(--bad); }} .RUNNING {{ background:var(--run-bg); color:var(--run); }}
.ABORTED, .NOT_BUILT, .OTHER {{ background:var(--off-bg); color:var(--off); }}
.legend span {{ margin-right:1rem; }}
</style>
<h1>ROS 2 health</h1>
<p class="muted">Updated {updated} UTC. Last {days} days.</p>
{body}
"""


def _spark(points: list[tuple[int, float]], w=140, h=28) -> str:
    if len(points) < 2:
        return ""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sx = (w - 2) / ((x1 - x0) or 1)
    sy = (h - 4) / ((y1 - y0) or 1)
    pts = " ".join(f"{1 + (x - x0) * sx:.1f},{h - 2 - (y - y0) * sy:.1f}" for x, y in points)
    return f'<svg width="{w}" height="{h}" role="img"><polyline points="{pts}"/></svg>'


def _fmt(v: float) -> str:
    return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"


def _job_url(build_url: str) -> str:
    return build_url.rstrip("/").rsplit("/", 1)[0] + "/"


def _duration(seconds: int) -> str:
    h, m = divmod(seconds // 60, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


def _cell(builds: list[dict]) -> str:
    """Latest build of the day links to Jenkins; extra same-day builds show as a count."""
    b = max(builds, key=lambda x: x["ts"])
    cls = b["result"] if b["result"] in GLYPH else "OTHER"
    tests = ""
    if b["total"] is not None:
        tests = f" · {b['fail']} failed / {b['total']} tests"
    title = f"{b['result']} #{b['number']}{tests} · {_duration(b['duration_s'])}"
    if len(builds) > 1:
        title += f" · {len(builds)} builds that day"
    extra = f"<sup>{len(builds)}</sup>" if len(builds) > 1 else ""
    return (f'<td><a class="c {cls}" href="{html.escape(b["url"])}" '
            f'title="{html.escape(title)}">{GLYPH.get(cls, "?")}{extra}</a></td>')


def render_matrix(store: Store, now: float) -> str:
    today = datetime.fromtimestamp(now, timezone.utc).date()
    days = [today - timedelta(days=i) for i in range(MATRIX_DAYS)]  # newest first
    since = int(datetime.combine(days[-1], datetime.min.time(), timezone.utc).timestamp())
    rows = store.query(
        "SELECT server, grp, job, number, ts, result, duration_s, fail, total, url "
        "FROM build WHERE ts >= ? ORDER BY server, grp, job, ts", [since])
    if not rows:
        return ""

    sections: dict[tuple, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in rows:
        day = datetime.fromtimestamp(r["ts"], timezone.utc).date()
        sections[(r["server"], r["grp"])][r["job"]][day].append(r)

    head = "".join(f'<th title="{d:%Y-%m-%d}">{d:%m-%d}<br>{d:%a}</th>' for d in days)
    out = [
        "<h2>Nightly builds</h2>",
        '<p class="legend muted"><span>✓ success</span><span>! unstable (test failures)</span>'
        "<span>✗ failed</span><span>● running</span><span>– aborted</span>"
        f"<span>days are UTC; cells link to the build in Jenkins</span></p>",
    ]
    for (server, grp), jobs in sorted(sections.items()):
        title = server if grp == "nightly" else f"{server} · {grp}"
        body = []
        for job, by_day in sorted(jobs.items()):
            sample = next(iter(by_day.values()))[0]
            cells = "".join(_cell(by_day[d]) if d in by_day else "<td></td>" for d in days)
            ok = sum(1 for d in by_day.values() if max(d, key=lambda x: x["ts"])["result"] == "SUCCESS")
            body.append(
                f'<tr><th class="job"><a href="{html.escape(_job_url(sample["url"]))}">'
                f"{html.escape(job)}</a></th>{cells}<td class=\"n\">{ok}/{len(by_day)} ok</td></tr>")
        out.append(
            f"<h3>{html.escape(title)}</h3><div class=\"scroll\"><table class=\"matrix\">"
            f"<tr><th></th>{head}<th></th></tr>{''.join(body)}</table></div>")
    return "".join(out)


def render(store: Store, out_dir: str) -> Path:
    since = int(time.time()) - WINDOW_DAYS * 86400
    rows = store.query(
        "SELECT ts, source, metric, labels, value FROM observation "
        "WHERE ts >= ? ORDER BY source, metric, labels, ts",
        [since],
    )
    series: dict[tuple, list[tuple[int, float]]] = defaultdict(list)
    for r in rows:
        series[(r["source"], r["metric"], r["labels"])].append((r["ts"], r["value"]))

    by_source: dict[str, list[str]] = defaultdict(list)
    for (source, metric, labels), pts in series.items():
        label = metric + (f" {json.loads(labels)}" if labels != "{}" else "")
        by_source[source].append(
            f"<tr><td>{html.escape(label)}</td><td>{_spark(pts)}</td>"
            f'<td class="v">{_fmt(pts[-1][1])}</td></tr>'
        )
    body = "".join(
        f"<h2>{html.escape(src)}</h2><table>{''.join(trs)}</table>"
        for src, trs in sorted(by_source.items())
    ) + render_matrix(store, time.time())
    body = body or "<p>No data yet.</p>"

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    page = out / "index.html"
    page.write_text(
        PAGE.format(updated=time.strftime("%Y-%m-%d %H:%M", time.gmtime()), days=WINDOW_DAYS, body=body)
    )
    return page
