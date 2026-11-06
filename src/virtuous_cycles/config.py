"""``virtuous-cycles.toml``: the list of metrics to ratchet."""

import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatchcase

from virtuous_cycles.budget import DIRECTIONS

DEFAULT_CONFIG = "virtuous-cycles.toml"


@dataclass(frozen=True)
class Metric:
    """One ratcheted metric: an adapter, a key filter and a budget file."""

    name: str
    adapter: str
    budget: str
    direction: str = "lower"
    select: tuple = ("*",)
    options: dict = field(default_factory=dict)

    def selected(self, values):
        """``values`` restricted to keys matching any ``select`` glob."""
        return {
            k: v
            for k, v in values.items()
            if any(fnmatchcase(k, g) for g in self.select)
        }


def load(path):
    """Parse a config file into a list of :class:`Metric`."""
    with open(path, "rb") as f:
        doc = tomllib.load(f)
    metrics, seen = [], set()
    for i, m in enumerate(doc.get("metric", [])):
        unknown = m.keys() - {
            "name",
            "adapter",
            "budget",
            "direction",
            "select",
            "options",
        }
        if unknown:
            raise ValueError(f"metric {i}: unknown fields {sorted(unknown)}")
        if "adapter" not in m or "budget" not in m:
            raise ValueError(f"metric {i}: 'adapter' and 'budget' are required")
        select = m.get("select", ["*"])
        metric = Metric(
            name=m.get("name", m["adapter"]),
            adapter=m["adapter"],
            budget=m["budget"],
            direction=m.get("direction", "lower"),
            select=tuple([select] if isinstance(select, str) else select),
            options=dict(m.get("options", {})),
        )
        if metric.direction not in DIRECTIONS:
            raise ValueError(f"{metric.name}: direction must be one of {DIRECTIONS}")
        for attr, val in (("name", metric.name), ("budget", metric.budget)):
            if (attr, val) in seen:
                raise ValueError(f"duplicate metric {attr} {val!r}")
            seen.add((attr, val))
        metrics.append(metric)
    if not metrics:
        raise ValueError(f"{path}: no [[metric]] entries")
    return metrics
