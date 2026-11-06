"""Facebook Infer cost adapter over ``costs-report.json``."""

import json
import math
import re

from tqdm import tqdm

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


@register("infer-cost")
def infer_cost(options):
    """Per-procedure cost from Infer's ``costs-report.json``.

    Keys come from the ``key`` template; procedures sharing a key keep the
    worst value. See docs/adapters.md for the options.
    """
    report = options.get("report", "infer-out/costs-report.json")
    with open(report, encoding="utf-8") as f:
        entries = json.load(f)
    mode = options.get("value", "degree")
    if mode not in ("degree", "polynomial"):
        raise ValueError(f"infer-cost: value must be degree or polynomial: {mode!r}")
    template = options.get("key", "{procedure_id}")
    field = options.get("cost", "exec_cost")
    symbols, default = options.get("symbols", {}), options.get("default")
    out, unknown = {}, 0
    for entry in tqdm(
        entries, desc="infer-cost", unit="proc", disable=None, leave=False
    ):
        cost = entry[field]
        if cost["hum"]["hum_degree"] == "Top":
            value, unknown = math.inf, unknown + 1
        elif cost["hum"]["hum_degree"] == "Unreachable":
            value = 0.0
        elif mode == "degree":
            value = cost.get("degree", 0) / 100
        else:
            value = Polynomial(
                cost["hum"]["hum_polynomial"], symbols, default
            ).evaluate()
        key = template.format(**entry, **entry.get("loc", {}))
        out[key] = max(value, out.get(key, -math.inf))
    out[options.get("unknown_key", "infer-cost:unknown")] = float(unknown)
    return out
