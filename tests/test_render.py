import re
import time

from rhd.models import Build, Observation
from rhd.render import render
from rhd.store import SqliteStore

NOW = int(time.time())
DAY = 86400


def b(server, grp, job, number, days_ago, result="SUCCESS"):
    return Build(server, grp, job, number, NOW - int(days_ago * DAY), result, 3600,
                 f"https://j/{server}/{job}/{number}/")


def page(tmp_path, builds, observations=()):
    store = SqliteStore(str(tmp_path / "t.db"))
    store.write(NOW, [*builds, *observations])
    return render(store, str(tmp_path / "site")).read_text()


def test_tab_order_is_importance_order(tmp_path):
    text = page(tmp_path,
                [b("build.ros2.org", "Kci", "k", 1, 1), b("build.ros2.org", "Rci", "r", 1, 1),
                 b("ci.ros2.org", "nightly", "n", 1, 1), b("build.ros2.org", "Lci", "l", 1, 1)],
                [Observation("rosdistro", "open_prs", 4)])
    labels = re.findall(r'<a role="tab" href="#[^"]+">([^<]+)', text)
    assert labels == ["ci.ros2.org", "Rolling (Rci)", "Lyrical (Lci)", "Kilted (Kci)", "rosdistro"]


def test_sparse_section_shows_only_days_with_builds(tmp_path):
    # Kci runs every third day; Rci runs daily.
    kci = [b("build.ros2.org", "Kci", "k", i, i * 3) for i in range(1, 6)]
    rci = [b("build.ros2.org", "Rci", "r", i, i - 1) for i in range(1, 15)]
    text = page(tmp_path, kci + rci)
    kilted = text[text.index('id="kilted"'):text.index("</section>", text.index('id="kilted"'))]
    rolling = text[text.index('id="rolling"'):text.index("</section>", text.index('id="rolling"'))]
    assert "only days with builds" in kilted
    assert kilted.count("<th title=") == 5  # one column per run day, not 14
    assert "only days with builds" not in rolling
    assert rolling.count("<th title=") == 14


def test_no_ok_ratio_column(tmp_path):
    assert " ok<" not in page(tmp_path, [b("ci.ros2.org", "nightly", "n", 1, 1)])


def test_failing_badge(tmp_path):
    text = page(tmp_path, [b("ci.ros2.org", "nightly", "n", 1, 0.1, "FAILURE")])
    assert '<span class="badge"' in text and "1 ✗" in text


def test_rosdistro_tiles_link_to_github_queries(tmp_path):
    obs = [Observation("rosdistro", m, v) for m, v in [
        ("open_prs", 4), ("open_prs_unreviewed", 2), ("merged_7d", 140), ("merged_30d", 680),
        ("days_since_last_merge", 0.05), ("open_pr_age_p50_days", 4.9)]]
    text = page(tmp_path, [], obs)
    assert 'href="https://github.com/ros/rosdistro/pulls?q=is%3Apr+is%3Aopen"' in text
    assert "is%3Apr+is%3Aopen+draft%3Afalse+review%3Anone+comments%3A0" in text  # unreviewed
    assert "is%3Apr+is%3Amerged+merged%3A%3E%3D" in text
    assert "since last merge" in text and "<span class=\"n\">1 h</span>" in text


def test_stale_rosdistro_tile_is_flagged(tmp_path):
    text = page(tmp_path, [], [Observation("rosdistro", "days_since_last_merge", 5)])
    assert 'class="tile bad"' in text


def test_package_list_starts_collapsed(tmp_path):
    from rhd.failures import reconcile
    from rhd.models import FailureSnapshot, PkgFailure

    store = SqliteStore(str(tmp_path / "t.db"))
    store.write(NOW, [Observation("repo_status", "pkgs_total", 3, {"distro": "rolling", "column": "R64"}),
                      Observation("repo_status", "pkgs_unbuilt", 1, {"distro": "rolling", "column": "R64"})])
    store.execute(reconcile(store, NOW, FailureSnapshot("rolling", [
        PkgFailure("rolling", "R64", "p", "missing", "http://j/p", "FAILURE")])))
    text = render(store, str(tmp_path / "site")).read_text()
    assert "1 unbuilt packages" in text and "<details open" not in text


