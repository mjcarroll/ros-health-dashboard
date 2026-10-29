import html
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .store import Store

WINDOW_DAYS = 30
MATRIX_DAYS = 14
# A section whose jobs run on fewer than this share of recent calendar days (Lci/Kci run every
# few days) shows only the days that had builds, instead of a mostly empty grid.
DAILY_COVERAGE = 0.7

GLYPH = {"SUCCESS": "✓", "UNSTABLE": "!", "FAILURE": "✗", "RUNNING": "●", "ABORTED": "–", "NOT_BUILT": "–"}

# Tab order is importance order: ci.ros2.org first, then each distro's Xci view with its package
# status (Rolling first), then anything else that has data (rosdistro, ...).
CI_SERVER = "ci.ros2.org"
BUILD_SERVER = "build.ros2.org"
DISTROS = [  # (distro, build.ros2.org view, label)
    ("rolling", "Rci", "Rolling"),
    ("lyrical", "Lci", "Lyrical"),
    ("kilted", "Kci", "Kilted"),
    ("jazzy", "Jci", "Jazzy"),
    ("humble", "Hci", "Humble"),
]

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ROS 2 health</title>
<script>document.documentElement.classList.add('js')</script>
<style>
:root { --fg:#1a1a1a; --bg:#fff; --muted:#666; --line:#2563eb; --rule:#e5e5e5;
  --ok-bg:#dafbe1; --ok:#1a7f37; --warn-bg:#fff8c5; --warn:#9a6700; --bad-bg:#ffebe9; --bad:#cf222e;
  --off-bg:#eaeef2; --off:#57606a; --run-bg:#ddf4ff; --run:#0969da; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e8e8e8; --bg:#111; --muted:#999; --line:#60a5fa; --rule:#2a2a2a;
    --ok-bg:#12261e; --ok:#3fb950; --warn-bg:#272115; --warn:#d29922; --bad-bg:#2d1215; --bad:#f85149;
    --off-bg:#21262d; --off:#8b949e; --run-bg:#0c2d6b; --run:#58a6ff; }
}
body { font:15px system-ui,sans-serif; color:var(--fg); background:var(--bg); max-width:70rem; margin:2rem auto; padding:0 1rem; }
h1 { margin-bottom:.25rem; } h2 { margin-top:1.5rem; } h3 { margin-bottom:.4rem; }
table { border-collapse:collapse; }
td { padding:.4rem .5rem; border-bottom:1px solid var(--rule); }
td.v { text-align:right; font-variant-numeric:tabular-nums; }
svg { stroke:var(--line); fill:none; stroke-width:1.5; vertical-align:middle; }
.muted { color:var(--muted); font-size:.85em; }
.scroll { overflow-x:auto; }

.tabs { display:flex; gap:.25rem; overflow-x:auto; border-bottom:1px solid var(--rule); margin:1rem 0; }
.tabs a { padding:.5rem .8rem; text-decoration:none; color:var(--muted); border-bottom:2px solid transparent; white-space:nowrap; }
.tabs a[aria-selected=true] { color:var(--fg); border-bottom-color:var(--line); font-weight:600; }
.tabs a:hover { color:var(--fg); }
.badge { background:var(--bad-bg); color:var(--bad); padding:0 .4rem; border-radius:999px; font-size:.75em; margin-left:.4rem; }
.js .panel { display:none; } .js .panel.active { display:block; }
.panel > h2:first-child { margin-top:0; }

table.matrix { border-collapse:separate; border-spacing:2px; font-size:.85em; }
.matrix th { font-weight:500; color:var(--muted); padding:.1rem .2rem; text-align:center; white-space:nowrap; }
.matrix th.job { text-align:left; position:sticky; left:0; background:var(--bg); padding-right:.75rem; }
.matrix th.job a { color:var(--fg); text-decoration:none; }
.matrix th.job a:hover { text-decoration:underline; }
.matrix td { padding:0; border:0; }
a.c { display:block; min-width:2rem; text-align:center; padding:.2rem 0; border-radius:4px; text-decoration:none; font-weight:600; }
a.c sup { font-weight:400; font-size:.7em; }
.SUCCESS { background:var(--ok-bg); color:var(--ok); } .UNSTABLE { background:var(--warn-bg); color:var(--warn); }
.FAILURE { background:var(--bad-bg); color:var(--bad); } .RUNNING { background:var(--run-bg); color:var(--run); }
.ABORTED, .NOT_BUILT, .OTHER { background:var(--off-bg); color:var(--off); }
.legend span { margin-right:1rem; }
details { margin:.5rem 0 1rem; } summary { cursor:pointer; color:var(--muted); }
table.pkgs td { padding:.15rem .5rem; font-size:.85em; }
table.pkgs a { color:inherit; }
.tag { padding:.05rem .35rem; border-radius:4px; font-size:.85em; }
</style>
<h1>ROS 2 health</h1>
<p class="muted">Updated %UPDATED% UTC.</p>
<nav class="tabs" role="tablist">%TABS%</nav>
%PANELS%
<script>
function show() {
  var panels = [].slice.call(document.querySelectorAll('.panel'));
  var target = panels.filter(function (p) { return p.id === location.hash.slice(1); })[0] || panels[0];
  panels.forEach(function (p) { p.classList.toggle('active', p === target); });
  [].forEach.call(document.querySelectorAll('.tabs a'), function (a) {
    a.setAttribute('aria-selected', a.getAttribute('href') === '#' + target.id);
  });
}
addEventListener('hashchange', show);
show();
</script>
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


