"""``virtuous-cycles.toml``: the list of metrics to ratchet."""

import tomllib
from dataclasses import dataclass, field
from fnmatch import fnmatchcase

from virtuous_cycles.budget import DIRECTIONS, worse

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
    limits: dict = field(default_factory=dict)
    tolerance: dict = field(default_factory=dict)

    def selected(self, values):
        """``values`` restricted to keys matching any ``select`` glob."""
        return {
            k: v
            for k, v in values.items()
            if any(fnmatchcase(k, g) for g in self.select)
        }

    def limit(self, key):
        """The strictest limit whose glob matches ``key``, or None."""
        found = [v for g, v in self.limits.items() if fnmatchcase(key, g)]
        return (min if self.direction == "lower" else max)(found, default=None)

    def tolerance_for(self, key):
        """The smallest tolerance whose glob matches ``key``, or 0."""
        found = [v for g, v in self.tolerance.items() if fnmatchcase(key, g)]
        return min(found, default=0)

    def regressed(self, key, value, budget_value):
        """True if ``value`` is worse than ``key``'s budget beyond its tolerance."""
        return worse(value, budget_value, self.direction, self.tolerance_for(key))

    def over(self, key, value):
        """True if ``value`` is worse than ``key``'s limit."""
        lim = self.limit(key)
        return lim is not None and worse(value, lim, self.direction)


def number_table(i, m, name):
    """The ``name`` field of metric ``m`` as a table of glob to number."""
    table = m.get(name, {})
    if not isinstance(table, dict) or any(
        isinstance(v, bool) or not isinstance(v, (int, float)) for v in table.values()
    ):
        raise ValueError(f"metric {i}: {name} must be a table of glob to number")
    return dict(table)


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
            "limits",
            "tolerance",
        }
        if unknown:
            raise ValueError(f"metric {i}: unknown fields {sorted(unknown)}")
        if "adapter" not in m or "budget" not in m:
            raise ValueError(f"metric {i}: 'adapter' and 'budget' are required")
        select = m.get("select", ["*"])
        limits = number_table(i, m, "limits")
        tolerance = number_table(i, m, "tolerance")
        if any(v < 0 for v in tolerance.values()):
            raise ValueError(f"metric {i}: tolerance values must be >= 0")
        metric = Metric(
            name=m.get("name", m["adapter"]),
            adapter=m["adapter"],
            budget=m["budget"],
            direction=m.get("direction", "lower"),
            select=tuple([select] if isinstance(select, str) else select),
            options=dict(m.get("options", {})),
            limits=limits,
            tolerance=tolerance,
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
