"""Open PR and issue health of any GitHub repo: the same PR measures as the rosdistro collector,
plus issues. One config entry per repo, so covering more ros2 repos later is configuration."""

import statistics
from datetime import datetime, timedelta, timezone

from ..models import Observation
from . import rosdistro
from .rosdistro import RosdistroCollector, _percentile, _ts

ISSUES_OPEN = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { createdAt comments { totalCount } }
    }
  }
}"""

ISSUES_CLOSED = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(states: CLOSED, first: 100, after: $after, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { createdAt closedAt }
    }
  }
}"""


class GithubRepoCollector(RosdistroCollector):
    def __init__(self, repo: str, issues: bool = True):
        super().__init__(repo)
        self.name = repo  # observations are filed under the repo slug, e.g. "ros2-gbp/ros2-gbp-github-org"
        self.issues = issues

    def collect(self) -> list[Observation]:
        prs = super().collect()
        if not self.issues:
            return prs
        now = datetime.now(timezone.utc)
        open_issues = list(rosdistro._pages(ISSUES_OPEN, self.owner, self.repo_name))
        cutoff = now - timedelta(days=rosdistro.MERGED_WINDOW_DAYS)
        closed, old_run = [], 0
        for issue in rosdistro._pages(ISSUES_CLOSED, self.owner, self.repo_name):
            closed.append(issue)
            old_run = old_run + 1 if _ts(issue["closedAt"]) < cutoff else 0
            if old_run >= 100:
                break
        return prs + self.summarize_issues(open_issues, closed, now)

    def summarize_issues(self, open_issues: list[dict], closed: list[dict], now: datetime) -> list[Observation]:
        def obs(metric: str, value: float) -> Observation:
            return Observation(self.name, metric, float(value))

        within = lambda stamp, days: now - _ts(stamp) <= timedelta(days=days)
        ages = sorted((now - _ts(i["createdAt"])).total_seconds() / 86400 for i in open_issues)
        out = [
            obs("open_issues", len(open_issues)),
            obs("open_issues_no_reply", sum(1 for i in open_issues if i["comments"]["totalCount"] == 0)),
            obs("issues_opened_7d", sum(1 for i in [*open_issues, *closed] if within(i["createdAt"], 7))),
            obs("issues_closed_7d", sum(1 for i in closed if within(i["closedAt"], 7))),
            obs("issues_closed_30d", sum(1 for i in closed if within(i["closedAt"], 30))),
        ]
        if ages:
            out += [
                obs("open_issue_age_p50_days", statistics.median(ages)),
                obs("open_issue_age_p90_days", _percentile(ages, 0.9)),
                obs("open_issue_age_max_days", ages[-1]),
            ]
        return out
