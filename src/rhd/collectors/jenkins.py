"""Recent builds of selected Jenkins jobs, for the nightly status matrix."""

import re
import time
import xml.etree.ElementTree as ET

from ..jenkins import Jenkins
from ..models import Build, BuildClass, TestFailures

BUILD_TREE = (
    "builds[number,result,timestamp,duration,url,"
    "actions[failCount,skipCount,totalCount,executingTimeMillis]]{{0,{n}}}"
)


def _tests(actions: list[dict]) -> tuple[int | None, int | None, int | None]:
    for a in actions:
        if "totalCount" in a:
            return a.get("failCount"), a.get("skipCount"), a["totalCount"]
    return None, None, None


FAILED_CASES = ("/job/{job}/{number}/testReport/api/xml"
                "?xpath=//case[status='FAILED' or status='REGRESSION']&wrapper=cases")


# Well-known Jenkins/infrastructure failure signatures, matched against the end of the console.
# Anything that matches none of these is treated as a real failure. Extend via `infra_patterns`.
INFRA_PATTERNS = [
    # Deliberately no mail signature: Jenkins mails every failed build, so an unreachable SMTP server
    # puts a MailSender stack trace at the end of *every* failing console and says nothing about
    # why the build failed (nightly_linux-rhel_release #2863 really failed fetching ros2.repos).
    (r"curl: \((?:6|7|18|28|35|52|55|56)\)", "download failed (curl network error)"),
    (r"curl: \(22\) The requested URL returned error: 5\d\d", "download failed (server error)"),
    (r"ChannelClosedException|Channel is already closed|Connection was broken|ClosedChannelException",
     "agent connection lost"),
    (r"was marked offline|Agent went offline during the build|was removed|Remote call on .* failed|"
     r"Unable to create live FilePath", "agent lost"),
    (r"[Nn]o space left on device", "disk full"),
    (r"Killed signal terminated program|internal compiler error: Killed|virtual memory exhausted|"
     r"std::bad_alloc|Cannot allocate memory", "out of memory"),
    (r"Cannot connect to the Docker daemon|docker: Error response from daemon", "docker daemon error"),
    (r"Could not resolve host|Temporary failure in name resolution|UnknownHostException", "network/DNS failure"),
    # ros_buildfarm's create_workspace.py could not clone the sources, so nothing was built or tested.
    (r"Command '\['vcs', 'import'.*returned non-zero exit status", "source checkout failed (vcs import)"),
]


# colcon's end-of-build summary ("  1 package failed: ros2_transport") and per-package failure lines.
_FAILED_SUMMARY = re.compile(r"\d+ packages? failed:[ \t]*([^\n]+)")
_FAILED_LINE = re.compile(r"Failed\s+<<<\s+(\S+)")


def breadcrumb(console_tail: str) -> str:
    """Which package(s) failed to build, as a short phrase; empty when the console does not say."""
    found = _FAILED_SUMMARY.findall(console_tail)
    names = found[-1].split() if found else list(dict.fromkeys(_FAILED_LINE.findall(console_tail)))
    if not names:
        return ""
    more = f" (+{len(names) - 3} more)" if len(names) > 3 else ""
    return f"build failed: {', '.join(names[:3])}{more}"


def _executing_ms(actions: list[dict]) -> int | None:
    for a in actions:
        if "executingTimeMillis" in a:
            return a["executingTimeMillis"]
    return None


