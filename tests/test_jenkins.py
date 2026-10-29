import time

from rhd.cli import unchanged_filtered
from rhd.collectors.jenkins import JenkinsCollector
from rhd.models import Build, BuildClass
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


def test_empty_job_list_is_an_error():
    import pytest

    client = StubClient({"/api/json": {"jobs": []}})
    c = JenkinsCollector(label="ci.example", base_url="x", user_env="U", token_env="T",
                         match="^nightly_", client=client)
    with pytest.raises(RuntimeError, match="no jobs matched"):
        c.collect()


# ---- infrastructure vs. real failures (stubs only: no Jenkins calls) ----

class ConsoleClient(StubClient):
    def __init__(self, responses, tails):
        super().__init__(responses)
        self.tails, self.calls = tails, []

    def console_tail(self, job, number, nbytes=12000):
        self.calls.append(number)
        return self.tails.get(number)


def failing_job_client(tails):
    def b(number, executing=None, age=0.1):
        actions = [{"executingTimeMillis": executing}] if executing is not None else []
        return {**build_json(number, "FAILURE", age), "actions": actions}
    return ConsoleClient({
        "/api/json": {"jobs": [{"name": "nightly_a"}]},
        "/job/nightly_a/api/json": {"builds": [b(5), b(4), b(3), b(2, executing=0), b(1, executing=5000)]},
    }, tails)


def classes(records):
    from rhd.models import BuildClass
    return {c.number: (c.kind, c.reason) for c in records if isinstance(c, BuildClass)}


def test_console_patterns_classify_failures():
    client = failing_job_client({
        5: "...at hudson.tasks.MailSender.run\nCaused by: java.net.ConnectException: Connection refused",
        4: "colcon test failed: 3 tests failed",
        3: None,  # console size unavailable: never download the whole log
    })
    c = JenkinsCollector(label="ci.example", base_url="x", user_env="U", token_env="T", match="^nightly_",
                         classify_console=True, client=client)
    got = classes(c.collect())
    assert got[5] == ("infra", "mail server unreachable")
    assert got[4] == ("code", "")
    assert got[3][0] == "unknown"
    assert got[2] == ("infra", "agent lost (no executor time)")  # from the JSON, no console needed
    assert 2 not in client.calls   # already classified from the JSON: no console fetch
    assert 1 in client.calls and got[1][0] == "unknown"  # real executor time: console is checked


def test_classification_is_bounded_and_not_repeated(tmp_path):
    client = failing_job_client({n: "build failed" for n in (3, 4, 5)})
    c = JenkinsCollector(label="ci.example", base_url="x", user_env="U", token_env="T", match="^nightly_",
                         classify_console=True, max_classify=2, client=client)
    c.collect()
    assert len(client.calls) == 2 and client.calls == [5, 4]  # newest first, capped

    store = SqliteStore(str(tmp_path / "t.db"))
    store.write(0, [x for x in c.collect() if isinstance(x, BuildClass)])
    again = JenkinsCollector(label="ci.example", base_url="x", user_env="U", token_env="T", match="^nightly_",
                             classify_console=True, client=failing_job_client({}))
    again.bind(store)
    assert {(k[1], k[2]) for k in again.classified} >= {("nightly_a", 5), ("nightly_a", 4)}


def test_custom_patterns_extend_the_defaults():
    client = failing_job_client({5: "license server timed out", 4: "x", 3: "x"})
    c = JenkinsCollector(label="ci.example", base_url="x", user_env="U", token_env="T", match="^nightly_",
                         classify_console=True, infra_patterns=["license server"], client=client)
    assert classes(c.collect())[5][0] == "infra"


def test_failing_tests_section_starts_collapsed(tmp_path):
    from rhd.models import TestFailures

    store = SqliteStore(str(tmp_path / "t.db"))
    now = int(time.time())
    build = Build("ci.ros2.org", "nightly", "nightly_a", 7, now - 3600, "UNSTABLE", 3600,
                  "https://ci.ros2.org/job/nightly_a/7/", fail=1, skip=0, total=10)
    store.write(0, [build, TestFailures(build.server, build.job, build.number, build.ts,
                                        [("pkg.TestA", "does_a_thing", 1, 7)])])
    text = render(store, str(tmp_path / "site")).read_text()
    assert "1 tests failed in the last 14 days: 0 failing, 1 new, 0 flaky" in text
    section = text[text.index("Failing tests"):]
    assert section.startswith("Failing tests</h3><details><summary>") and "<details open" not in text
    assert "pkg.TestA" in section and "does_a_thing" in section
