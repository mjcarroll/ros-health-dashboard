from typing import Protocol

from ..models import Build, FailureSnapshot, Observation


class Collector(Protocol):
    """A data source. Add one by writing a class with `name` and `collect`,
    then registering it in REGISTRY below."""

    name: str

    def collect(self) -> list[Observation | Build | FailureSnapshot]: ...


def _registry() -> dict[str, type]:
    # Imported lazily so a collector's dependencies load only when enabled.
    from .build_queue import BuildQueueCollector
    from .github_repo import GithubRepoCollector
    from .jenkins import JenkinsCollector
    from .repo_status import RepoStatusCollector
    from .rosdistro import RosdistroCollector

    return {
        "rosdistro": RosdistroCollector,
        "github_repo": GithubRepoCollector,
        "jenkins": JenkinsCollector,
        "repo_status": RepoStatusCollector,
        "build_queue": BuildQueueCollector,
    }


def build_collectors(entries: list[dict]) -> list[Collector]:
    registry = _registry()
    collectors = []
    for entry in entries:
        opts = dict(entry)
        kind = opts.pop("type")
        if kind not in registry:
            raise ValueError(f"unknown collector type {kind!r}; known: {sorted(registry)}")
        collectors.append(registry[kind](**opts))
    return collectors