def test_infra_failures_get_their_own_cell_and_do_not_count_as_failing(tmp_path):
    from rhd.models import BuildClass

    store = SqliteStore(str(tmp_path / "t.db"))
    builds = [b("ci.ros2.org", "nightly", "n", 1, 3, "SUCCESS"), b("ci.ros2.org", "nightly", "n", 2, 0.5, "FAILURE")]
    store.write(NOW, [*builds, BuildClass("ci.ros2.org", "n", 2, builds[1].ts, "infra", "agent lost")])
    text = render(store, str(tmp_path / "site")).read_text()
    assert 'class="c INFRA"' in text and "INFRA FAILURE (agent lost)" in text and "↯" in text
    assert '<span class="badge"' not in text           # not a real failure: no badge
    assert "1 failed build(s) in this view were infrastructure failures" in text


def test_infra_failure_does_not_break_or_extend_a_streak(tmp_path):
    from rhd.alerts import evaluate
    from rhd.models import BuildClass

    def alerts_for(results, infra_numbers):
        store = SqliteStore(str(tmp_path / f"{len(results)}{''.join(map(str, infra_numbers))}.db"))
        # results are oldest -> newest; build numbers 1..n
        builds = [b("ci.ros2.org", "nightly", "n", i, len(results) - i + 0.5, r) for i, r in enumerate(results, 1)]
        classes = [BuildClass("ci.ros2.org", "n", i, builds[i - 1].ts, "infra", "x") for i in infra_numbers]
        store.write(NOW, [*builds, *classes])
        return [a.title for a in evaluate(store, NOW) if "in a row" in a.title]

    # 3 failures, the middle one infra: a streak of 2 (infra neither extends nor breaks it)
    assert alerts_for(["FAILURE"] * 3, [2]) == ["n failed 2 builds in a row"]
    # a success after the failures ends the streak regardless of infra failures before it
    assert alerts_for(["FAILURE", "FAILURE", "SUCCESS"], []) == []
    # all-infra failures never alert
    assert alerts_for(["FAILURE"] * 4, [1, 2, 3, 4]) == []


def alerting_page(tmp_path, days_since_merge=5.0):
    obs = [Observation("rosdistro", "days_since_last_merge", days_since_merge)]
    builds = [b("ci.ros2.org", "nightly", "n", i, 5 - i, "FAILURE") for i in range(1, 5)]
    return page(tmp_path, builds, obs)


def test_alerts_live_in_a_sidebar_with_stable_keys(tmp_path):
    text = alerting_page(tmp_path)
    aside = text[text.index('<aside class="side" id="alerts">'):text.index("</aside>")]
    assert 'data-key="rosdistro:stopped"' in aside and 'data-sev="bad"' in aside
    assert 'data-key="streak:ci.ros2.org:n"' in aside      # not the title: it contains the changing count
    assert 'class="dismiss"' in aside and "Alerts (<span class=\"count\">2</span>)" in aside
    assert "none\" hidden" in aside                          # the 'no alerts' note is hidden while some fire
    # one list only: the old per-tab and top banners are gone
    assert text.count('<ul class="alerts">') == 1
    assert text.index("<main>") < text.index('id="alerts"') < text.index("</div>\n<script>")


def test_no_alerts_shows_the_all_clear(tmp_path):
    text = page(tmp_path, [b("ci.ros2.org", "nightly", "n", 1, 0.5)], [Observation("rosdistro", "days_since_last_merge", 0.1)])
    aside = text[text.index('<aside class="side"'):text.index("</aside>")]
    assert "No alerts firing." in aside and "none\" hidden" not in aside and "<li" not in aside


def test_dismissal_script_is_valid_javascript(tmp_path):
    import shutil
    import subprocess

    text = alerting_page(tmp_path)
    scripts = re.findall(r"<script>(.*?)</script>", text, re.S)
    assert any("rhd.dismissed" in s for s in scripts)
    node = shutil.which("node")
    if node:
        for i, src in enumerate(scripts):
            f = tmp_path / f"s{i}.js"
            f.write_text(src)
            assert subprocess.run([node, "--check", str(f)], capture_output=True).returncode == 0, src[:80]
