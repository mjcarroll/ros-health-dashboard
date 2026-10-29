"""Health of the ros/rosdistro PR queue: is work going in at a regular cadence?"""

import statistics
from datetime import datetime, timedelta, timezone

from ..github import graphql
from ..models import Observation

OPEN_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: OPEN, first: 100, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { createdAt isDraft reviews { totalCount } comments { totalCount } }
    }
  }
}"""

MERGED_QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, first: 100, after: $after,
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { createdAt mergedAt }
    }
  }
}"""

MERGED_WINDOW_DAYS = 30


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _pages(query: str, owner: str, name: str):
    after = None
    while True:
        conn = graphql(query, {"owner": owner, "name": name, "after": after})["repository"]["pullRequests"]
        yield from conn["nodes"]
        if not conn["pageInfo"]["hasNextPage"]:
            return
        after = conn["pageInfo"]["endCursor"]


def _percentile(sorted_vals: list[float], q: float) -> float:
    return sorted_vals[min(len(sorted_vals) - 1, int(q * len(sorted_vals)))]


class RosdistroCollector:
    name = "rosdistro"

    def __init__(self, repo: str = "ros/rosdistro"):
        self.owner, self.repo_name = repo.split("/")

    def collect(self) -> list[Observation]:
        now = datetime.now(timezone.utc)
        open_prs = list(_pages(OPEN_QUERY, self.owner, self.repo_name))
        cutoff = now - timedelta(days=MERGED_WINDOW_DAYS)
        merged = []
        # Ordered by update time, not merge time, so an old merge can sit among
        # newer ones; stop only after a long run of consecutive old merges.
        old_run = 0
        for pr in _pages(MERGED_QUERY, self.owner, self.repo_name):
            merged.append(pr)
            old_run = old_run + 1 if _ts(pr["mergedAt"]) < cutoff else 0
            if old_run >= 100:
                break
        return self.summarize(open_prs, merged, now)

    def summarize(self, open_prs: list[dict], merged: list[dict], now: datetime) -> list[Observation]:
        def obs(metric: str, value: float) -> Observation:
            return Observation(self.name, metric, float(value))

        ages = sorted((now - _ts(p["createdAt"])).total_seconds() / 86400 for p in open_prs)
        ready = [p for p in open_prs if not p["isDraft"]]
        unreviewed = [p for p in ready if p["reviews"]["totalCount"] + p["comments"]["totalCount"] == 0]

        merge_times = sorted(_ts(p["mergedAt"]) for p in merged)
        in_30d = [t for t in merge_times if now - t <= timedelta(days=30)]
        in_7d = [t for t in in_30d if now - t <= timedelta(days=7)]
        ttm = sorted(
            (_ts(p["mergedAt"]) - _ts(p["createdAt"])).total_seconds() / 86400
            for p in merged
            if now - _ts(p["mergedAt"]) <= timedelta(days=30)
        )

        out = [
            obs("open_prs", len(open_prs)),
            obs("open_prs_unreviewed", len(unreviewed)),
            obs("merged_7d", len(in_7d)),
            obs("merged_30d", len(in_30d)),
        ]
        if ages:
            out += [
                obs("open_pr_age_p50_days", statistics.median(ages)),
                obs("open_pr_age_p90_days", _percentile(ages, 0.9)),
                obs("open_pr_age_max_days", ages[-1]),
            ]
        if ttm:
            out += [obs("time_to_merge_p50_days", statistics.median(ttm))]
        if merge_times:
            out += [obs("days_since_last_merge", (now - merge_times[-1]).total_seconds() / 86400)]
        return out
