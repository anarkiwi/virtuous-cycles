"""``virtuous-cycles`` command line."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from tqdm import tqdm

from virtuous_cycles import budget, config
from virtuous_cycles.adapters import get_adapter


def measure(metrics, quiet=False):
    """Evaluate each metric's adapter and apply its ``select`` globs."""
    out = {}
    for m in tqdm(
        metrics, desc="metrics", unit="metric", disable=quiet, file=sys.stderr
    ):
        out[m.name] = m.selected(get_adapter(m.adapter)(m.options))
    return out


def rows(metric, values, budgets):
    """One ``(key, value, budget, status)`` per key in values or budgets."""
    for k in sorted(values.keys() | budgets.keys()):
        v, b = values.get(k), budgets.get(k)
        if v is None:
            status = "gone"
        elif metric.over(k, v):
            status = "over"
        elif b is None:
            status = "new"
        elif budget.worse(v, b, metric.direction):
            status = "worse"
        elif budget.worse(b, v, metric.direction):
            status = "better"
        else:
            status = "ok"
        yield k, v, b, status


def budget_at(ref, path):
    """The budget file at ``path`` in git ``ref``; None if that commit lacks it."""
    path = Path(path).resolve()
    git = ["git", "-C", str(path.parent)]
    subprocess.run(
        git + ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        check=True,
        capture_output=True,
    )
    shown = subprocess.run(
        git + ["show", f"{ref}:./{path.name}"],
        check=False,
        capture_output=True,
        text=True,
    )
    if shown.returncode:
        return None
    data = json.loads(shown.stdout)
    return data.get("direction"), budget.parse(data, None, f"{ref}:{path.name}")


def cmd_check(args, metrics):
    """Fail on values over limit or budget, unbudgeted keys, or loosened budgets."""
    failures, values = [], measure(metrics, args.quiet)
    for m in metrics:
        current = budget.load(m.budget, m.direction)
        if args.against:
            old = budget_at(args.against, m.budget)
            if old is not None:
                direction, old_budgets = old
                if direction != m.direction:
                    failures.append(f"{m.name}: direction changed since {args.against}")
                for k, (was, now) in sorted(
                    budget.loosened(old_budgets, current, m.direction).items()
                ):
                    failures.append(
                        f"{m.name}: {k}: budget loosened {budget.fmt(was)} -> "
                        f"{budget.fmt(now)} since {args.against}"
                    )
        for k, v, b, status in rows(m, values[m.name], current):
            if status == "over":
                failures.append(
                    f"{m.name}: {k}: {budget.fmt(v)} over limit {budget.fmt(m.limit(k))}"
                )
            elif status == "worse":
                failures.append(
                    f"{m.name}: {k}: {budget.fmt(v)} worse than budget {budget.fmt(b)}"
                )
            elif status == "new":
                failures.append(f"{m.name}: {k}: {budget.fmt(v)} has no budget")
    print("\n".join(failures) if failures else "ok")
    return 1 if failures else 0


def cmd_tighten(args, metrics):
    """Move budgets to current values where stricter and drop gone keys."""
    values = measure(metrics, args.quiet)
    for m in metrics:
        old = budget.load(m.budget, m.direction)
        new = budget.tighten(old, values[m.name], m.direction)
        budget.save(m.budget, new, m.direction)
        changed = sum(old.get(k) != v for k, v in new.items())
        print(
            f"{m.name}: {changed} tightened or added, {len(old.keys() - new.keys())} dropped"
        )
    return 0


def cmd_report(args, metrics):
    """Print every key's value, budget and status."""
    values = measure(metrics, args.quiet)
    table = [
        {"metric": m.name, "key": k, "value": v, "budget": b, "status": s}
        for m in metrics
        for k, v, b, s in rows(m, values[m.name], budget.load(m.budget, m.direction))
    ]
    if args.json:
        print(json.dumps(table, indent=1))
        return 0
    cols = ("metric", "key", "value", "budget", "status")
    cells = [cols] + [
        tuple(budget.fmt(r[c]) if c in ("value", "budget") else r[c] for c in cols)
        for r in table
    ]
    widths = [max(len(row[i]) for row in cells) for i in range(len(cols))]
    for row in cells:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip())
    return 0


def read_side(path):
    """A merge-driver input: ``(direction, budgets)``; empty if blank."""
    text = Path(path).read_text(encoding="utf-8")
    if not text.strip():
        return None, {}
    data = json.loads(text)
    return data.get("direction"), budget.parse(data, None, path)


def cmd_merge_driver(args):
    """Git merge driver: write the per-key stricter merge into ``ours``."""
    _, base = read_side(args.base)
    d_ours, ours = read_side(args.ours)
    d_theirs, theirs = read_side(args.theirs)
    direction = d_ours or d_theirs
    if d_ours and d_theirs and d_ours != d_theirs or direction not in budget.DIRECTIONS:
        print(
            f"virtuous-cycles: cannot merge {args.path or args.ours}", file=sys.stderr
        )
        return 1
    Path(args.ours).write_text(
        budget.dumps(budget.merge(base, ours, theirs, direction), direction),
        encoding="utf-8",
    )
    return 0


def parser():
    """Build the argument parser."""
    p = argparse.ArgumentParser(prog="virtuous-cycles", description=__doc__)
    p.add_argument("-c", "--config", default=config.DEFAULT_CONFIG)
    p.add_argument("-q", "--quiet", action="store_true", help="no progress bars")
    p.add_argument("-m", "--metric", action="append", help="only these metrics")
    sub = p.add_subparsers(dest="cmd", required=True)
    check = sub.add_parser("check", help="fail if any value is worse than budget")
    check.add_argument(
        "--against", metavar="REF", help="also fail on budgets looser than at REF"
    )
    sub.add_parser("tighten", help="ratchet budgets to current values")
    report = sub.add_parser("report", help="print values against budgets")
    report.add_argument("--json", action="store_true")
    merge = sub.add_parser("merge-driver", help="git merge driver: %%O %%A %%B [%%P]")
    for name in ("base", "ours", "theirs"):
        merge.add_argument(name)
    merge.add_argument("path", nargs="?")
    return p


def main(argv=None):
    """Entry point."""
    args = parser().parse_args(argv)
    if args.cmd == "merge-driver":
        return cmd_merge_driver(args)
    try:
        cfg = Path(args.config).resolve()
        metrics = config.load(cfg)
        if args.metric:
            metrics = [m for m in metrics if m.name in set(args.metric)]
        os.chdir(cfg.parent)
        return {"check": cmd_check, "tighten": cmd_tighten, "report": cmd_report}[
            args.cmd
        ](args, metrics)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        print(f"virtuous-cycles: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
