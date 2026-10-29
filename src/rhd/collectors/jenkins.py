"""Recent builds of selected Jenkins jobs, for the nightly status matrix."""

import re
import time

from ..jenkins import Jenkins
from ..models import Build

BUILD_TREE = (
    "builds[number,result,timestamp,duration,url,"
    "actions[failCount,skipCount,totalCount]]{{0,{n}}}"
)


def _tests(actions: list[dict]) -> tuple[int | None, int | None, int | None]:
    for a in actions:
        if "totalCount" in a:
            return a.get("failCount"), a.get("skipCount"), a["totalCount"]
    return None, None, None


class JenkinsCollector:
    """Options:
    label       display name of the server, e.g. "ci.ros2.org"
    base_url    Jenkins root
    user_env / token_env   names of the env vars holding credentials
    views       optional list of views; each becomes a matrix section. Without it,
                jobs come from the server root and form one section named `group`.
    match       regex a job name must match (search, not full match)
    days        only keep builds started within this many days
    history     max builds fetched per job
    """

    def __init__(self, label, base_url, user_env, token_env, views=None, group="nightly",
                 match="nightly", days=30, history=40, client=None):
        self.name = f"jenkins:{label}"
        self.label = label
        self.views = views
        self.group = group
        self.match = re.compile(match)
        self.days = days
        self.history = history
        self.client = client or Jenkins(base_url, user_env, token_env)

    def _jobs(self) -> list[tuple[str, str]]:
        """(section, job name) pairs."""
        sources = [(v, f"/view/{v}") for v in self.views] if self.views else [(self.group, "")]
        out = []
        for section, prefix in sources:
            data = self.client.json(f"{prefix}/api/json?tree=jobs[name]") or {}
            out += [(section, j["name"]) for j in data.get("jobs", []) if self.match.search(j["name"])]
        return out

    def collect(self) -> list[Build]:
        cutoff = time.time() - self.days * 86400
        builds = []
        for section, job in self._jobs():
            path = f"/job/{job}/api/json?tree=" + BUILD_TREE.format(n=self.history)
            for b in (self.client.json(path) or {}).get("builds", []):
                ts = b["timestamp"] // 1000
                if ts < cutoff:
                    continue
                fail, skip, total = _tests(b.get("actions", []))
                builds.append(Build(
                    server=self.label, grp=section, job=job, number=b["number"], ts=ts,
                    result=b["result"] or "RUNNING", duration_s=b["duration"] // 1000,
                    url=b["url"], fail=fail, skip=skip, total=total,
                ))
        return builds
