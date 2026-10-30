"""Build queue depth per distro on a Jenkins server (one request to /queue/api/json per run).

Job names start with the distro's view letter (Rbin_..., Lrel_..., Kci_...), so each queued item is
attributed to a distro by that prefix. `buildable` items only wait for a free executor; `blocked`
items wait for an upstream job, which is what a large release cascade looks like.
"""

import re
import time

from ..jenkins import Jenkins
from ..layout import DISTROS
from ..models import Observation

PREFIX = re.compile(r"^([A-Z])[a-z]+_")


class BuildQueueCollector:
    def __init__(self, base_url="https://build.ros2.org", user_env="JENKINS_BUILD_USER",
                 token_env="JENKINS_BUILD_TOKEN", client=None, clock=time.time):
        self.name = "build_queue"
        self.base_url = base_url
        self.user_env, self.token_env = user_env, token_env
        self._client = client
        self.clock = clock

    @property
    def client(self):
        if self._client is None:
            self._client = Jenkins(self.base_url, self.user_env, self.token_env)
        return self._client

    def collect(self):
        data = self.client.json("/queue/api/json?tree=items[task[name],inQueueSince,buildable,blocked]")
        if data is None:
            raise RuntimeError(f"no build queue at {self.base_url}")
        distro_of = {view[0]: distro for distro, view, _ in DISTROS}
        # Every distro gets a row each run, so a drained queue shows as 0 rather than a gap.
        counts = {d: {"queue_total": 0, "queue_buildable": 0, "queue_blocked": 0} for d in distro_of.values()}
        oldest = {d: 0.0 for d in distro_of.values()}
        now = self.clock()
        for item in data.get("items", []):
            m = PREFIX.match((item.get("task") or {}).get("name", ""))
            distro = distro_of.get(m.group(1)) if m else None
            if distro is None:
                continue
            c = counts[distro]
            c["queue_total"] += 1
            if item.get("buildable"):
                c["queue_buildable"] += 1
            elif item.get("blocked"):
                c["queue_blocked"] += 1
            if since := item.get("inQueueSince"):
                oldest[distro] = max(oldest[distro], now - since / 1000)
        obs = []
        for distro, c in counts.items():
            labels = {"distro": distro}
            obs += [Observation("build_queue", metric, value, labels) for metric, value in c.items()]
            obs.append(Observation("build_queue", "queue_oldest_s", round(oldest[distro]), labels))
        return obs
