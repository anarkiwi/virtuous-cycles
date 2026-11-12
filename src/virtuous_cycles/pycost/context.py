"""Where the extractor is, what it reports, and how methods resolve on types."""

import functools
import os
import re

from mypy import nodes
from mypy.types import (
    Instance,
    LiteralType,
    TupleType,
    TypedDictType,
    TypeVarType,
    get_proper_type,
)

from virtuous_cycles.cost.poly import UNBOUNDED, Poly
from virtuous_cycles.cost.program import Cost, LedgerEntry, Site
from virtuous_cycles.pycost.scan import abstract, deco_name, func_of, var

VC_TAG = re.compile(r"(?:^|\.)vc\.(cost|recursion|size)$")
ZERO = Cost.leaf(Poly())


def total(costs):
    """The sum of ``costs``."""
    r = ZERO
    for c in costs:
        r = Cost.sum(r, c)
    return r


def joined(costs):
    """The join of ``costs``."""
    costs = list(costs)
    return functools.reduce(Cost.join, costs) if costs else ZERO


def instance(t):
    """The instance type method lookups on ``t`` go through."""
    t = get_proper_type(t)
    if isinstance(t, (TypedDictType, LiteralType)):
        t = get_proper_type(t.fallback)
    if isinstance(t, TupleType):
        t = get_proper_type(t.partial_fallback)
    if isinstance(t, TypeVarType):
        t = get_proper_type(t.upper_bound)
    return t if isinstance(t, Instance) else None


def lookup(t, name):
    """The definition of ``name`` on ``t``'s class, or None."""
    t = instance(t)
    sym = t.type.get(name) if t is not None else None
    return sym.node if sym is not None else None


class Context:
    """The module and function being summarised into ``out``."""

    def __init__(self, analysis, out):
        self.a = analysis
        self.out = out
        self.module = None
        self.cur = None
        self.mentioned = set()

    @property
    def src(self):
        """The current module's ``Source``."""
        return self.a.sources[self.module]

    def site(self, node):
        """Where ``node`` is, its file relative to the root."""
        path = os.path.normpath(os.path.abspath(self.a.trees[self.module].path))
        root = self.a.root
        if root and (path == root or path.startswith(root + os.sep)):
            path = os.path.relpath(path, root)
        return Site(path, node.line, node.column + 1)

    def op(self, w):
        """``w`` operations."""
        return Cost.leaf(Poly.constant(w))

    def unbounded(self, kind, reason, node):
        """``?``, with a ledger entry."""
        if self.cur is not None:
            self.cur.ledger.append(
                LedgerEntry(kind, self.cur.name, reason, self.site(node))
            )
        return Cost.leaf(Poly.symbol(UNBOUNDED))

    def parsed(self, text, node):
        """An annotation's polynomial; ``?`` and a ledger entry if it has none."""
        p = Poly.parse(str(text))
        if p is None:
            return self.unbounded("annotation", f'cannot parse "{text}"', node).p
        for m in p.terms:
            self.mentioned.update(s for s, _ in m)
        if p.degree(UNBOUNDED):
            self.unbounded("annotation", f"annotated as unbounded: {text}", node)
        return p

    def text(self, node):
        """``node``'s source text."""
        return self.src.text(node)

    def pragmas(self, s):
        """The ``# vc:`` pragmas on statement ``s``."""
        return {p.tag: p for p in self.src.pragmas.get(s.line, ())}

    def typeof(self, e):
        """``e``'s type, or None."""
        t = self.a.types.get(e)
        return get_proper_type(t) if t is not None else None

    def var_of(self, e):
        """The variable ``e`` names, attributes of instances included."""
        v = var(e)
        if v is None and isinstance(e, nodes.MemberExpr):
            node = lookup(self.typeof(e.expr), e.name)
            v = node if isinstance(node, nodes.Var) else None
        return v

    def decorations(self, f):
        """``{tag: argument}`` of the ``vc`` decorators on ``f``."""
        d = self.a.decorator.get(id(f))
        out = {}
        for x in d.decorators if d else ():
            m = VC_TAG.search(deco_name(x))
            if m and isinstance(x, nodes.CallExpr) and x.args:
                arg = x.args[0]
                if isinstance(arg, (nodes.StrExpr, nodes.IntExpr)):
                    out[m[1]] = arg.value
        return out

    def dispatch(self, t, name):
        """Every concrete definition a call of ``name`` on ``t`` can run."""
        t = instance(t)
        first = lookup(t, name)
        if first is None:
            return []
        f = func_of(first)
        if t.type.is_final or getattr(f, "is_final", False):
            return [first]
        out = {id(first): first}
        for sub in self.a.subclasses.get(t.type.fullname, []) + self.a.implementers(
            t.type
        ):
            sym = sub.get(name)
            if sym is not None and sym.node is not None:
                out.setdefault(id(sym.node), sym.node)
        return [n for n in out.values() if not abstract(n)]

    def user_method(self, t, name):
        """True if a call of ``name`` on ``t`` can reach analysed code."""
        return any(self.a.analysed(n) for n in self.dispatch(t, name))