def _columns(jobs: dict[str, dict], now: float) -> tuple[list, bool]:
    """-> (days newest first, collapsed). Daily sections show the last MATRIX_DAYS calendar days;
    sparse ones show their last MATRIX_DAYS days that had any build."""
    today = datetime.fromtimestamp(now, timezone.utc).date()
    calendar = [today - timedelta(days=i) for i in range(MATRIX_DAYS)]
    ran = {d for by_day in jobs.values() for d in by_day}
    if sum(d in ran for d in calendar) / MATRIX_DAYS >= DAILY_COVERAGE:
        return calendar, False
    return sorted(ran, reverse=True)[:MATRIX_DAYS], True


def _matrix(jobs: dict[str, dict], now: float) -> tuple[str, int]:
    """-> (html, number of jobs whose most recent build failed)."""
    days, collapsed = _columns(jobs, now)
    head = "".join(f'<th title="{d:%Y-%m-%d}">{d:%m-%d}<br>{d:%a}</th>' for d in days)
    body, failing = [], 0
    for job, by_day in sorted(jobs.items()):
        everything = [b for day in by_day.values() for b in day]
        failing += max(everything, key=lambda b: b["ts"])["result"] == "FAILURE"
        cells = "".join(_cell(by_day[d]) if d in by_day else "<td></td>" for d in days)
        body.append(
            f'<tr><th class="job"><a href="{html.escape(_job_url(everything[0]["url"]))}">'
            f"{html.escape(job)}</a></th>{cells}</tr>")
    note = ('<p class="muted">These jobs do not run daily: only days with builds are shown.</p>'
            if collapsed else "")
    table = (f'{note}<div class="scroll"><table class="matrix"><tr><th></th>{head}</tr>'
             f'{"".join(body)}</table></div>')
    return table, failing


LEGEND = ('<p class="legend muted"><span>✓ success</span><span>! unstable (test failures)</span>'
          "<span>✗ failed</span><span>● running</span><span>– aborted</span>"
          "<span>days are UTC; cells link to the build in Jenkins</span></p>")


def _load_matrix_data(store: Store, now: float) -> dict[tuple, dict]:
    since = int(now) - WINDOW_DAYS * 86400
    sections: dict[tuple, dict] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in store.query(
        "SELECT server, grp, job, number, ts, result, duration_s, fail, total, url "
        "FROM build WHERE ts >= ? ORDER BY server, grp, job, ts", [since]):
        day = datetime.fromtimestamp(r["ts"], timezone.utc).date()
        sections[(r["server"], r["grp"])][r["job"]][day].append(r)
    return sections


def _repo_series(store: Store, since: int) -> dict[tuple, list[tuple[int, float]]]:
    out: dict[tuple, list[tuple[int, float]]] = defaultdict(list)
    for r in store.query(
        "SELECT ts, metric, labels, value FROM observation WHERE source = 'repo_status' "
        "AND ts >= ? ORDER BY ts", [since]):
        lab = json.loads(r["labels"])
        out[(lab["distro"], lab["column"], r["metric"])].append((r["ts"], r["value"]))
    return out


