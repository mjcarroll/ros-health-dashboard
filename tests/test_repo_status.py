import time

from rhd.collectors.repo_status import RepoStatusCollector, parse
from rhd.failures import reconcile
from rhd.models import FailureSnapshot, Observation, PkgFailure
from rhd.render import render
from rhd.store import SqliteStore, statements

PAGE = """<html><head><script>
window.job_url_templates = [
  'https://build.example/view/Xsrc/job/Xsrc__{pkg}__source',
  'https://build.example/view/Xbin/job/Xbin__{pkg}__binary',
];</script></head><body><table><thead><tr>
<th class="sortable"><div>Name</div></th><th class="sortable"><div>Repo</div></th>
<th class="sortable"><div>Version</div></th><th class="sortable"><div>Status</div></th>
<th class="sortable"><div>Maintainer</div></th>
<th><div title="Ubuntu source">Xsource</div><span class="sum">3</span><span class="sum">3</span><span class="sum">0</span></th>
<th><div title="Ubuntu amd64">X64</div><span class="sum">1</span><span class="sum">1</span><span class="sum">0</span></th>
</tr></thead><tbody >
%s
</tbody></table></body></html>"""


def row(pkg, src, binary):
    cells = lambda c: "<td>" + "".join(f'<a class="{x}">v</a>' if x else '<a class=""/>' for x in c) + "</td>"
    return (f'<tr><td><div><a href="https://index/{pkg}">{pkg}</a></div></td><td><div>r</div></td>'
            f'<td><span>1.0-1</span></td><td><span class="maintained"/></td><td class="main"><div>m</div></td>'
            f"{cells(src)}{cells(binary)}</tr>")


ROWS = "\n".join([
    row("ok_pkg", "eem", "eem"),
    row("failed_pkg", "eem", "mmm"),      # red job
    row("aborted_pkg", "eem", "lmm"),     # stale, aborted job
    row("synced_pkg", "eem", "mem"),      # gone from building but current in testing: fine
    row("skipped_pkg", "eem", "iii"),     # intentionally missing: ignored
])


class Client:
    def json(self, path):
        assert path.startswith("/view/Xbin/") or path.startswith("/view/Xsrc/")
        return {"jobs": [
            {"name": "Xbin__failed_pkg__binary", "color": "red"},
            {"name": "Xbin__aborted_pkg__binary", "color": "aborted"},
            {"name": "Xbin__ok_pkg__binary", "color": "blue"},
        ]}


def collector():
    return RepoStatusCollector("x", base_url="u", client=Client(), page_fetch=lambda url: PAGE % ROWS)


def test_parse():
    columns, templates, packages = parse(PAGE % ROWS)
    assert columns == [("Xsource", "Ubuntu source"), ("X64", "Ubuntu amd64")]
    assert len(templates) == 2 and len(packages) == 5
    assert packages[1]["cells"] == [["e", "e", "m"], ["m", "m", "m"]]


def test_collect_counts_and_failures():
    records = collector().collect()
    metrics = {(o.labels["column"], o.metric): o.value for o in records if isinstance(o, Observation)}
    assert metrics[("X64", "pkgs_total")] == 4  # the intentionally-missing package is excluded
    assert metrics[("X64", "pkgs_unbuilt")] == 2
    assert metrics[("X64", "pkgs_failed")] == 1
    assert metrics[("Xsource", "pkgs_unbuilt")] == 0
    snap = next(r for r in records if isinstance(r, FailureSnapshot))
    by_pkg = {f.pkg: f for f in snap.failures}
    assert by_pkg["failed_pkg"].jenkins == "FAILURE" and by_pkg["failed_pkg"].state == "missing"
    assert by_pkg["aborted_pkg"].jenkins == "ABORTED" and by_pkg["aborted_pkg"].state == "stale"
    assert by_pkg["failed_pkg"].url == "https://build.example/view/Xbin/job/Xbin__failed_pkg__binary"


def test_reconcile_tracks_open_and_resolved(tmp_path):
    store = SqliteStore(str(tmp_path / "t.db"))
    f = lambda pkg, j="FAILURE": PkgFailure("x", "X64", pkg, "missing", f"http://j/{pkg}", j, "1.0")

    store.execute(reconcile(store, 100, FailureSnapshot("x", [f("a"), f("b")])))
    assert reconcile(store, 200, FailureSnapshot("x", [f("a"), f("b")])) == []  # steady state: no writes

    store.execute(reconcile(store, 300, FailureSnapshot("x", [f("a", "ABORTED")])))
    rows = {r["pkg"]: r for r in store.query("SELECT * FROM pkg_failure")}
    assert rows["a"]["jenkins"] == "ABORTED" and rows["a"]["first_seen"] == 100 and rows["a"]["resolved"] is None
    assert rows["b"]["resolved"] == 300

    store.execute(reconcile(store, 400, FailureSnapshot("x", [f("b")])))  # b fails again: new row
    assert len(store.query("SELECT * FROM pkg_failure WHERE pkg = 'b'")) == 2
    # other distros are untouched
    assert reconcile(store, 500, FailureSnapshot("y", [])) == []


def test_render_package_section(tmp_path):
    store = SqliteStore(str(tmp_path / "t.db"))
    now = int(time.time())
    for ts in (now - 3600, now):
        store.write(ts, [r for r in collector().collect() if isinstance(r, Observation)])
    store.execute(reconcile(store, now - 86400, FailureSnapshot("x", collector().collect()[-1].failures)))
    text = render(store, str(tmp_path / "site")).read_text()
    assert "Package build status" in text
    assert 'href="https://build.example/view/Xbin/job/Xbin__failed_pkg__binary"' in text
    assert "2 unbuilt packages" in text and "1 failing" in text
