import html
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import re
import urllib.parse

from .alerts import Thresholds, evaluate
from .layout import BUILD_SERVER, CI_SERVER, DISTROS
from .store import Store

WINDOW_DAYS = 30
MATRIX_DAYS = 14
STATUS_PAGE_STALE_HOURS = 6  # the buildfarm normally regenerates these every hour or so
# A section whose jobs run on fewer than this share of recent calendar days (Lci/Kci run every
# few days) shows only the days that had builds, instead of a mostly empty grid.
DAILY_COVERAGE = 0.7

GLYPH = {"SUCCESS": "✓", "UNSTABLE": "!", "FAILURE": "✗", "RUNNING": "●", "ABORTED": "–", "NOT_BUILT": "–",
         "INFRA": "↯"}

PAGE = """<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ROS 2 health</title>
<script>document.documentElement.classList.add('js')</script>
<style>
:root { --fg:#1a1a1a; --bg:#fff; --muted:#666; --line:#2563eb; --rule:#e5e5e5;
  --ok-bg:#dafbe1; --ok:#1a7f37; --warn-bg:#fff8c5; --warn:#9a6700; --bad-bg:#ffebe9; --bad:#cf222e;
  --off-bg:#eaeef2; --off:#57606a; --run-bg:#ddf4ff; --run:#0969da; --infra-bg:#f3e8ff; --infra:#8250df; }
@media (prefers-color-scheme: dark) {
  :root { --fg:#e8e8e8; --bg:#111; --muted:#999; --line:#60a5fa; --rule:#2a2a2a;
    --ok-bg:#12261e; --ok:#3fb950; --warn-bg:#272115; --warn:#d29922; --bad-bg:#2d1215; --bad:#f85149;
    --off-bg:#21262d; --off:#8b949e; --run-bg:#0c2d6b; --run:#58a6ff; --infra-bg:#261a3a; --infra:#a371f7; }
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
.INFRA { background:var(--infra-bg); color:var(--infra); }
.legend span { margin-right:1rem; }
details { margin:.5rem 0 1rem; } summary { cursor:pointer; color:var(--muted); }
table.pkgs td { padding:.15rem .5rem; font-size:.85em; }
table.pkgs a { color:inherit; }
.tag { padding:.05rem .35rem; border-radius:4px; font-size:.85em; }
.alerts { margin:1rem 0; padding:0; list-style:none; }
.alerts li { padding:.35rem .6rem; margin:.25rem 0; border-radius:4px; }
.alerts li.bad { background:var(--bad-bg); color:var(--bad); } .alerts li.warn { background:var(--warn-bg); color:var(--warn); }
.alerts a { color:inherit; } .alerts .muted { color:inherit; opacity:.8; }
.ok-note { background:var(--ok-bg); color:var(--ok); padding:.35rem .6rem; border-radius:4px; }
table.tests td { font-size:.85em; padding:.2rem .5rem; vertical-align:top; }
table.tests td.t { word-break:break-word; max-width:34rem; }
.new { background:var(--warn-bg); color:var(--warn); } .failing { background:var(--bad-bg); color:var(--bad); }
.flaky { background:var(--off-bg); color:var(--off); }
.tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(11rem,1fr)); gap:.75rem; margin:1rem 0; }
a.tile { display:flex; flex-direction:column; gap:.1rem; padding:.75rem .9rem; border:1px solid var(--rule); border-radius:8px;
  text-decoration:none; color:var(--fg); }
a.tile:hover { border-color:var(--line); }
a.tile .n { font-size:1.9rem; font-weight:600; font-variant-numeric:tabular-nums; line-height:1.1; }
a.tile .l { color:var(--muted); font-size:.85em; }
a.tile svg { margin-top:.35rem; width:100%; height:28px; }
a.tile.warn { background:var(--warn-bg); border-color:var(--warn); } a.tile.warn .n { color:var(--warn); }
a.tile.bad { background:var(--bad-bg); border-color:var(--bad); } a.tile.bad .n { color:var(--bad); }
table.facts { width:100%; max-width:34rem; } table.facts td:first-child { color:var(--muted); }
table.facts a { color:var(--fg); }
</style>
<h1>ROS 2 health</h1>
<p class="muted">Updated %UPDATED% UTC.</p>
%ALERTS%
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
    infra = b["result"] == "FAILURE" and b.get("kind") == "infra"
    cls = "INFRA" if infra else b["result"] if b["result"] in GLYPH else "OTHER"
    tests = ""
    if b["total"] is not None:
        tests = f" · {b['fail']} failed / {b['total']} tests"
    title = f"{'INFRA FAILURE (' + (b.get('reason') or 'infrastructure') + ')' if infra else b['result']} " \
            f"#{b['number']}{tests} · {_duration(b['duration_s'])}"
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
    body, failing, infra_count = [], 0, 0
    for job, by_day in sorted(jobs.items()):
        everything = [b for day in by_day.values() for b in day]
        real = [b for b in everything if b.get("kind") != "infra"] or everything
        failing += max(real, key=lambda b: b["ts"])["result"] == "FAILURE"
        infra_count += sum(1 for b in everything if b["result"] == "FAILURE" and b.get("kind") == "infra")
        cells = "".join(_cell(by_day[d]) if d in by_day else "<td></td>" for d in days)
        body.append(
            f'<tr><th class="job"><a href="{html.escape(_job_url(everything[0]["url"]))}">'
            f"{html.escape(job)}</a></th>{cells}</tr>")
    note = ('<p class="muted">These jobs do not run daily: only days with builds are shown.</p>'
            if collapsed else "")
    if infra_count:
        note += (f'<p class="muted">{infra_count} failed build(s) in this view were infrastructure failures '
                 "(shown as ↯) and are excluded from failure streaks and the tab badge.</p>")
    table = (f'{note}<div class="scroll"><table class="matrix"><tr><th></th>{head}</tr>'
             f'{"".join(body)}</table></div>')
    return table, failing


LEGEND = ('<p class="legend muted"><span>✓ success</span><span>! unstable (test failures)</span>'
          "<span>✗ failed</span><span>↯ infrastructure failure</span><span>● running</span><span>– aborted</span>"
          "<span>days are UTC; cells link to the build in Jenkins</span></p>")


def _load_matrix_data(store: Store, now: float) -> dict[tuple, dict]:
    since = int(now) - WINDOW_DAYS * 86400
    sections: dict[tuple, dict] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for r in store.query(
        "SELECT b.server, b.grp, b.job, b.number, b.ts, b.result, b.duration_s, b.fail, b.total, b.url, "
        "c.kind, c.reason FROM build b LEFT JOIN build_class c USING (server, job, number) "
        "WHERE b.ts >= ? ORDER BY b.server, b.grp, b.job, b.ts", [since]):
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


def _page_age(distro: str, series: dict, now: float) -> str:
    pts = series.get((distro, "", "page_generated_ts"))
    if not pts:
        return ""
    generated = pts[-1][1]
    age_days = (now - generated) / 86400
    stamp = datetime.fromtimestamp(generated, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    late = ' <span class="tag UNSTABLE">stale</span>' if age_days > STATUS_PAGE_STALE_HOURS / 24 else ""
    return (f'<p class="muted">Status page last generated <b>{stamp}</b> ({_dur(age_days)} ago){late}. '
            "Package data below is as of then.</p>")


def _packages(distro: str, series: dict, failures: list[dict], now: float) -> str:
    cols = sorted({k[1] for k in series if k[0] == distro} - {""})
    rows = []
    for col in cols:
        unbuilt, failed, total = (series.get((distro, col, m), []) for m in
                                  ("pkgs_unbuilt", "pkgs_failed", "pkgs_total"))
        if not total:
            continue
        rows.append(
            f"<tr><td>{html.escape(col)}</td><td>{_spark(unbuilt)}</td>"
            f'<td class="v">{_fmt(unbuilt[-1][1] if unbuilt else 0)} / {_fmt(total[-1][1])} unbuilt</td>'
            f'<td class="v">{_fmt(failed[-1][1] if failed else 0)} failing</td></tr>')
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
    detail = (f"<details><summary>{len(items)} unbuilt packages, red jobs first</summary>"
              f'<div class="scroll"><table class="pkgs">{"".join(items)}</table></div></details>'
              if items else "")
    return ("<h3>Package build status</h3>" + _page_age(distro, series, now) +
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


def _alert_list(alerts, link_tab: bool) -> str:
    if not alerts:
        return ""
    items = []
    for a in alerts:
        title = html.escape(a.title)
        if a.url:
            title = f'<a href="{html.escape(a.url)}">{title}</a>'
        where = f' <a class="muted" href="#{a.tab}">[{html.escape(a.tab)}]</a>' if link_tab else ""
        detail = f' <span class="muted">{html.escape(a.detail)}</span>' if a.detail else ""
        items.append(f'<li class="{a.severity}"><b>{a.severity.upper()}</b> {title}{detail}{where}</li>')
    return f'<ul class="alerts">{"".join(items)}</ul>'


def _test_url(build_url: str, cls: str, name: str) -> str:
    """Deep link to a test in a build's JUnit report; Jenkins rewrites odd characters to '_'."""
    pkg, _, leaf = cls.rpartition(".")
    safe = lambda x: re.sub(r"[^\w.\-]", "_", x)
    return f"{build_url}testReport/{safe(pkg) if pkg else '(root)'}/{safe(leaf or cls)}/{safe(name)}/"


