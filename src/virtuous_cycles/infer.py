"""Facebook Infer cost adapter over ``costs-report.json``."""

import json
import math
import os
import re
import subprocess

from tqdm import tqdm

from virtuous_cycles import callgraph
from virtuous_cycles.adapters import register

SUPERSCRIPTS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
FUNCTIONS = {
    "log": lambda x: math.log2(x) if x > 1 else 0.0,
    "min": min,
    "max": max,
}
TOKEN = re.compile(
    rf"(?P<num>\d+)(?![\w\[])|(?P<sup>[{SUPERSCRIPTS}]+)"
    r"|(?P<op>[-+⋅×.,()^]|x(?=\s))(?!>)"
)
CALL = re.compile(r"(log|min|max)\(")
OPERAND_END = " \t,)⋅×^" + SUPERSCRIPTS
ANON = re.compile(r"(?P<head>anonymous_namespace_)(?P<path>[^:]+)")
LAMBDA = re.compile(r"(?P<site>lambda_[^:<>(),]+:\d+)_[0-9a-f]{8}\b")
HASHED = re.compile(r"<[0-9a-f]{12,16}>")
LOCATED = re.compile(r"\([a-z_]+_at_[^()]*\)")
COLLAPSED = "\0"
ENCLOSING = re.compile(rf"<[^<>]*{COLLAPSED}[^<>]*>")


class Polynomial:
    """Evaluate Infer's human-readable cost polynomial (``hum_polynomial``).

    Sums of products of integers, ``log``/``min``/``max`` calls, bounds and
    symbols. A symbol is its source text (``n``, ``this->len``, ``(*p).size``),
    valued from ``symbols`` or else ``default``.
    """

    def __init__(self, text, symbols, default=None):
        self.text, self.pos = text, 0
        self.symbols, self.default = symbols, default

    def evaluate(self):
        """The polynomial's value; ``⊤`` is infinite and ``⊥`` zero."""
        stripped = self.text.strip()
        if stripped == "⊤":
            return math.inf
        if stripped == "⊥":
            return 0.0
        value = self.expr()
        self.skip()
        if self.pos != len(self.text):
            self.fail("trailing input")
        return value

    def fail(self, why):
        """Raise a parse error pointing at the current position."""
        raise ValueError(f"cannot evaluate {self.text!r} at {self.pos}: {why}")

    def skip(self):
        """Advance past whitespace."""
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def peek(self):
        """The next token as ``(kind, text, end)``, or None before a symbol."""
        self.skip()
        m = TOKEN.match(self.text, self.pos)
        return (m.lastgroup, m.group(m.lastgroup), m.end()) if m else None

    def accept(self, *ops):
        """Consume and return the next operator if it is one of ``ops``."""
        tok = self.peek()
        if tok and tok[0] == "op" and tok[1] in ops:
            self.pos = tok[2]
            return tok[1]
        return None

    def expr(self):
        """``term (('+' | '-') term)*``."""
        value = self.term()
        while op := self.accept("+", "-"):
            rhs = self.term()
            value = value + rhs if op == "+" else value - rhs
        return value

    def term(self):
        """``factor (op factor)*``; ``.`` and ``x`` are ASCII-locale products."""
        value = self.factor()
        while self.accept("⋅", "×", ".", "x"):
            value *= self.factor()
        return value

    def factor(self):
        """``'-'? atom exponent?``."""
        if self.accept("-"):
            return -self.factor()
        base = self.atom()
        tok = self.peek()
        if tok and tok[0] == "sup":
            self.pos = tok[2]
            exp = int(tok[1].translate(str.maketrans(SUPERSCRIPTS, "0123456789")))
            return base**exp
        if self.accept("^"):
            return base ** self.atom()
        return base

    def atom(self):
        """A number, call, parenthesised bound or symbol."""
        tok = self.peek()
        start = self.pos
        if tok and tok[0] == "num":
            self.pos = tok[2]
            return float(tok[1])
        if tok and tok[1] == "(":
            self.balanced()
            if self.at_operand_end():
                inner = self.text[start + 1 : self.pos - 1]
                return Polynomial(inner, self.symbols, self.default).evaluate()
            return self.symbol(start)
        call = CALL.match(self.text, self.pos)
        if call:
            self.pos = call.end()
            args = [self.expr()]
            while self.accept(","):
                args.append(self.expr())
            if not self.accept(")"):
                self.fail("expected ')'")
            return float(FUNCTIONS[call.group(1)](*args))
        return self.symbol(start)

    def balanced(self):
        """Skip a balanced parenthesised span starting at ``(``."""
        depth = 0
        for i in range(self.pos, len(self.text)):
            depth += {"(": 1, ")": -1}.get(self.text[i], 0)
            if depth == 0:
                self.pos = i + 1
                return
        self.fail("unbalanced '('")

    def at_operand_end(self):
        """True if the next character ends an operand."""
        return self.pos == len(self.text) or self.text[self.pos] in OPERAND_END

    def symbol(self, start):
        """Consume a symbol path, gluing on adjacent parenthesised spans."""
        while not self.at_operand_end():
            if self.text[self.pos] == "(":
                self.balanced()
            elif self.text.startswith("->", self.pos):
                self.pos += 2
            elif self.text[self.pos] in "+-":
                break
            else:
                self.pos += 1
        name = self.text[start : self.pos]
        if not name:
            self.fail("expected an operand")
        if name in self.symbols:
            return float(self.symbols[name])
        if self.default is None:
            self.fail(f"no value for symbol {name!r}")
        return float(self.default)


