"""``cxx-cost`` and ``py-cost`` adapters over the JSON cost reports of
``vc-cxx-cost`` and ``vc-py-cost``."""

import json
import math
from fnmatch import fnmatchcase

from virtuous_cycles.adapters import register

VERSION = 1
VALUES = ("cost", "unbounded", "degree")


class Symbols:
    """Symbol values: options, then the report, then ``default``; memoised."""

    def __init__(self, report, options):
        self.unbounded = report.get("unbounded_symbol", "?")
        self.report = report.get("symbols", {})
        self.options = options.get("symbols", {})
        self.default = options.get("default")
        self.cache = {}

    def __getitem__(self, name):
        if name not in self.cache:
            self.cache[name] = self.resolve(name)
        return self.cache[name]

    def resolve(self, name):
        """The value of one symbol; ``log2(X)`` is ``max(0, log2(X))``."""
        if name == self.unbounded:
            return math.inf
        if name.startswith("log2(") and name.endswith(")"):
            x = self[name[5:-1]]
            return math.log2(x) if x > 1 else 0.0
        for table in (self.options, self.report):
            if table.get(name) is not None:
                return float(table[name])
        if self.default is None:
            raise ValueError(f"cxx-cost: no value for symbol {name!r}")
        return float(self.default)


def cost(terms, symbols):
    """The polynomial's value; a term with an infinite factor is infinite."""
    return sum(
        t["coefficient"] * math.prod(symbols[s] ** p for s, p in t["powers"].items())
        for t in terms
    )


def cost_report(options, adapter):
    """Per-entry ``cost``, ``unbounded`` and ``degree:<symbol>`` from a report.

    See docs/adapters.md for the options.
    """
    with open(options.get("report", f"{adapter}.json"), encoding="utf-8") as f:
        report = json.load(f)
    if report.get("version") != VERSION:
        raise ValueError(
            f"{adapter}: unsupported report version {report.get('version')!r}"
        )
    values = set(options.get("values", VALUES))
    if values - set(VALUES):
        raise ValueError(f"{adapter}: values must be among {VALUES}: {sorted(values)}")
    globs = options.get("entries", ["*"])
    symbols = Symbols(report, options)
    out = {}
    for name, e in report["entries"].items():
        if not any(fnmatchcase(name, g) for g in globs):
            continue
        if "cost" in values:
            out[f"{name}:cost"] = float(cost(e["terms"], symbols))
        if "unbounded" in values:
            out[f"{name}:unbounded"] = float(len(e["ledger"]))
        if "degree" in values:
            out.update({f"{name}:degree:{s}": float(d) for s, d in e["degree"].items()})
    return out


@register("cxx-cost")
def cxx_cost(options):
    """The ``vc-cxx-cost`` report."""
    return cost_report(options, "cxx-cost")


@register("py-cost")
def py_cost(options):
    """The ``vc-py-cost`` report."""
    return cost_report(options, "py-cost")
