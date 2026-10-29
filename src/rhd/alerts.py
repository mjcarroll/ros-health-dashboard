"""Threshold checks over what is already in the store. Evaluated at render time, so changing a
threshold in config.toml takes effect on the next run without re-collecting anything."""

import statistics
from dataclasses import dataclass, fields

from .layout import tab_for

SEVERITY = {"bad": 0, "warn": 1}


@dataclass
class Thresholds:
    # rosdistro: PRs should keep merging.
    rosdistro_days_since_merge_warn: float = 1.0
    rosdistro_days_since_merge_bad: float = 3.0
    rosdistro_merge_rate_warn: float = 0.5   # merged_7d below this share of the 30-day weekly average
    rosdistro_merge_rate_bad: float = 0.25
    # nightlies: consecutive FAILURE builds (UNSTABLE is test failures and is normal), and jobs
    # that stopped running.
    nightly_consecutive_failures_warn: int = 2
    nightly_consecutive_failures_bad: int = 4
    nightly_stale_factor: float = 2.5        # no build for this many typical gaps...
    nightly_stale_min_hours: float = 36.0    # ...and at least this long
    # packages: jobs that turned red recently, per distro.
    packages_new_failures_24h_warn: int = 5
    packages_new_failures_24h_bad: int = 15

    @classmethod
    def from_config(cls, section: dict | None) -> "Thresholds":
        known = {f.name for f in fields(cls)}
        unknown = set(section or {}) - known
        if unknown:
            raise ValueError(f"unknown [alerts] keys: {sorted(unknown)}; known: {sorted(known)}")
        return cls(**(section or {}))


@dataclass(frozen=True)
class Alert:
    severity: str   # 'bad' | 'warn'
    tab: str
    title: str
    detail: str = ""
    url: str | None = None
    key: str = ""   # stable identity for dismissal; the title often contains changing numbers


def _level(value, warn, bad, higher_is_worse=True):
    if higher_is_worse:
        return "bad" if value >= bad else "warn" if value >= warn else None
    return "bad" if value <= bad else "warn" if value <= warn else None


def _rosdistro(store, now, t) -> list[Alert]:
    latest = {}
    for r in store.query(
        "SELECT metric, value FROM observation WHERE source = 'rosdistro' AND ts = "
        "(SELECT MAX(ts) FROM observation WHERE source = 'rosdistro')"):
        latest[r["metric"]] = r["value"]
    out = []
    days = latest.get("days_since_last_merge")
    if days is not None and (lvl := _level(days, t.rosdistro_days_since_merge_warn,
                                           t.rosdistro_days_since_merge_bad)):
        out.append(Alert(lvl, "rosdistro", "rosdistro has stopped merging",
                         f"last merge {days:.1f} days ago", "https://github.com/ros/rosdistro/pulls?q=is%3Amerged",
                         "rosdistro:stopped"))
    if "merged_7d" in latest and latest.get("merged_30d"):
        weekly = latest["merged_30d"] * 7 / 30
        ratio = latest["merged_7d"] / weekly
        if lvl := _level(ratio, t.rosdistro_merge_rate_warn, t.rosdistro_merge_rate_bad, False):
            out.append(Alert(lvl, "rosdistro", "rosdistro merge rate is down",
                             f"{latest['merged_7d']:.0f} merged in 7 days vs a {weekly:.0f}/week average",
                             "https://github.com/ros/rosdistro/pulls?q=is%3Amerged", "rosdistro:rate"))
    return out


def _nightlies(store, now, t) -> list[Alert]:
    jobs: dict[tuple, list[dict]] = {}
    for r in store.query(
        "SELECT b.server, b.grp, b.job, b.number, b.ts, b.result, b.url, c.kind FROM build b "
        "LEFT JOIN build_class c USING (server, job, number) ORDER BY b.server, b.job, b.ts"):
        jobs.setdefault((r["server"], r["grp"], r["job"]), []).append(r)
    out = []
    for (server, grp, job), builds in jobs.items():
        tab = tab_for(server, grp)
        job_url = builds[-1]["url"].rstrip("/").rsplit("/", 1)[0] + "/"
        done = [b for b in builds if b["result"] != "RUNNING"]

        streak = 0
        for b in reversed(done):
            if b["kind"] == "infra":  # says nothing about the code: neither extends nor breaks a streak
                continue
            if b["result"] != "FAILURE":
                break
            streak += 1
        if lvl := _level(streak, t.nightly_consecutive_failures_warn, t.nightly_consecutive_failures_bad):
            out.append(Alert(lvl, tab, f"{job} failed {streak} builds in a row", server, builds[-1]["url"],
                             f"streak:{server}:{job}"))

        if len(builds) >= 3:
            recent = [b["ts"] for b in builds[-10:]]
            gap = statistics.median(b - a for a, b in zip(recent, recent[1:]))
            allowed = max(t.nightly_stale_min_hours * 3600, t.nightly_stale_factor * gap)
            silent = now - builds[-1]["ts"]
            if silent > allowed:
                out.append(Alert("warn", tab, f"{job} has not run for {silent / 86400:.1f} days",
                                 f"usually every {gap / 86400:.1f} days", job_url, f"stale:{server}:{job}"))
    return out


def _packages(store, now, t) -> list[Alert]:
    out = []
    for r in store.query(
        "SELECT p.distro, COUNT(*) n FROM pkg_failure p WHERE p.resolved IS NULL AND p.jenkins = 'FAILURE' "
        "AND p.first_seen >= ? GROUP BY p.distro", [int(now) - 86400]):
        # The first snapshot marks everything as new; only trust this once there is a day of history.
        oldest = store.query("SELECT MIN(ts) m FROM observation WHERE source = 'repo_status' "
                             "AND json_extract(labels, '$.distro') = ?", [r["distro"]])[0]["m"]
        if oldest is None or now - oldest < 86400:
            continue
        if lvl := _level(r["n"], t.packages_new_failures_24h_warn, t.packages_new_failures_24h_bad):
            out.append(Alert(lvl, r["distro"], f"{r['n']} packages started failing in {r['distro']} in the last 24h",
                             key=f"pkgs:{r['distro']}"))
    return out


def evaluate(store, now: float, thresholds: Thresholds | None = None) -> list[Alert]:
    t = thresholds or Thresholds()
    alerts = [*_rosdistro(store, now, t), *_nightlies(store, now, t), *_packages(store, now, t)]
    return sorted(alerts, key=lambda a: (SEVERITY[a.severity], a.tab, a.title))
