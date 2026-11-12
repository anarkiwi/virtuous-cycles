"""Polynomials with non-negative coefficients over named symbols.

Symbols are non-negative, so the coefficient-wise maximum of two polynomials
bounds the larger of their values (`join`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable

UNBOUNDED = "?"

Monomial = tuple[tuple[str, int], ...]

_SPACE = " \t\n\v\f\r"
_STOD = re.compile(
    r"[ \t\n\v\f\r]*[+-]?(?:"
    r"(0[xX](?:[0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?|\.[0-9a-fA-F]+)(?:[pP][+-]?[0-9]+)?)"
    r"|((?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)"
    r"|((?i:inf(?:inity)?|nan(?:\([0-9A-Za-z_]*\))?)))"
)


def stod(text: str, pos: int = 0) -> tuple[float, int]:
    """`std::stod` of `text[pos:]`: the value and the end of its longest
    `strtod` prefix; ValueError when there is none or it overflows."""
    m = _STOD.match(text, pos)
    if not m:
        raise ValueError(f"stod: no conversion of {text[pos:]!r}")
    body = m.group(0).lstrip(_SPACE)
    if m.group(1):
        try:
            value = float.fromhex(body)
        except OverflowError as err:
            raise ValueError(f"stod: {body} out of range") from err
    elif m.group(2):
        value = float(body)
    else:
        value = float(body.split("(")[0])
    if math.isinf(value) and not m.group(3):
        raise ValueError(f"stod: {body} out of range")
    return value, m.end()


def number(c: float) -> str:
    """A coefficient as C++ prints it: `%.0f` when integral and < 1e15."""
    return f"{c:.0f}" if float(c).is_integer() and c < 1e15 else f"{c:g}"


def _ceil(x: float) -> float:
    return float(math.ceil(x)) if math.isfinite(x) else x


def _total(m: Monomial) -> int:
    return sum(e for _, e in m)


class Poly:
    """An immutable polynomial: monomial -> coefficient (> 0), in C++
    `std::map<Monomial, double>` order."""

    __slots__ = ("terms",)

    def __init__(self, terms: dict[Monomial, float] | None = None):
        self.terms: dict[Monomial, float] = dict(
            sorted((m, float(c)) for m, c in (terms or {}).items() if c > 0)
        )

    @staticmethod
    def _sum(acc: dict[Monomial, float], m: Monomial, c: float) -> None:
        if c > 0:
            acc[m] = acc.get(m, 0.0) + c

    @staticmethod
    def constant(c: float) -> Poly:
        """The constant `c` (zero when `c <= 0`)."""
        return Poly({(): c})

    @staticmethod
    def symbol(name: str) -> Poly:
        """The symbol `name`."""
        return Poly({((name, 1),): 1.0})

    @staticmethod
    def capacity(value: float) -> Poly:
        """A capacity known only by its value: `#value`, until `name`."""
        return Poly.symbol("#" + number(value))

    def name(self, values: dict[str, float | None]) -> Poly:
        """Each `#value` replaced by the one symbol of `values` with that
        value, or by the value itself when there is none or more than one."""
        unique: dict[float, str] = {}
        shared: set[float] = set()
        for s, v in sorted(values.items()):
            if v is not None:
                if v in unique:
                    shared.add(v)
                else:
                    unique[v] = s
        r = Poly()
        for m, c in self.terms.items():
            t = Poly.constant(c)
            for s, e in m:
                sym, log = s, False
                if sym.startswith("log2("):
                    sym = sym[5:]
                    if sym.endswith(")"):
                        sym, log = sym[:-1], True
                f = Poly.symbol(s)
                if sym.startswith("#"):
                    v = stod(sym, 1)[0]
                    f = (
                        Poly.constant(v)
                        if v not in unique or v in shared
                        else Poly.symbol(unique[v])
                    )
                    if log:
                        f = f.log2()
                for _ in range(e):
                    t = t * f
            r = r + t
        return r

    @staticmethod
    def parse(text: str) -> Poly | None:
        """Sums of products of numbers, symbols, `s^k`, `log2(s)` and
        parentheses; a `::`-qualified name keeps its last component."""
        return _Parser(text).run()

    def log2(self) -> Poly:
        """An upper bound of log2: log2 of the coefficient sum plus the
        degree-weighted `log2(s)` of each symbol (symbols are >= 1)."""
        c = self.constant_value()
        if c is not None:
            return Poly.constant(_ceil(math.log2(c)) if c > 1 else 0.0)
        r = Poly.constant(_ceil(math.log2(max(self.coefficient_sum(), 1.0))))
        deg: dict[str, int] = {}
        for m in self.terms:
            for s, e in m:
                deg[s] = max(deg.get(s, 0), e)
        for s in sorted(deg):
            sym = s if s == UNBOUNDED else f"log2({s})"
            r = r + Poly.constant(deg[s]) * Poly.symbol(sym)
        return r

    def __add__(self, other: Poly) -> Poly:
        acc = dict(self.terms)
        for m, c in other.terms.items():
            Poly._sum(acc, m, c)
        return Poly(acc)

    def __mul__(self, other: Poly) -> Poly:
        acc: dict[Monomial, float] = {}
        for ma, ca in self.terms.items():
            for mb, cb in other.terms.items():
                m = dict(ma)
                for s, e in mb:
                    m[s] = m.get(s, 0) + e
                Poly._sum(acc, tuple(sorted(m.items())), ca * cb)
        return Poly(acc)

    def join(self, other: Poly) -> Poly:
        """Coefficient-wise maximum: an upper bound of max(self, other)."""
        acc = dict(self.terms)
        for m, c in other.terms.items():
            acc[m] = max(acc.get(m, 0.0), c)
        return Poly(acc)

    @staticmethod
    def tighter(a: Poly, b: Poly) -> Poly:
        """The smaller of two bounds, by total degree then coefficient sum."""
        return b if _key(b) < _key(a) else a

    @property
    def zero(self) -> bool:
        """Whether this is the zero polynomial."""
        return not self.terms

    def constant_value(self) -> float | None:
        """The value of a constant polynomial, else None."""
        if not self.terms:
            return 0.0
        if len(self.terms) == 1 and () in self.terms:
            return self.terms[()]
        return None

    def degree(self, sym: str) -> int:
        """The largest exponent of `sym`."""
        return max((dict(m).get(sym, 0) for m in self.terms), default=0)

    def total_degree(self) -> int:
        """The largest total degree of a term."""
        return max(map(_total, self.terms), default=0)

    def coefficient_sum(self) -> float:
        """The sum of the coefficients, added in term order."""
        s = 0.0
        for c in self.terms.values():
            s += c
        return s

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Poly) and self.terms == other.terms

    def __hash__(self) -> int:
        return hash(tuple(self.terms.items()))

    def __repr__(self) -> str:
        return f"Poly({str(self)!r})"

    def __str__(self) -> str:
        if not self.terms:
            return "0"
        out = []
        for m, c in sorted(self.terms.items(), key=lambda t: -_total(t[0])):
            term = number(c) if not m or c != 1 else ""
            for s, e in m:
                term += ("*" if term else "") + s + (f"^{e}" if e > 1 else "")
            out.append(term)
        return " + ".join(out)


def _key(p: Poly) -> tuple[int, float]:
    return p.total_degree(), p.coefficient_sum()


def _ident_start(c: str) -> bool:
    return c.isascii() and (c.isalpha() or c == "_")


def _ident_char(c: str) -> bool:
    return c.isascii() and (c.isalnum() or c == "_")


class _Parser:
    """Recursive descent over sum := product ('+' product)*,
    product := factor ('*' factor)*, factor := base ('^' digits)?."""

    def __init__(self, text: str):
        self.text, self.pos = text, 0

    def run(self) -> Poly | None:
        """The whole text as a polynomial, or None."""
        p = self.sum()
        self.skip()
        return p if p is not None and self.pos == len(self.text) else None

    def skip(self) -> None:
        """Skip C-locale whitespace."""
        while self.pos < len(self.text) and self.text[self.pos] in _SPACE:
            self.pos += 1

    def eat(self, c: str) -> bool:
        """Consume `c` after whitespace, if it is next."""
        self.skip()
        if self.text.startswith(c, self.pos):
            self.pos += 1
            return True
        return False

    def ident(self) -> str:
        """An identifier path: `::` keeps the last component, `.`/`->` all."""
        text, name = self.text, ""
        while True:
            start = self.pos
            while self.pos < len(text) and _ident_char(text[self.pos]):
                self.pos += 1
            name += text[start : self.pos]
            sep = next(
                (len(s) for s in ("::", "->", ".") if text.startswith(s, self.pos)),
                0,
            )
            if (
                not sep
                or self.pos + sep >= len(text)
                or not _ident_start(text[self.pos + sep])
            ):
                return name
            name = (
                "" if text[self.pos] == ":" else name + text[self.pos : self.pos + sep]
            )
            self.pos += sep

    def chain(self, op: str, item: Callable[[], Poly | None]) -> Poly | None:
        """`item (op item)*`, summed for `+` and multiplied for `*`."""
        p = item()
        while p is not None and self.eat(op):
            q = item()
            if q is None:
                return None
            p = p + q if op == "+" else p * q
        return p

    def sum(self) -> Poly | None:
        """A sum of products."""
        return self.chain("+", self.product)

    def product(self) -> Poly | None:
        """A product of factors."""
        return self.chain("*", self.factor)

    def call(self) -> Poly | None:
        """The parenthesised sum after a `(` or `log2(`."""
        p = self.sum()
        return p if p is not None and self.eat(")") else None

    def base(self) -> Poly | None:
        """A number, `?`, symbol, `log2(sum)` or `(sum)`."""
        self.skip()
        text = self.text
        c = text[self.pos : self.pos + 1]
        if self.eat("("):
            return self.call()
        if "0" <= c <= "9":
            value, self.pos = stod(text, self.pos)
            while self.pos < len(text) and text[self.pos] in "uUlL\0":
                self.pos += 1
            return Poly.constant(value)
        if self.eat("?"):
            return Poly.symbol(UNBOUNDED)
        if not _ident_start(c):
            return None
        name = self.ident()
        if name == "log2" and self.eat("("):
            arg = self.call()
            return None if arg is None else arg.log2()
        return Poly.symbol(name)

    def factor(self) -> Poly | None:
        """A base, optionally raised to a non-negative integer power."""
        base = self.base()
        if base is None or not self.eat("^"):
            return base
        self.skip()
        text, start = self.text, self.pos
        while self.pos < len(text) and "0" <= text[self.pos] <= "9":
            self.pos += 1
        if start == self.pos:
            return None
        r = Poly.constant(1)
        for _ in range(int(text[start : self.pos])):
            r = r * base
        return r