def _tests(store: Store, server: str, now: float, limit: int = 60) -> str:
    since = int(now) - MATRIX_DAYS * 86400
    fails = store.query(
        "SELECT job, number, ts, class, name, age FROM test_failure WHERE server = ? AND ts >= ?", [server, since])
    fetched = store.query("SELECT job, number FROM test_fetch WHERE server = ? AND ts >= ?", [server, since])
    if not fetched:
        return ""
    urls = {(r["job"], r["number"]): r["url"] for r in store.query(
        "SELECT job, number, url FROM build WHERE server = ? AND ts >= ?", [server, since])}
    per_job: dict[str, list[int]] = defaultdict(list)
    for r in fetched:
        per_job[r["job"]].append(r["number"])
    latest = {job: max(nums) for job, nums in per_job.items()}

    tests: dict[tuple, dict] = {}
    for r in fails:
        t = tests.setdefault((r["class"], r["name"]), {"jobs": {}, "last_ts": 0})
        j = t["jobs"].setdefault(r["job"], {"builds": 0, "last": 0, "age": 0})
        j["builds"] += 1
        if r["number"] > j["last"]:
            j["last"], j["age"] = r["number"], r["age"] or 1
        t["last_ts"] = max(t["last_ts"], r["ts"])

    rows = []
    for (cls, name), t in tests.items():
        current = {job: j for job, j in t["jobs"].items() if j["last"] == latest.get(job)}
        age = max((j["age"] for j in current.values()), default=0)
        kind = "flaky" if not current else "new" if age <= 1 else "failing"
        t.update(current=current, age=age, kind=kind)
        rows.append(((cls, name), t))
    order = {"failing": 0, "new": 1, "flaky": 2}
    rows.sort(key=lambda kv: (order[kv[1]["kind"]], -len(kv[1]["current"]), -kv[1]["age"],
                              -sum(j["builds"] for j in kv[1]["jobs"].values())))

    trs = []
    for (cls, name), t in rows[:limit]:
        links = []
        for job, j in sorted(t["jobs"].items(), key=lambda kv: (kv[0] not in t["current"], kv[0])):
            url = urls.get((job, j["last"]))
            if url:
                links.append(f'<a href="{html.escape(_test_url(url, cls, name))}">{html.escape(job)}</a>'
                             f" #{j['last']}" + ("" if job in t["current"] else ' <span class="muted">(earlier)</span>'))
        runs = sum(j["builds"] for j in t["jobs"].values())
        of = sum(len(per_job[job]) for job in t["jobs"])
        trs.append(
            f'<tr><td class="t">{html.escape(cls)}<br><b>{html.escape(name)}</b></td>'
            f'<td><span class="tag {t["kind"]}">{t["kind"]}</span></td>'
            f"<td>{'<br>'.join(links)}</td>"
            f'<td class="v">{runs}/{of} builds</td>'
            f'<td class="v">{t["age"] or ""}</td>'
            f'<td class="v muted">{(now - t["last_ts"]) / 86400:.0f}d ago</td></tr>')
    head = ("<tr><td>Test</td><td></td><td>Jobs (latest failing build)</td><td>Failed in</td>"
            "<td>Streak</td><td>Last failed</td></tr>")
    note = (f'<p class="muted">Tests that failed in the last {MATRIX_DAYS} days. <b>failing</b>: failing in the latest '
            "build of a job for 2+ builds; <b>new</b>: started failing in the latest build; <b>flaky</b>: failed "
            "earlier but passed in the latest build. Streak = consecutive failing builds. "
            f"{len(rows)} distinct tests{', showing ' + str(limit) if len(rows) > limit else ''}.</p>")
    body = f'<div class="scroll"><table class="tests">{head}{"".join(trs)}</table></div>' if trs else \
        '<p class="ok-note">No failing tests in the fetched builds.</p>'
    return f"<h3>Failing tests</h3>{note}{body}"


