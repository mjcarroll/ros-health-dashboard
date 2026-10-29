import html
import json
import time
from collections import defaultdict
from pathlib import Path

from .store import Store

WINDOW_DAYS = 30

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
    ) or "<p>No data yet.</p>"

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    page = out / "index.html"
    page.write_text(
        PAGE.format(updated=time.strftime("%Y-%m-%d %H:%M", time.gmtime()), days=WINDOW_DAYS, body=body)
    )
    return page
