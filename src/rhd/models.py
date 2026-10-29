import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Observation:
    source: str
    metric: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def labels_json(self) -> str:
        return json.dumps(self.labels, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Build:
    server: str
    grp: str
    job: str
    number: int
    ts: int
    result: str
    duration_s: int
    url: str
    fail: int | None = None
    skip: int | None = None
    total: int | None = None

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.server, self.job, self.number)

    @property
    def state(self) -> tuple:
        """What can change after a build is first seen (it finishes, tests are reported)."""
        return (self.result, self.duration_s, self.fail, self.skip, self.total)


@dataclass(frozen=True)
class PkgFailure:
    distro: str
    col: str
    pkg: str
    state: str
    url: str
    jenkins: str | None = None
    version: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.distro, self.col, self.pkg)

    @property
    def detail(self) -> tuple:
        return (self.state, self.jenkins, self.version, self.url)


@dataclass(frozen=True)
class FailureSnapshot:
    """Everything failing right now within `scope` (a distro). Anything open in the
    store for that scope but absent here has been fixed."""

    scope: str
    failures: list[PkgFailure]
