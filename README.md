# ros-health-dashboard

Top-line health dashboard for the ROS 2 project. It answers "is the project healthy right now?", not "why did this test fail?". Deep dives stay in the local Grafana/Loki stack (`mjcarroll/ros2`, branch `ci-observability`).

## Goals

1. **rosdistro PR queue**: PRs in `ros/rosdistro` should merge at a regular cadence. Track open count, age distribution, merges per day/week, time-to-first-review, time-to-merge, days since last merge.
2. **Nightly build status**: ci.ros2.org and build.ros2.org (Rci, Kci, Lci, ...). Per-job pass/fail and test-failure counts over time.
3. **Later**: PRs/issues across all ros2 repos. The design must make this a config + new collector, not a rewrite.

## Architecture

- **Collectors** run on a GitHub Actions cron. Each implements `collect() -> list[Observation]` and is enabled in a config file. Adding a data source means adding a collector.
- **Storage**: Cloudflare D1 (SQLite). Only top-line rollups go here, never raw logs or per-test history. Schema is a generic `observation(ts, source, metric, labels_json, value)` table plus a small number of current-state tables.
- **Dashboard**: static site rendered from D1 by the workflow and published to Pages/Cloudflare. No Grafana.
- **Secrets** (Actions): `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, optionally a GitHub PAT (the built-in `GITHUB_TOKEN` is enough for public reads of `ros/rosdistro`).
- Jenkins collection logic is reused from the `ci-observability` branch of `mjcarroll/ros2` (`export.py`, `buildfarm.py`, `github.py`), copied rather than depended on.

## Status

Not started. Tracking: https://github.com/mjcarroll/ros-project-management/issues