def _int(el, tag):
    text = el.findtext(tag)
    return int(text) if text and text.lstrip("-").isdigit() else None


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
    tests       also record the failing tests of completed builds (servers that serve test
                reports; build.ros2.org does not)
    test_days   only fetch test reports of builds this recent (days). The default of 1 is
                "last night": older builds are never fetched, to go easy on Jenkins
    max_test_fetches   cap per run: each report costs Jenkins seconds to render, so a backfill
                catches up over several runs, newest builds first
    classify_console   tell infrastructure failures from real ones by reading the end of the console
                of new FAILURE builds (servers that allow it; build.ros2.org does not, but there a build
                that never got executor time is recognised from the JSON we already fetch)
    classify_days / max_classify   same kind of limits as for test reports
    infra_patterns   extra regexes that mark a console as an infrastructure failure
    infra_builds     {"job#number": reason} for failures diagnosed by hand, e.g. on build.ros2.org,
                     whose consoles sit behind a bot challenge and cannot be classified automatically
    """

    def __init__(self, label, base_url, user_env, token_env, views=None, group="nightly",
                 match="nightly", days=30, history=40, tests=False, test_days=1,
                 max_test_fetches=20, classify_console=False, classify_days=1, max_classify=10,
                 infra_patterns=(), infra_builds=None, client=None):
        self.name = f"jenkins:{label}"
        self.label = label
        self.views = views
        self.group = group
        self.match = re.compile(match)
        self.days = days
        self.history = history
        self.client = client or Jenkins(base_url, user_env, token_env)
        self.tests, self.test_days, self.max_test_fetches = tests, test_days, max_test_fetches
        self.fetched: set[tuple] = set()
        self.classify_console, self.classify_days, self.max_classify = classify_console, classify_days, max_classify
        self.patterns = [(re.compile(p), r) for p, r in INFRA_PATTERNS] + [
            (re.compile(p), "matched a custom infra pattern") for p in infra_patterns]
        self.classified: set[tuple] = set()
        self.infra_builds = dict(infra_builds or {})

    def bind(self, store) -> None:
        """Learn which builds already have their test report stored."""
        if self.tests:
            self.fetched = {(r["server"], r["job"], r["number"]) for r in store.query(
                "SELECT server, job, number FROM test_fetch")}
        if self.classify_console:
            self.classified = {(r["server"], r["job"], r["number"]) for r in store.query(
                "SELECT server, job, number FROM build_class")}

    def _classify_console(self, b: Build) -> BuildClass:
        tail = self.client.console_tail(b.job, b.number)
        if tail is None:
            return BuildClass(b.server, b.job, b.number, b.ts, "unknown", "console size unavailable")
        crumb = breadcrumb(tail)
        for pattern, reason in self.patterns:
            if pattern.search(tail):
                return BuildClass(b.server, b.job, b.number, b.ts, "infra", f"{reason}; {crumb}" if crumb else reason)
        return BuildClass(b.server, b.job, b.number, b.ts, "code", crumb)

    def _failing_tests(self, b: Build) -> TestFailures | None:
        text = self.client.text(FAILED_CASES.format(job=b.job, number=b.number))
        if text is None:
            return None
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            # Not XML: a bot challenge or login page. Do not keep hammering it.
            raise PermissionError(f"{self.label} did not return a test report for {b.job} #{b.number}")
        cases = [(c.findtext("className") or "", c.findtext("name") or "", _int(c, "age"),
                  _int(c, "failedSince")) for c in root.iter("case")]
        return TestFailures(b.server, b.job, b.number, b.ts, cases)

    def _jobs(self) -> list[tuple[str, str]]:
        """(section, job name) pairs."""
        sources = [(v, f"/view/{v}") for v in self.views] if self.views else [(self.group, "")]
        out = []
        for section, prefix in sources:
            data = self.client.json(f"{prefix}/api/json?tree=jobs[name]") or {}
            out += [(section, j["name"]) for j in data.get("jobs", []) if self.match.search(j["name"])]
        if not out:
            # An anonymous or degraded session lists no jobs with a 200; do not report that as success.
            raise RuntimeError(f"{self.label}: no jobs matched {self.match.pattern!r} (credentials rejected?)")
        return out

    def collect(self) -> list[Build | BuildClass | TestFailures]:
        cutoff = time.time() - self.days * 86400
        builds, classes = [], []
        for section, job in self._jobs():
            path = f"/job/{job}/api/json?tree=" + BUILD_TREE.format(n=self.history)
            for b in (self.client.json(path) or {}).get("builds", []):
                ts = b["timestamp"] // 1000
                if ts < cutoff:
                    continue
                fail, skip, total = _tests(b.get("actions", []))
                if b["result"] == "FAILURE" and b["duration"] > 0 and _executing_ms(b.get("actions", [])) == 0:
                    classes.append(BuildClass(self.label, job, b["number"], ts, "infra",
                                              "agent lost (no executor time)"))
                builds.append(Build(
                    server=self.label, grp=section, job=job, number=b["number"], ts=ts,
                    result=b["result"] or "RUNNING", duration_s=b["duration"] // 1000,
                    url=b["url"], fail=fail, skip=skip, total=total,
                ))
        # Hand-diagnosed builds come last so they win over any automatic classification.
        classes += [BuildClass(b.server, b.job, b.number, b.ts, "infra", reason) for b in builds
                    if (reason := self.infra_builds.get(f"{b.job}#{b.number}"))]
        return builds + classes + self._classify(builds, classes) + self._collect_tests(builds)

    def _classify(self, builds: list[Build], known: list[BuildClass]) -> list[BuildClass]:
        if not self.classify_console:
            return []
        done = {(c.server, c.job, c.number) for c in known} | self.classified
        recent = time.time() - self.classify_days * 86400
        todo = sorted((b for b in builds if b.result == "FAILURE" and b.ts >= recent and b.key not in done),
                      key=lambda b: -b.ts)[: self.max_classify]
        out = []
        for b in todo:
            try:
                out.append(self._classify_console(b))
            except Exception as e:  # one unreadable console must not lose the rest
                print(f"  {self.name}: could not classify {b.job} #{b.number}: {e}")
        return out

    def _collect_tests(self, builds: list[Build]) -> list[TestFailures]:
        if not self.tests:
            return []
        recent = time.time() - self.test_days * 86400
        todo = sorted((b for b in builds if b.result != "RUNNING" and b.fail and b.ts >= recent
                       and b.key not in self.fetched), key=lambda b: -b.ts)
        out = []
        for b in todo[: self.max_test_fetches]:
            try:
                tf = self._failing_tests(b)
            except PermissionError as e:
                print(f"  {e}; skipping test reports this run")
                break
            if tf:
                out.append(tf)
        if len(todo) > len(out):
            print(f"  {self.name}: {len(todo) - len(out)} test reports still to fetch")
        return out
