"""Budget files and the direction-aware comparisons the ratchet is built on."""

import json
import math
from pathlib import Path

DIRECTIONS = ("lower", "higher")


def worse(value, budget, direction):
    """True if ``value`` is worse than ``budget`` in ``direction``."""
    return value > budget if direction == "lower" else value < budget


def stricter(a, b, direction):
    """The stricter of two budgets in ``direction``."""
    return min(a, b) if direction == "lower" else max(a, b)


def load(path, direction=None):
    """Read a budget file; a missing file is an empty budget."""
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return parse(data, direction, str(path))


def parse(data, direction, source):
    """Validate decoded budget JSON and return its key to value map."""
    if not isinstance(data, dict) or not isinstance(data.get("budgets"), dict):
        raise ValueError(f"{source}: not a budget file")
    if direction is not None and data.get("direction") != direction:
        raise ValueError(
            f"{source}: direction {data.get('direction')!r} != {direction!r}"
        )
    return {str(k): float(v) for k, v in data["budgets"].items()}


def dumps(budgets, direction):
    """Serialise budgets one key per line in sorted order, merge-friendly."""
    body = {"direction": direction, "budgets": dict(sorted(budgets.items()))}
    return json.dumps(body, indent=1, allow_nan=True) + "\n"


def save(path, budgets, direction):
    """Write a budget file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(budgets, direction), encoding="utf-8")


def tighten(budgets, values, direction):
    """Budgets moved to current values where stricter; gone keys dropped."""
    return {
        k: stricter(budgets[k], v, direction) if k in budgets else v
        for k, v in values.items()
    }


def loosened(old, new, direction):
    """Keys whose budget in ``new`` is looser than in ``old``."""
    return {
        k: (old[k], v)
        for k, v in new.items()
        if k in old and worse(v, old[k], direction)
    }


def merge(base, ours, theirs, direction):
    """Three-way merge keeping the stricter budget per key.

    A key on both sides takes the stricter value. A key on one side only is
    kept if it was added there and dropped if the other side removed it.
    """
    out = {}
    for k in ours.keys() | theirs.keys():
        if k in ours and k in theirs:
            out[k] = stricter(ours[k], theirs[k], direction)
        elif k not in base:
            out[k] = ours[k] if k in ours else theirs[k]
    return out


def fmt(value):
    """Compact human formatting for a metric value."""
    if value is None:
        return "-"
    if math.isinf(value) or value != int(value):
        return f"{value:g}"
    return str(int(value))
