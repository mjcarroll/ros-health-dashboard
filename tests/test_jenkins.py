import time

from rhd.cli import unchanged_filtered
from rhd.collectors.jenkins import JenkinsCollector
from rhd.models import Build
from rhd.render import render
from rhd.store import SqliteStore


class StubClient:
    def __init__(self, responses):
        self.responses = responses

    def json(self, path):
        return self.responses.get(path.split("?")[0])


def build_json(number, result, age_days, fail=None, total=None):
    actions = [{}, {"failCount": fail, "skipCount": 1, "totalCount": total}] if total else [{}]
    return {
        "number": number,
        "result": result,
        "timestamp": int((time.time() - age_days * 86400) * 1000),
        "duration": 3_600_000,
        "url": f"https://ci.example/job/nightly_a/{number}/",
        "actions": actions,
    }


def collector(**kw):
    client = StubClient({
        "/api/json": {"jobs": [{"name": "nightly_a"}, {"name": "ci_linux"}]},
        "/job/nightly_a/api/json": {"builds": [
            build_json(3, None, 0.1),
            build_json(2, "UNSTABLE", 1, fail=5, total=100),
            build_json(1, "SUCCESS", 90),  # outside the retention window
        ]},
    })
    return JenkinsCollector(label="ci.example", base_url="x", user_env="U", token_env="T",
                            match="^nightly_", client=client, **kw)


def test_collect_filters_jobs_and_window():
    builds = collector().collect()
    assert [(b.job, b.number, b.result) for b in builds] == [
        ("nightly_a", 3, "RUNNING"), ("nightly_a", 2, "UNSTABLE")]
    assert (builds[1].fail, builds[1].total) == (5, 100)
    assert builds[0].total is None


def test_views_become_sections():
    client = StubClient({
        "/view/Rci/api/json": {"jobs": [{"name": "nightly_a"}]},
        "/job/nightly_a/api/json": {"builds": [build_json(1, "SUCCESS", 1)]},
    })
    c = JenkinsCollector(label="b", base_url="x", user_env="U", token_env="T",
                         views=["Rci"], match="nightly", client=client)
    assert [b.grp for b in c.collect()] == ["Rci"]


def test_unchanged_builds_are_not_rewritten(tmp_path):
    store = SqliteStore(str(tmp_path / "t.db"))
    builds = collector().collect()
    assert unchanged_filtered(store, builds) == builds
    store.write(0, builds)
    assert unchanged_filtered(store, builds) == []
    finished = Build(**{**builds[0].__dict__, "result": "SUCCESS"})
    assert unchanged_filtered(store, [finished]) == [finished]


def test_matrix_links_to_builds(tmp_path):
    store = SqliteStore(str(tmp_path / "t.db"))
    store.write(0, collector().collect())
    text = render(store, str(tmp_path / "site")).read_text()
    assert 'href="https://ci.example/job/nightly_a/2/"' in text
    assert 'href="https://ci.example/job/nightly_a/"' in text  # row label -> job page
    assert "UNSTABLE" in text and "5 failed / 100 tests" in text
