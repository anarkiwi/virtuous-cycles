"""Reachability over Infer's call graph (``infer debug --procedures-callees``)."""

import re
from fnmatch import fnmatchcase

PROC_ID = re.compile(r"(\(\d+\)|\{\d+\})$")
OPERATORS = sorted(
    "() [] ->* -> <<= >>= <=> << >> <= >= == != && || ++ -- += -= *= /= %= &= "
    "|= ^= + - * / % & | ^ ~ ! = < > ,".split(),
    key=len,
    reverse=True,
)
WORD = re.compile(r"\w")


def operator_len(name, i):
    """Length of the C++ operator token at ``name[i:]`` (after ``operator``).

    Of the tokens that match, the longest is taken unless it leaves more
    ``>`` than ``<`` behind, as ``operator<`` followed by a template does.
    """
    fits = [t for t in OPERATORS if name.startswith(t, i)]
    for tok in fits:
        rest = name[i + len(tok) :]
        excess = rest.count(">") - rest.count("->") - rest.count("<")
        if tok[0] not in "<>" or excess <= 0 or tok is fits[-1]:
            return len(tok)
    return 0


def scan(name):
    """Top-level ``(`` and ``,`` positions, outside template brackets."""
    parens, commas, depth, i = [], [], 0, 0
    while i < len(name):
        if (
            name.startswith("operator", i)
            and (i == 0 or not WORD.match(name[i - 1]))
            and not WORD.match(name[i + 8 : i + 9] or " ")
        ):
            i += 8 + operator_len(name, i + 8)
            continue
        ch = name[i]
        depth += (ch == "<") - (ch == ">")
        if depth == 0 and ch == "(":
            parens.append(i)
        elif depth == 0 and ch == ",":
            commas.append(i)
        i += 1
    return parens, commas


def plain(header):
    """A procedure header as ``procedure_id`` and callee lists spell it."""
    name = PROC_ID.sub("", header.strip()).removeprefix("class ")
    parens = [p for p in scan(name)[0] if p > 0]
    return name[: parens[0]] if parens else name


def split_callees(text):
    """Split a callee list on commas outside template brackets."""
    bounds = [-1, *scan(text)[1], len(text)]
    parts = (text[a + 1 : b].strip() for a, b in zip(bounds, bounds[1:]))
    return [p for p in parts if p]


def parse(lines):
    """Map each procedure to its callees from ``infer debug`` output."""
    graph, name = {}, None
    for line in lines:
        if line.strip() and not line.startswith(" "):
            name = plain(line)
            graph.setdefault(name, set())
        elif line.startswith("  callees:") and name is not None:
            graph[name].update(split_callees(line[len("  callees:") :]))
    return graph


def reached(graph, roots):
    """Procedures reachable from any procedure matching a ``roots`` glob."""
    stack = []
    for root in roots:
        hits = [n for n in graph if fnmatchcase(n, root)]
        if not hits:
            raise ValueError(f"call graph has no procedure matching root {root!r}")
        stack.extend(hits)
    seen = set()
    while stack:
        n = stack.pop()
        if n not in seen:
            seen.add(n)
            stack.extend(graph.get(n, ()))
    return seen
