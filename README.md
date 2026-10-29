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
- Nightly matrix: the `jenkins` collector stores one `build` row per recent build (not per-test data) so the page can draw job × day cells that link back to Jenkins. Needs read-only Jenkins API tokens for both servers (`JENKINS_CI_*`, `JENKINS_BUILD_*`).
- Package status: the `repo_status` collector (one config entry per distro) parses the repo.ros2.org status pages and joins each platform's Jenkins view colours in one request. A package is *unbuilt* when no repo has its current version; *failing* when its Jenkins job is also red. Counts go in as observations; each unbuilt package is a `pkg_failure` row (written on transitions only) that links to its Jenkins job.
- The page is tabbed: ci.ros2.org, then Rolling (Rci), then the other distros, then rosdistro. Sections whose jobs do not run daily show only days that had builds.
- Alerts (`[alerts]` in `config.toml`, evaluated at render time): rosdistro merge cadence, consecutive nightly failures, nightlies that stopped running, and bursts of newly failing packages. `rhd alerts` prints them and exits 2 on a `bad` one. No notification channel yet.
- Failing tests (ci.ros2.org only; build.ros2.org puts test reports and consoles behind a bot challenge that is deliberately not worked around): only *failing* tests are stored, from builds of the last day, capped per run, so history builds up run over run.
- Infrastructure vs. real failures: on ci.ros2.org the end of the console of new `FAILURE` builds is matched against known Jenkins infra signatures (`infra_patterns` in config adds more); on build.ros2.org a failed build with no executor time is recognised from the build JSON. Infra failures show as ↯ and do not count toward streaks or badges. Unmatched failures count as real.
- Be gentle with Jenkins: the collectors look back 2 days / 6 builds per job and cap per-run report and console fetches.
- Jenkins collection logic is reused from the `ci-observability` branch of `mjcarroll/ros2` (`export.py`, `buildfarm.py`, `github.py`), copied rather than depended on.

## Status

Live: rosdistro queue, nightly matrices (ci.ros2.org and the Rci/Lci/Kci/Jci/Hci views), per-distro package status. Tracking: https://github.com/mjcarroll/ros-project-management/issues/42

## Development

```
pip install -e '.[dev]' && pytest
GITHUB_TOKEN=$(gh auth token) rhd collect   # writes ./rhd.db (SQLite) unless D1 env vars are set
rhd render --out site
```

Adding a collector: write a class with `name` and `collect() -> list[Observation]`, register it in `src/rhd/collectors/base.py`, enable it in `config.toml`. No schema change is needed.

## Deploy

D1 database `ros-health` exists and Actions secrets are set (`CLOUDFLARE_API_TOKEN` D1-edit, `CLOUDFLARE_ACCOUNT_ID`, `D1_DATABASE_ID`) plus `JENKINS_CI_USER/TOKEN` and `JENKINS_BUILD_USER/TOKEN`; schema applied with `wrangler d1 execute ros-health --remote --file schema/0001_init.sql`. the site is deployed to GitHub Pages by the `deploy` job. `D1Store` verified end to end (first CI run wrote 9 rosdistro rows).
