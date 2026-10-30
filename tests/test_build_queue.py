import time

from rhd.collectors.build_queue import BuildQueueCollector
from rhd.render import render
from rhd.store import SqliteStore

NOW = 1_800_000_000.0


class Client:
    def json(self, path):
        assert path.startswith("/queue/api/json")
        ms = lambda age_s: (NOW - age_s) * 1000
        return {"items": [
            {"task": {"name": "Rbin_uR64__rclcpp__ubuntu_resolute_amd64__binary"}, "inQueueSince": ms(600),
             "buildable": True, "blocked": False},
            {"task": {"name": "Rbin_uR64__rclcpp_action__ubuntu_resolute_amd64__binary"},
             "inQueueSince": ms(3600), "buildable": False, "blocked": True},
            {"task": {"name": "Rrel_sync-packages-to-testing_resolute_amd64"}, "inQueueSince": ms(60),
             "buildable": False, "blocked": False},
            {"task": {"name": "Lci__nightly-release_ubuntu_resolute_amd64"}, "inQueueSince": ms(120),
             "buildable": True, "blocked": False},
            {"task": {"name": "some_unrelated_job"}, "inQueueSince": ms(9999), "buildable": True},
        ]}


def metrics():
    obs = BuildQueueCollector(client=Client(), clock=lambda: NOW).collect()
    return {(o.labels["distro"], o.metric): o.value for o in obs}


def test_counts_per_distro():
    m = metrics()
    assert (m[("rolling", "queue_total")], m[("rolling", "queue_buildable")],
            m[("rolling", "queue_blocked")], m[("rolling", "queue_oldest_s")]) == (3, 1, 1, 3600)
    assert m[("lyrical", "queue_total")] == 1 and m[("lyrical", "queue_oldest_s")] == 120
    # distros with nothing queued still report 0, and unattributable jobs are ignored
    assert m[("humble", "queue_total")] == 0 and m[("humble", "queue_oldest_s")] == 0
    assert {d for d, _ in m} == {"rolling", "lyrical", "kilted", "jazzy", "humble"}


def test_render_queue_section_in_distro_tab(tmp_path):
    store = SqliteStore(str(tmp_path / "t.db"))
    now = int(time.time())
    obs = BuildQueueCollector(client=Client(), clock=lambda: NOW).collect()
    for ts in (now - 3600, now):
        store.write(ts, obs)
    text = render(store, str(tmp_path / "site")).read_text()
    assert "Build queue" in text and "blocked on upstream" in text and "oldest wait" in text and "1 h" in text
    assert text.count("<svg") >= 4  # one sparkline per queue metric
    assert 'href="#build_queue"' not in text  # not duplicated as a generic tab
    assert 'id="rolling"' in text
