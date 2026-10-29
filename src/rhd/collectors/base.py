from typing import Protocol

from ..models import Observation


class Collector(Protocol):
    """A data source. Add one by writing a class with `name` and `collect`,
    then registering it in REGISTRY below."""

    name: str

    def collect(self) -> list[Observation]: ...


def _registry() -> dict[str, type]:
    # Imported lazily so a collector's dependencies load only when enabled.
    from .rosdistro import RosdistroCollector

    return {"rosdistro": RosdistroCollector}


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
