from datetime import datetime, timedelta, timezone

from rhd.collectors import rosdistro
from rhd.collectors.github_repo import GithubRepoCollector

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def iso(days_ago):
    return (NOW - timedelta(days=days_ago)).isoformat()


def issue(age, comments=0, closed_ago=None):
    return {"createdAt": iso(age), "comments": {"totalCount": comments},
            **({"closedAt": iso(closed_ago)} if closed_ago is not None else {})}


def collector():
    return GithubRepoCollector("ros2-gbp/ros2-gbp-github-org")


def test_issue_summary():
    c = collector()
    open_issues = [issue(2), issue(10, comments=3), issue(200)]
    closed = [issue(3, closed_ago=1), issue(40, closed_ago=20), issue(400, closed_ago=100)]
    v = {o.metric: o.value for o in c.summarize_issues(open_issues, closed, NOW)}
    assert v["open_issues"] == 3 and v["open_issues_no_reply"] == 2
    assert v["issues_opened_7d"] == 2           # one open + one closed, both created within 7 days
    assert v["issues_closed_7d"] == 1 and v["issues_closed_30d"] == 2
    assert v["open_issue_age_max_days"] == 200 and v["open_issue_age_p50_days"] == 10


def test_observations_are_filed_under_the_repo_slug(monkeypatch):
    def fake_graphql(query, variables, token=None):
        node = {"createdAt": iso(1), "isDraft": False, "reviews": {"totalCount": 0},
                "comments": {"totalCount": 0}, "mergedAt": iso(0.5), "closedAt": iso(0.5)}
        field = "issues" if "issues(" in query else "pullRequests"
        return {"repository": {field: {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [node]}}}

    monkeypatch.setattr(rosdistro, "graphql", fake_graphql)
    obs = collector().collect()
    assert {o.source for o in obs} == {"ros2-gbp/ros2-gbp-github-org"}
    metrics = {o.metric for o in obs}
    assert {"open_prs", "merged_7d", "open_issues", "issues_closed_30d"} <= metrics


def test_issues_can_be_switched_off(monkeypatch):
    def fake_graphql(query, variables, token=None):
        assert "issues(" not in query
        return {"repository": {"pullRequests": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}}}

    monkeypatch.setattr(rosdistro, "graphql", fake_graphql)
    assert not any(o.metric == "open_issues" for o in GithubRepoCollector("a/b", issues=False).collect())