ROSDISTRO_REPO = "ros/rosdistro"


def _gh(query: str) -> str:
    return f"https://github.com/{ROSDISTRO_REPO}/pulls?q=" + urllib.parse.quote_plus(query)


def _dur(days: float) -> str:
    if days < 1 / 24:
        return f"{days * 1440:.0f} min"
    if days < 1:
        return f"{days * 24:.0f} h"
    return f"{days:.1f} d" if days < 10 else f"{days:.0f} d"


def _rosdistro(rows: list[dict], now: float, t: Thresholds) -> str:
    series: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for r in rows:
        series[r["metric"]].append((r["ts"], r["value"]))
    latest = {m: pts[-1][1] for m, pts in series.items()}
    day = lambda n: (datetime.fromtimestamp(now, timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")
    open_q = "is:pr is:open"
    oldest_q = "is:pr is:open sort:created-asc"

    days = latest.get("days_since_last_merge")
    stale = ("bad" if days >= t.rosdistro_days_since_merge_bad else
             "warn" if days >= t.rosdistro_days_since_merge_warn else "") if days is not None else ""
    tiles = [  # (metric, label, text, query, severity)
        ("open_prs", "open PRs", None, open_q, ""),
        ("open_prs_unreviewed", "open, no review or comment", None,
         "is:pr is:open draft:false review:none comments:0", ""),
        ("merged_7d", "merged in 7 days", None, f"is:pr is:merged merged:>={day(7)}", ""),
        ("merged_30d", "merged in 30 days", None, f"is:pr is:merged merged:>={day(30)}", ""),
        ("days_since_last_merge", "since last merge", _dur, "is:pr is:merged sort:updated-desc", stale),
    ]
    out = []
    for metric, label, fmt, query, sev in tiles:
        if metric not in latest:
            continue
        value = fmt(latest[metric]) if fmt else _fmt(latest[metric])
        out.append(f'<a class="tile {sev}" href="{html.escape(_gh(query))}"><span class="n">{value}</span>'
                   f'<span class="l">{label}</span>{_spark(series[metric], 200)}</a>')

    facts = []
    for metric, label, query in [
        ("open_pr_age_p50_days", "Median open PR age", oldest_q),
        ("open_pr_age_p90_days", "90th percentile open PR age", oldest_q),
        ("open_pr_age_max_days", "Oldest open PR", oldest_q),
        ("time_to_merge_p50_days", "Median time to merge (last 30 days)", f"is:pr is:merged merged:>={day(30)}"),
    ]:
        if metric in latest:
            facts.append(f"<tr><td>{label}</td><td class=\"v\"><a href=\"{html.escape(_gh(query))}\">"
                         f"{_dur(latest[metric])}</a></td></tr>")
    return (f'<div class="tiles">{"".join(out)}</div>'
            f'<table class="facts">{"".join(facts)}</table>'
            f'<p class="muted">Tiles and values link to the matching search on github.com/{ROSDISTRO_REPO}. '
            f"Trend lines cover the last {WINDOW_DAYS} days.</p>")


def _tab(slug: str, label: str, content: str, failing: int = 0) -> tuple[str, str]:
    badge = f'<span class="badge" title="jobs whose latest build failed">{failing} ✗</span>' if failing else ""
    link = f'<a role="tab" href="#{slug}">{html.escape(label)}{badge}</a>'
    return link, f'<section class="panel" id="{slug}"><h2>{html.escape(label)}</h2>{content}</section>'


def render(store: Store, out_dir: str, thresholds: Thresholds | None = None) -> Path:
    now = time.time()
    thresholds = thresholds or Thresholds()
    alerts = evaluate(store, now, thresholds)
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
        tabs.append(_tab("ci", CI_SERVER, _alert_list([a for a in alerts if a.tab == "ci"], False)
                         + LEGEND + table + _tests(store, CI_SERVER, now), failing))

    for distro, view, label in DISTROS:
        jobs = matrices.pop((BUILD_SERVER, view), None)
        content, failing = "", 0
        if jobs:
            table, failing = _matrix(jobs, now)
            content += f"<h3>{view} nightly jobs on {BUILD_SERVER}</h3>" + LEGEND + table
        content += _packages(distro, series, failures.get(distro, []), now)
        content = _alert_list([a for a in alerts if a.tab == distro], False) + content if content else content
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
        body = (_rosdistro(rows, now, thresholds) if source == "rosdistro"
                else f'<p class="muted">Last {WINDOW_DAYS} days.</p>' + _generic(rows))
        tabs.append(_tab(source, source, _alert_list([a for a in alerts if a.tab == source], False) + body))

    page = PAGE.replace("%UPDATED%", time.strftime("%Y-%m-%d %H:%M", time.gmtime())).replace(
        "%TABS%", "".join(t[0] for t in tabs)).replace(
        "%PANELS%", "".join(t[1] for t in tabs) or "<p>No data yet.</p>").replace(
        "%ALERTS%", _alert_list(alerts, True) or '<p class="ok-note">No alerts firing.</p>')
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "index.html"
    path.write_text(page)
    return path
