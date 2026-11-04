"""A source being down (build.ros2.org returning 500s) must not stop the run."""

import io
import urllib.error

import pytest

from rhd import cli, jenkins
from rhd.alerts import evaluate
from rhd.models import Observation
from rhd.store import SqliteStore


@pytest.fixture(autouse=True)
def fresh_hosts(monkeypatch):
    monkeypatch.setattr(jenkins, "_down", {})
    monkeypatch.setattr(jenkins.time, "sleep", lambda s: None)
    monkeypatch.setenv("U", "u")
    monkeypatch.setenv("T", "t")


def test_down_host_fails_fast_for_every_later_client(monkeypatch):
    calls = []

    def urlopen(req, timeout):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 500, "Internal Server Error", {}, io.BytesIO())

    monkeypatch.setattr(jenkins.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.HTTPError):
        jenkins.Jenkins("https://build.example", "U", "T").json("/api/json")
    assert len(calls) == jenkins.MAX_ATTEMPTS
    with pytest.raises(jenkins.HostDown):
        jenkins.Jenkins("https://build.example/", "U", "T").json("/queue/api/json")
    assert len(calls) == jenkins.MAX_ATTEMPTS  # no further requests to the down host


def test_connection_errors_also_mark_the_host_down(monkeypatch):
    def urlopen(req, timeout):
        raise urllib.error.URLError("Name or service not known")

    monkeypatch.setattr(jenkins.urllib.request, "urlopen", urlopen)
    with pytest.raises(urllib.error.URLError):
        jenkins.Jenkins("https://build.example", "U", "T").json("/api/json")
    with pytest.raises(jenkins.HostDown, match="Name or service not known"):
        jenkins.Jenkins("https://build.example", "U", "T").json("/api/json")


def test_404_does_not_mark_the_host_down(monkeypatch):
    def urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO())

    monkeypatch.setattr(jenkins.urllib.request, "urlopen", urlopen)
    assert jenkins.Jenkins("https://build.example", "U", "T").json("/job/x/api/json") is None
    assert jenkins._down == {}


class Ok:
    name = "ok"

    def collect(self):
        return [Observation("rosdistro", "open_prs", 3)]


class Broken:
    name = "jenkins:build.ros2.org"

    def collect(self):
        raise RuntimeError("HTTP Error 500: Internal Server Error")


def run(monkeypatch, tmp_path, collectors):
    monkeypatch.setattr(cli, "build_collectors", lambda entries: collectors)
    monkeypatch.setattr(cli, "load_config", lambda path: {"collectors": [{"type": "x"}]})
    db = str(tmp_path / "t.db")
    return cli.collect("unused", db), SqliteStore(db)


def test_partial_failure_still_succeeds_and_records_the_rest(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    code, store = run(monkeypatch, tmp_path, [Broken(), Ok()])
    assert code == 0
    assert store.query("SELECT value FROM observation WHERE metric = 'open_prs'")[0]["value"] == 3
    status = {r["c"]: r["value"] for r in store.query(
        "SELECT json_extract(labels, '$.collector') c, value FROM observation WHERE source = 'collector'")}
    assert status == {"jenkins:build.ros2.org": 0, "ok": 1}
    assert "::warning title=collector jenkins:build.ros2.org failed::" in capsys.readouterr().out


def test_every_collector_failing_is_an_error(monkeypatch, tmp_path):
    code, _ = run(monkeypatch, tmp_path, [Broken()])
    assert code == 1


def test_failing_collector_raises_an_alert_that_escalates_and_clears(tmp_path):
    store = SqliteStore(str(tmp_path / "t.db"))
    now = 1_800_000_000
    name = {"collector": "jenkins:build.ros2.org"}
    store.write(now - 2 * 3600, [Observation("collector", "ok", 1, name)])
    store.write(now - 3600, [Observation("collector", "ok", 0, name)])
    [a] = evaluate(store, now)
    assert (a.severity, a.tab, a.key) == ("warn", "rolling", "collector:jenkins:build.ros2.org")
    assert "since 2h ago" in a.detail

    store.write(now, [Observation("collector", "ok", 0, name)])
    [a] = evaluate(store, now + 12 * 3600)
    assert a.severity == "bad"

    store.write(now + 13 * 3600, [Observation("collector", "ok", 1, name)])
    assert evaluate(store, now + 13 * 3600) == []
