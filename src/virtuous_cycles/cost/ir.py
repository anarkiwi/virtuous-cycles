"""The serialized Program that `vc-cxx-cost --emit-ir` writes, and its
composition into the cost report: `python -m virtuous_cycles.cost.ir IR.json`."""

from __future__ import annotations

import argparse
import json
import sys

from .poly import Poly
from .program import (
    CALL,
    HOIST,
    LEAF,
    SCALE,
    TARGETS,
    Cost,
    Function,
    LedgerEntry,
    Program,
    Site,
    dumps,
)

VERSION = 1


def _terms(p: Poly) -> list:
    return [[c, dict(m)] for m, c in p.terms.items()]


def _poly(terms: list) -> Poly:
    return Poly(
        {
            tuple(sorted((s, int(e)) for s, e in powers.items())): c
            for c, powers in terms
        }
    )


def _at(s: Site) -> list:
    return [s.file, s.line, s.column]


def _site(at: list) -> Site:
    return Site(at[0], int(at[1]), int(at[2]))


def _node(n: dict, kids: tuple[Cost, ...]) -> Cost:
    k = n["k"]
    return Cost(
        k,
        p=_poly(n["p"]) if k in (LEAF, SCALE) else Poly(),
        kids=kids,
        usr=n.get("usr", ""),
        callee=n.get("callee", ""),
        virtual=n.get("virtual", False),
        pure=n.get("pure", False),
        run=n.get("run", False),
        names=n.get("names", ()),
        at=_site(n["at"]) if "at" in n else Site(),
    )


def _nodes(nodes: list[dict]) -> list[Cost]:
    """Each node as a Cost of its own kind, a shared node built once."""
    built: list[Cost | None] = [None] * len(nodes)
    for root in range(len(nodes)):
        work = [root]
        while work:
            i = work[-1]
            if built[i] is not None:
                work.pop()
                continue
            kids = nodes[i].get("kids", ())
            todo = [j for j in kids if built[j] is None]
            if todo:
                work.extend(todo)
                continue
            built[i] = _node(nodes[i], tuple(built[j] for j in kids))
            work.pop()
    return built


def load(obj: dict) -> tuple[Program, list[str], bool]:
    """The program, entry patterns and breakdown flag of an IR document."""
    if obj.get("version") != VERSION:
        raise ValueError(f"unsupported IR version {obj.get('version')}")
    ir = obj["program"]
    nodes = _nodes(ir["nodes"])
    program = Program()
    for usr, f in ir["functions"].items():
        program.functions[usr] = Function(
            f["name"],
            f["plain"],
            _site(f["at"]),
            nodes[f["body"]],
            [
                LedgerEntry(x["kind"], x["function"], x["reason"], _site(x["at"]))
                for x in f["ledger"]
            ],
            None if f["recursion"] is None else _poly(f["recursion"]),
            f["loops"],
        )
    program.overriders = {u: set(o) for u, o in ir["overriders"].items()}
    program.symbols = {
        s: None if v is None else float(v) for s, v in ir["symbols"].items()
    }
    program.conflicts = set(ir["conflicts"])
    return program, list(obj["entries"]), bool(obj.get("breakdown", False))


def _number(roots: list[Cost]) -> tuple[dict[int, int], list[Cost]]:
    """Post-order numbering of the nodes under `roots`, kids first, shared
    nodes (by identity) once."""
    index: dict[int, int] = {}
    order: list[Cost] = []
    for root in roots:
        work = [(root, False)]
        while work:
            c, done = work.pop()
            if id(c) in index:
                continue
            if done:
                index[id(c)] = len(order)
                order.append(c)
                continue
            work.append((c, True))
            work.extend((k, False) for k in reversed(c.kids))
    return index, order


def _dump_node(c: Cost, index: dict[int, int]) -> dict:
    n: dict = {"k": c.k}
    if c.k in (LEAF, SCALE):
        n["p"] = _terms(c.p)
    if c.k == CALL:
        n.update(usr=c.usr, callee=c.callee, virtual=c.virtual, pure=c.pure)
    if c.k == HOIST:
        n["run"] = c.run
    if c.k == TARGETS:
        n["names"] = list(c.names)
    if c.k in (CALL, TARGETS):
        n["at"] = _at(c.at)
    if c.kids:
        n["kids"] = [index[id(k)] for k in c.kids]
    return n


def dump(program: Program) -> dict:
    """The IR "program" object of `program`."""
    usrs = sorted(program.functions)
    index, order = _number([program.functions[u].body for u in usrs])
    return {
        "functions": {
            u: {
                "name": f.name,
                "plain": f.plain,
                "at": _at(f.at),
                "body": index[id(f.body)],
                "ledger": [
                    {
                        "kind": x.kind,
                        "function": x.function,
                        "reason": x.reason,
                        "at": _at(x.at),
                    }
                    for x in f.ledger
                ],
                "recursion": None if f.recursion is None else _terms(f.recursion),
                "loops": f.loops,
            }
            for u in usrs
            for f in (program.functions[u],)
        },
        "nodes": [_dump_node(c, index) for c in order],
        "overriders": {u: sorted(o) for u, o in sorted(program.overriders.items())},
        "symbols": dict(sorted(program.symbols.items())),
        "conflicts": sorted(program.conflicts),
    }


def main(argv: list[str] | None = None) -> int:
    """Print the cost report of an IR file; 2 for a resolve error."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ir", help="IR JSON file written by vc-cxx-cost --emit-ir")
    args = parser.parse_args(argv)
    with open(args.ir, encoding="utf-8") as f:
        program, patterns, breakdown = load(json.load(f))
    try:
        entries = program.resolve(patterns, breakdown)
    except ValueError as err:
        print(f"vc-cxx-cost: {err}", file=sys.stderr)
        return 2
    sys.stdout.write(dumps(program, entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