def mangled(path):
    """``path`` as Infer spells it in a name: ``/`` and space become ``_``."""
    return str(path).translate(str.maketrans("/ ", "__"))


def git_toplevel():
    """The enclosing git work tree of the working directory, else the directory."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return os.getcwd()


class Canonical:
    """Procedure names that do not depend on where the source was checked out.

    Infer's clang frontend writes an anonymous namespace as
    ``anonymous_namespace_<path>`` with the presumed file path, a lambda as
    ``lambda_<file>:<line>_<crc32 of its full path>``, and a function template's
    argument list longer than 40 characters as ``<fnv64 hex>``; a list naming a
    lambda or unnamed type spells that type's absolute path, so its length, and
    whether it is hashed, depend on the checkout. The anonymous namespace path is
    made relative to ``root`` or, failing that, to the longest report source file
    it ends in; the lambda's crc is dropped; an argument list that is hashed or
    names a source location becomes ``<>``, so every such instantiation of a
    template shares one key.
    """

    def __init__(self, root, files):
        self.root = mangled(str(root).rstrip("/")) + "_"
        self.files = sorted(
            {mangled(f) for f in files if f and not f.startswith("/")},
            key=len,
            reverse=True,
        )

    def path(self, match):
        """One ``anonymous_namespace_<path>`` relative to the source root."""
        path = match["path"]
        if path.startswith(self.root):
            path = path[len(self.root) :]
        elif path.startswith("_"):
            path = next((f for f in self.files if path.endswith("_" + f)), path)
        return match["head"] + path

    def __call__(self, name):
        name = LAMBDA.sub(r"\g<site>", ANON.sub(self.path, name))
        name = LOCATED.sub(COLLAPSED, HASHED.sub(COLLAPSED, name))
        while (folded := ENCLOSING.sub(COLLAPSED, name)) != name:
            name = folded
        return name.replace(COLLAPSED, "<>")


def cost_value(cost, options):
    """One procedure's cost: ``inf`` for ⊤, else its degree or polynomial."""
    degree = cost["hum"]["hum_degree"]
    if degree in ("Top", "Unreachable"):
        return math.inf if degree == "Top" else 0.0
    if options.get("value", "degree") == "degree":
        return cost.get("degree", 0) / 100
    return Polynomial(
        cost["hum"]["hum_polynomial"],
        options.get("symbols", {}),
        options.get("default"),
    ).evaluate()


@register("infer-cost")
def infer_cost(options):
    """Per-procedure cost from Infer's ``costs-report.json``.

    Keys come from the ``key`` template, made independent of the checkout
    path by :class:`Canonical`; procedures sharing a key keep the worst
    value. See docs/adapters.md for the options.
    """
    if options.get("value", "degree") not in ("degree", "polynomial"):
        raise ValueError(
            f"infer-cost: value must be degree or polynomial: {options['value']!r}"
        )
    with open(
        options.get("report", "infer-out/costs-report.json"), encoding="utf-8"
    ) as f:
        entries = json.load(f)
    canonical = Canonical(
        os.path.abspath(options.get("source_root") or git_toplevel()),
        {e.get("loc", {}).get("file") for e in entries},
    )
    if "callgraph" in options:
        with open(options["callgraph"], encoding="utf-8") as f:
            keep = callgraph.reached(callgraph.parse(f), options["roots"])
        entries = [e for e in entries if e["procedure_id"] in keep]
    template, field = options.get("key", "{procedure_id}"), options.get(
        "cost", "exec_cost"
    )
    out = {}
    for entry in tqdm(
        entries, desc="infer-cost", unit="proc", disable=None, leave=False
    ):
        key = canonical(template.format(**entry, **entry.get("loc", {})))
        out[key] = max(cost_value(entry[field], options), out.get(key, -math.inf))
    unknown = sum(math.isinf(v) for v in out.values())
    out[options.get("unknown_key", "infer-cost:unknown")] = float(unknown)
    return out
