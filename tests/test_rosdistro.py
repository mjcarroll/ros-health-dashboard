from datetime import datetime, timedelta, timezone

from rhd.collectors.rosdistro import RosdistroCollector

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def pr(age, reviews=0, comments=0, draft=False):
    return {
        "createdAt": iso(age),
        "isDraft": draft,
        "reviews": {"totalCount": reviews},
        "comments": {"totalCount": comments},
    }


def merged(created_days_ago, merged_days_ago):
    return {"createdAt": iso(created_days_ago), "mergedAt": iso(merged_days_ago)}


def values(observations):
    return {o.metric: o.value for o in observations}


def test_summarize():
    open_prs = [pr(1), pr(3, reviews=1), pr(10, draft=True), pr(20)]
    recent = [merged(5, 2), merged(10, 6), merged(40, 20), merged(90, 60)]
    v = values(RosdistroCollector().summarize(open_prs, recent, NOW))
    assert v["open_prs"] == 4
    assert v["open_prs_unreviewed"] == 2  # drafts and reviewed PRs excluded
    assert v["merged_7d"] == 2
    assert v["merged_30d"] == 3
    assert v["days_since_last_merge"] == 2
    assert v["open_pr_age_max_days"] == 20
    assert v["time_to_merge_p50_days"] == 4  # median of 3, 4, 20 days


def test_empty_queue():
    v = values(RosdistroCollector().summarize([], [], NOW))
    assert v == {"open_prs": 0, "open_prs_unreviewed": 0, "merged_7d": 0, "merged_30d": 0}
