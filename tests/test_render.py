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