def _packages(distro: str, series: dict, failures: list[dict], now: float) -> str:
    cols = sorted({k[1] for k in series if k[0] == distro})
    rows = []
    for col in cols:
        unbuilt, failed, total = (series.get((distro, col, m), []) for m in
                                  ("pkgs_unbuilt", "pkgs_failed", "pkgs_total"))
        if not total:
            continue
        rows.append(
            f"<tr><td>{html.escape(col)}</td><td>{_spark(unbuilt)}</td>"
            f'<td class="v">{_fmt(unbuilt[-1][1])} / {_fmt(total[-1][1])} unbuilt</td>'
            f'<td class="v">{_fmt(failed[-1][1])} failing</td></tr>')
    if not rows:
        return ""
    items = []
    for f in sorted(failures, key=lambda f: (f["jenkins"] != "FAILURE", f["first_seen"])):
        cls = f["jenkins"] if f["jenkins"] in GLYPH else "OTHER"
        age = (now - f["first_seen"]) / 86400
        items.append(
            f'<tr><td><a href="{html.escape(f["url"])}">{html.escape(f["pkg"])}</a></td>'
            f'<td>{html.escape(f["col"])}</td>'
            f'<td><span class="tag {cls}">{html.escape(f["jenkins"] or "unknown")}</span></td>'
            f'<td class="muted">{f["state"]}</td><td class="v muted">{age:.0f}d</td></tr>')
    detail = (f"<details open><summary>{len(items)} unbuilt packages, red jobs first</summary>"
              f'<div class="scroll"><table class="pkgs">{"".join(items)}</table></div></details>'
              if items else "")
    return ("<h3>Package build status</h3>"
            '<p class="muted">From the repo.ros2.org status page. <b>Unbuilt</b>: no repo has the current '
            "version. <b>Failing</b>: the Jenkins job is red; the rest are mostly aborted behind a failing "
            "dependency, or disabled.</p>"
            f"<table>{''.join(rows)}</table>{detail}")


def _generic(rows: list[dict]) -> str:
    series: dict[tuple, list[tuple[int, float]]] = defaultdict(list)
    for r in rows:
        series[(r["metric"], r["labels"])].append((r["ts"], r["value"]))
    trs = []
    for (metric, labels), pts in series.items():
        label = metric + (f" {json.loads(labels)}" if labels != "{}" else "")
        trs.append(f"<tr><td>{html.escape(label)}</td><td>{_spark(pts)}</td>"
                   f'<td class="v">{_fmt(pts[-1][1])}</td></tr>')
    return f"<table>{''.join(trs)}</table>"


def _tab(slug: str, label: str, content: str, failing: int = 0) -> tuple[str, str]:
    badge = f'<span class="badge" title="jobs whose latest build failed">{failing} ✗</span>' if failing else ""
    link = f'<a role="tab" href="#{slug}">{html.escape(label)}{badge}</a>'
    return link, f'<section class="panel" id="{slug}"><h2>{html.escape(label)}</h2>{content}</section>'


def render(store: Store, out_dir: str) -> Path:
    now = time.time()
    matrices = _load_matrix_data(store, now)
    series = _repo_series(store, int(now) - WINDOW_DAYS * 86400)
    failures: dict[str, list[dict]] = defaultdict(list)
    for f in store.query(
        "SELECT distro, col, pkg, state, jenkins, version, url, first_seen FROM pkg_failure "
        "WHERE resolved IS NULL ORDER BY first_seen"):
        failures[f["distro"]].append(f)

    tabs: list[tuple[str, str]] = []

    jobs = matrices.pop((CI_SERVER, "nightly"), None)
    if jobs:
        table, failing = _matrix(jobs, now)
        tabs.append(_tab("ci", CI_SERVER, LEGEND + table, failing))

    for distro, view, label in DISTROS:
        jobs = matrices.pop((BUILD_SERVER, view), None)
        content, failing = "", 0
        if jobs:
            table, failing = _matrix(jobs, now)
            content += f"<h3>{view} nightly jobs on {BUILD_SERVER}</h3>" + LEGEND + table
        content += _packages(distro, series, failures.get(distro, []), now)
        if content:
            tabs.append(_tab(distro, f"{label} ({view})", content, failing))

    known = {d for d, _, _ in DISTROS}
    for distro in sorted({k[0] for k in series} - known):
        if content := _packages(distro, series, failures.get(distro, []), now):
            tabs.append(_tab(distro, distro, content))

    # Anything left: other Jenkins sections, then generic metric sources such as rosdistro.
    for (server, grp), jobs in sorted(matrices.items()):
        table, failing = _matrix(jobs, now)
        tabs.append(_tab(f"{server}-{grp}".replace(".", "-"), f"{server} {grp}", LEGEND + table, failing))
    by_source: dict[str, list[dict]] = defaultdict(list)
    for r in store.query(
        "SELECT ts, source, metric, labels, value FROM observation WHERE ts >= ? "
        "ORDER BY source, metric, labels, ts", [int(now) - WINDOW_DAYS * 86400]):
        if r["source"] != "repo_status":  # drawn per distro above
            by_source[r["source"]].append(r)
    for source, rows in sorted(by_source.items()):
        tabs.append(_tab(source, source, f'<p class="muted">Last {WINDOW_DAYS} days.</p>' + _generic(rows)))

    page = PAGE.replace("%UPDATED%", time.strftime("%Y-%m-%d %H:%M", time.gmtime())).replace(
        "%TABS%", "".join(t[0] for t in tabs)).replace(
        "%PANELS%", "".join(t[1] for t in tabs) or "<p>No data yet.</p>")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "index.html"
    path.write_text(page)
    return path
