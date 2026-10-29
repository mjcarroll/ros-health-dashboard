"""Package build status per distro from the buildfarm status page
(https://repo.ros2.org/status_page/ros_<distro>_default.html).

For every package and platform column the page shows whether the expected version exists in
the `building`, `testing` and `main` apt repos. The `building` repo is emptied once packages are
synced onward, so a package is "unbuilt" only when no repo has the current version. The Jenkins job
colour (one bulk request per view) then separates real failures from jobs that merely aborted
behind them.
"""

import html
import re
import urllib.request
from datetime import datetime

from ..jenkins import Jenkins
from ..models import FailureSnapshot, Observation, PkgFailure

COLOR = {
    "blue": "SUCCESS", "red": "FAILURE", "yellow": "UNSTABLE", "aborted": "ABORTED",
    "disabled": "DISABLED", "notbuilt": "NOT_BUILT", "grey": "NOT_BUILT",
}


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=120) as resp:
        return resp.read().decode("utf-8", "replace")


def page_time(page: str) -> float | None:
    """When the buildfarm generated this status page (unix seconds)."""
    m = re.search(r'moment\("(\d+(?:\.\d+)?)",\s*"X"\)', page)
    if m:
        return float(m.group(1))
    m = re.search(r"<title>[^<]*?(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4})</title>", page)
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S %z").timestamp() if m else None


def parse(page: str) -> tuple[list[tuple[str, str]], list[str], list[dict]]:
    """-> (columns [(short, title)], job url templates, packages).
    Each package: {pkg, version, cells: [[building, testing, main] class letters per column]}."""
    head = page[: page.index("<tbody")]
    columns = [
        (short, html.unescape(title))
        for title, short in re.findall(r'<th><div title="([^"]*)">([^<]*)</div><span class="sum">', head)
    ]
    templates = re.findall(r"'(https://[^']*\{pkg\}[^']*)'", head)
    meta = head.count('<th class="sortable">')

    packages = []
    body = page[page.index("<tbody"):]
    for row in re.findall(r"<tr><td>.*?</tr>", body, re.S):
        tds = re.findall(r"<td\b.*?</td>", row, re.S)
        if len(tds) != meta + len(columns):
            continue
        name = re.search(r">([^<]+)</a>", tds[0])
        version = re.search(r"<span>([^<]*)</span>", tds[2])
        packages.append({
            "pkg": html.unescape(name.group(1)),
            "version": version.group(1) if version else None,
            "cells": [re.findall(r'<a class="([a-z]*)"', td) for td in tds[meta:]],
        })
    return columns, templates, packages


class RepoStatusCollector:
    def __init__(self, distro, base_url="https://repo.ros2.org/status_page",
                 jenkins_url="https://build.ros2.org", user_env="JENKINS_BUILD_USER",
                 token_env="JENKINS_BUILD_TOKEN", client=None, page_fetch=fetch):
        self.name = f"repo_status:{distro}"
        self.distro = distro
        self.url = f"{base_url}/ros_{distro}_default.html"
        self.jenkins_url = jenkins_url
        self.user_env, self.token_env = user_env, token_env
        self._client = client
        self.page_fetch = page_fetch

    @property
    def client(self):
        if self._client is None:
            self._client = Jenkins(self.jenkins_url, self.user_env, self.token_env)
        return self._client

    def _job_results(self, template: str) -> dict[str, str]:
        """job name -> result for every job in the template's Jenkins view."""
        view = re.search(r"/view/([^/]+)/job/", template)
        if not view:
            return {}
        data = self.client.json(f"/view/{view.group(1)}/api/json?tree=jobs[name,color]") or {}
        return {
            j["name"]: COLOR.get(j.get("color", "").removesuffix("_anime"), "UNKNOWN")
            for j in data.get("jobs", [])
        }

    def collect(self):
        page = self.page_fetch(self.url)
        columns, templates, packages = parse(page)
        if not columns or len(templates) != len(columns) or not packages:
            raise RuntimeError(f"unexpected status page layout at {self.url}")

        obs, failures = [], []
        generated = page_time(page)
        if generated is not None:  # page-level, so no platform column
            obs.append(Observation("repo_status", "page_generated_ts", generated,
                                   {"distro": self.distro, "column": ""}))
        for idx, (short, title) in enumerate(columns):
            results = self._job_results(templates[idx])
            total = unbuilt = failed = 0
            for p in packages:
                cells = p["cells"][idx]
                if any(c in ("e", "h") for c in cells):  # current version available somewhere
                    total += 1
                    continue
                if any(c in ("i", "o") for c in cells):  # intentionally missing / obsolete
                    continue
                total += 1
                unbuilt += 1
                state = "stale" if "l" in cells else "missing"
                url = templates[idx].replace("{pkg}", p["pkg"])
                job = url.rsplit("/job/", 1)[1]
                result = results.get(job)
                failed += result == "FAILURE"
                failures.append(PkgFailure(self.distro, short, p["pkg"], state, url,
                                           result, p["version"]))
            labels = {"distro": self.distro, "column": short}
            obs += [
                Observation("repo_status", "pkgs_total", total, labels),
                Observation("repo_status", "pkgs_unbuilt", unbuilt, labels),
                Observation("repo_status", "pkgs_failed", failed, labels),
            ]
        return [*obs, FailureSnapshot(self.distro, failures)]
