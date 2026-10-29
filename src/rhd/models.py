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
