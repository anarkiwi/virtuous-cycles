"""Sizes and integer bounds of expressions, range trip counts and generator yields."""

import math

from mypy import nodes
from mypy.types import Instance, LiteralType, TupleType, UnpackType, get_proper_type

from virtuous_cycles.cost.poly import Poly
from virtuous_cycles.pycost.context import Context
from virtuous_cycles.pycost.scan import SAME_SIZE, SAME_SIZE_METHODS, children, func_of

LOOP_TAGS = ("bound", "total", "run_total")
IMMUTABLE = {
    "builtins.int",
    "builtins.bool",
    "builtins.str",
    "builtins.bytes",
    "builtins.tuple",
    "builtins.frozenset",
    "builtins.range",
}


def _both(a, b, f):
    return f(a, b) if a is not None and b is not None else None


def _single(p):
    return (p,) if p is not None else None


def _constants(lb, rb):
    return (
        lb.constant_value() if lb is not None else None,
        rb.constant_value() if rb is not None else None,
    )


def _minus(lb, rc):
    lc = lb.constant_value() if lb is not None else None
    if lc is not None and rc is not None:
        return Poly.constant(max(0.0, lc - rc))
    return lb


def _floordiv(lb, rc):
    lc = lb.constant_value() if lb is not None else None
    if lc is not None and rc is not None and rc > 0:
        return Poly.constant(math.floor(lc / rc))
    return lb


def _shift_right(lb, rc):
    lc = lb.constant_value() if lb is not None else None
    if lc is None or rc is None or rc < 0:
        return lb
    return Poly.constant(math.floor(math.ldexp(lc, -int(rc))))


EXACT_RIGHT = {"-": _minus, "//": _floordiv, ">>": _shift_right}
EXACT_OPS = {"+": int.__add__, "-": int.__sub__, "*": int.__mul__}


def _shift_left(lb, rb):
    rc = _constants(lb, rb)[1]
    return _both(lb, rc, lambda p, c: p * Poly.constant(math.ldexp(1.0, int(c))))


def _mask(lb, rb):
    if lb is None or rb is None:
        return rb if lb is None else lb
    return Poly.tighter(lb, rb)


def _mod(lb, rb):
    rc = _constants(lb, rb)[1]
    return _mask(lb, Poly.constant(rc - 1) if rc is not None and rc > 0 else rb)


INT_OPS = {
    "+": lambda a, b: _both(a, b, Poly.__add__),
    "*": lambda a, b: _both(a, b, Poly.__mul__),
    "<<": _shift_left,
    "%": _mod,
    "&": _mask,
}


class Bounds(Context):
    """Bounds of values: a container's length and its elements', an integer's
    value, the trip count of a ``range`` and the items a generator yields."""

    def __init__(self, analysis, out):
        super().__init__(analysis, out)
        self.yields_memo = {}

    def size(self, e):
        """Upper bound of ``e``'s length (a container) or value (an integer)."""
        s = self.shape(e) if e is not None else None
        return s[0] if s else None

    def meta_shape(self, meta, node):
        """A declaration's bounds as polynomials."""
        return tuple(None if x is None else self.parsed(x, node) for x in meta.shape)

    def shape(self, e):
        """Bounds of ``e``: its value or length, then its elements', ..."""
        f = self._SHAPE.get(type(e))
        s = f(self, e) if f is not None else None
        if s is not None:
            return s
        ty = self.typeof(e)
        if isinstance(ty, TupleType) and not any(
            isinstance(x, UnpackType) for x in ty.items
        ):
            return (Poly.constant(len(ty.items)),)
        if isinstance(ty, LiteralType) and isinstance(ty.value, (int, str)):
            v = ty.value
            return (Poly.constant(max(0, v) if isinstance(v, int) else len(v)),)
        return _single(self.int_bound(e))

    def _inner(self, e):
        return self.shape(e.expr)

    def _display(self, e):
        n = Poly.constant(sum(not isinstance(x, nodes.StarExpr) for x in e.items))
        for x in e.items:
            if isinstance(x, nodes.StarExpr):
                s = self.size(x.expr)
                if s is None:
                    return None
                n = n + s
        return (n,)

    def _dict(self, e):
        n = Poly.constant(sum(k is not None for k, _ in e.items))
        for k, v in e.items:
            if k is None:
                s = self.size(v)
                if s is None:
                    return None
                n = n + s
        return (n,)

    def _literal(self, e):
        return (Poly.constant(len(e.value)),)

    def _int(self, e):
        return (Poly.constant(max(0, e.value)),)

    def _generator(self, e):
        n = Poly.constant(1)
        for seq in e.sequences:
            s = self.size(seq)
            if s is None:
                return None
            n = n * s
        return (n,)

    def _listcomp(self, e):
        return self._generator(e.generator)

    def _index(self, e):
        s = self.shape(e.base)
        if isinstance(e.index, nodes.SliceExpr):
            return s
        return s[1:] if s and len(s) > 1 else None

    def _name(self, e):
        v = self.var_of(e)
        return self.var_shape(v, e) if v is not None else None

    def var_shape(self, v, e):
        """What is known of variable ``v``'s value and elements."""
        meta = self.a.decl.get(id(v))
        if meta is not None and meta.shape:
            return self.meta_shape(meta, e)
        if id(v) in self.a.final:
            name = self.a.final[id(v)]
            self.out.symbol(name, self.a.known.get(name))
            return (Poly.symbol(name),)
        if self.a.assigns.get(id(v)) != 1:
            return None
        if id(v) in self.a.rvalue:
            t = get_proper_type(v.type) if v.type is not None else None
            if (
                not isinstance(t, Instance)
                or t.type.fullname in IMMUTABLE
                or id(v) not in self.a.escaped
            ):
                return self.shape(self.a.rvalue[id(v)])
            return None
        return self._bound_var(*self.a.binding.get(id(v), (None, None)))

    def _bound_var(self, kind, seq):
        """What a loop variable bound to ``seq`` is known to be."""
        if kind == "count":
            n = self.size(seq.args[0])
            start = self.size(seq.args[1]) if len(seq.args) > 1 else Poly()
            return _both(n, start, lambda a, b: (a + b,))
        if kind is None:
            return None
        if _callee(seq) == "builtins.range":
            return _single(self.range_limit(seq.args))
        s = self.shape(seq)
        return s[1:] if s and len(s) > 1 else None

    def _call(self, e):
        """Bounds of what call ``e`` returns."""
        if e.analyzed is not None:
            return self.shape(e.analyzed)
        name, args = _callee(e), e.args
        if name in self._CALL_SHAPE:
            return self._CALL_SHAPE[name](self, args)
        if name in SAME_SIZE and args:
            s = self.shape(args[0])
            return s if name != "builtins.enumerate" else (s[:1] if s else None)
        return self._returned(e)

    def _returned(self, e):
        """Bounds of what a call ``e`` of a method or analysed function returns."""
        c = e.callee
        node = getattr(c, "node", None)
        if isinstance(c, nodes.MemberExpr) and node is None:
            t = self.typeof(c.expr)
            if c.name in SAME_SIZE_METHODS and not self.user_method(t, c.name):
                return self.shape(c.expr)
            cands = self.dispatch(t, c.name)
            node = cands[0] if len(cands) == 1 else None
        f = func_of(node)
        if f is None or id(f) not in self.a.funcs:
            return None
        tags = self.decorations(f)
        if "size" in tags:
            return (self.parsed(tags["size"], e),)
        meta = self.a.ret.get(id(f))
        if meta is not None and meta.shape:
            return self.meta_shape(meta, e)
        if isinstance(f, nodes.FuncDef) and (f.is_generator or f.is_async_generator):
            return _single(self.yields(f))
        return None

    def _range(self, args):
        return _single(self.range_trip(args))

    def _filter(self, args):
        return self.shape(args[1]) if len(args) == 2 else None

    def _tightest(self, seqs):
        best = None
        for x in seqs:
            s = self.size(x)
            if s is not None:
                best = s if best is None else Poly.tighter(best, s)
        return _single(best)

    def _map(self, args):
        return self._tightest(args[1:])

    def _len(self, args):
        return _single(self.size(args[0])) if args else None

    def _min(self, args):
        return self._minmax(args, Poly.tighter)

    def _max(self, args):
        return self._minmax(args, Poly.join)

    def _minmax(self, args, combine):
        """``min``/``max`` of integers: the tighter bound, or both."""
        if len(args) < 2:
            return None
        best = None
        for a in args:
            p = self.size(a)
            if p is None:
                if combine is Poly.join:
                    return None
            else:
                best = p if best is None else combine(best, p)
        return _single(best)

    def int_bound(self, e):
        """Bounds of integer arithmetic, as for C++ ``bound``."""
        if isinstance(e, nodes.UnaryExpr) and e.op in ("-", "+"):
            c = self.const_int(e)
            return Poly.constant(max(0, c)) if c is not None else None
        if isinstance(e, nodes.ConditionalExpr):
            return _both(self.size(e.if_expr), self.size(e.else_expr), Poly.join)
        if isinstance(e, nodes.OpExpr) and e.op in EXACT_RIGHT:
            return EXACT_RIGHT[e.op](self.size(e.left), self.const_int(e.right))
        if isinstance(e, nodes.OpExpr) and e.op in INT_OPS:
            return INT_OPS[e.op](self.size(e.left), self.size(e.right))
        return None

    def const_int(self, e, final=False, seen=frozenset()):
        """``e``'s exact integer value, or None; a ``Final`` name only with
        ``final`` (elsewhere it is a symbol)."""
        if isinstance(e, nodes.IntExpr):
            return e.value
        if isinstance(e, nodes.UnaryExpr) and e.op in ("-", "+"):
            e = nodes.OpExpr(e.op, nodes.IntExpr(0), e.expr)
        if isinstance(e, nodes.OpExpr):
            a = self.const_int(e.left, final, seen) if e.op in EXACT_OPS else None
            b = self.const_int(e.right, final, seen) if a is not None else None
            return None if b is None else EXACT_OPS[e.op](a, b)
        v = self.var_of(e)
        if v is not None and v.is_final and isinstance(v.final_value, int):
            return v.final_value if final else None
        if v is None or id(v) in seen or self.a.assigns.get(id(v)) != 1:
            return None
        rv = self.a.rvalue.get(id(v))
        return None if rv is None else self.const_int(rv, final, seen | {id(v)})

    def _range_parts(self, args):
        """``(start, stop, step)`` of ``range(*args)``."""
        if len(args) == 1:
            return None, args[0], 1
        step = self.const_int(args[2], final=True) if len(args) > 2 else 1
        return args[0], args[1], step

    def range_trip(self, args):
        """The length of ``range(*args)``."""
        if not args:
            return None
        start, stop, step = self._range_parts(args)
        if step is None:
            return None
        if step == 0:
            return Poly.constant(0)
        hi, lo = (stop, start) if step > 0 else (start, stop)
        hc = self.const_int(hi)
        lc = self.const_int(lo) if lo is not None else 0
        if hc is not None and lc is not None:
            return Poly.constant(max(0, math.ceil((hc - lc) / abs(step))))
        h = self.size(hi)
        if h is None:
            return None
        return h + Poly.constant(-lc) if lc is not None and lc < 0 else h

    def range_limit(self, args):
        """Upper bound of the values of ``range(*args)``."""
        start, stop, step = self._range_parts(args)
        if step is None:
            return None
        return self.size(stop if step > 0 else start)

    def yields(self, f):
        """How many items generator ``f`` yields, or None."""
        key = id(f)
        if key in self.yields_memo:
            return self.yields_memo[key]
        self.yields_memo[key] = None
        saved, self.module = self.module, self.a.funcs[key][2]
        try:
            y = self.yield_block(f.body)
        finally:
            self.module = saved
        self.yields_memo[key] = y
        return y

    def yield_block(self, b):
        """Items the statements of ``b`` yield."""
        if b is None or b.is_unreachable:
            return Poly()
        r = Poly()
        for s in b.body:
            f = self._YIELD.get(type(s), Bounds.yield_expr)
            y = f(self, s)
            if y is None:
                return None
            r = r + y
        return r

    def _yield_loop(self, s):
        body = self.yield_block(s.body)
        rest = self.yield_block(s.else_body)
        if body is None or rest is None:
            return None
        if body.zero:
            return rest
        tags = self.pragmas(s)
        arg = next((tags[t].arg for t in LOOP_TAGS if t in tags), None)
        if arg is not None:
            trip = Poly.parse(arg)
        else:
            trip = self.size(s.expr) if isinstance(s, nodes.ForStmt) else None
        return None if trip is None else trip * body + rest

    def _yield_branches(self, bodies, r=Poly()):
        for b in bodies:
            y = self.yield_block(b)
            if y is None or r is None:
                return None
            r = r.join(y)
        return r

    def _yield_if(self, s):
        return self._yield_branches(s.body, self.yield_block(s.else_body))

    def _yield_try(self, s):
        alt = self._yield_branches(s.handlers, self.yield_block(s.else_body))
        parts = [self.yield_block(s.body), self.yield_block(s.finally_body), alt]
        return None if any(p is None for p in parts) else sum(parts, Poly())

    def _yield_with(self, s):
        return self.yield_block(s.body)

    def _yield_match(self, s):
        return self._yield_branches(s.bodies)

    def _yield_none(self, _s):
        return Poly()

    def yield_expr(self, n):
        """Items the expressions under ``n`` yield."""
        r = Poly()
        for x, _ in children(n):
            if x is None or isinstance(x, (nodes.LambdaExpr, nodes.Block)):
                continue
            if isinstance(x, nodes.YieldExpr):
                r = r + Poly.constant(1)
            elif isinstance(x, nodes.YieldFromExpr):
                s = self.size(x.expr)
                if s is None:
                    return None
                r = r + s
            y = self.yield_expr(x)
            if y is None:
                return None
            r = r + y
        return r

    _SHAPE = {
        nodes.CastExpr: _inner,
        nodes.AssertTypeExpr: _inner,
        nodes.ListExpr: _display,
        nodes.TupleExpr: _display,
        nodes.SetExpr: _display,
        nodes.DictExpr: _dict,
        nodes.StrExpr: _literal,
        nodes.BytesExpr: _literal,
        nodes.IntExpr: _int,
        nodes.ListComprehension: _listcomp,
        nodes.SetComprehension: _listcomp,
        nodes.GeneratorExpr: _generator,
        nodes.DictionaryComprehension: _generator,
        nodes.IndexExpr: _index,
        nodes.NameExpr: _name,
        nodes.MemberExpr: _name,
        nodes.CallExpr: _call,
    }
    _CALL_SHAPE = {
        "builtins.range": _range,
        "builtins.filter": _filter,
        "builtins.zip": _tightest,
        "builtins.map": _map,
        "builtins.len": _len,
        "builtins.min": _min,
        "builtins.max": _max,
    }
    _YIELD = {
        nodes.ForStmt: _yield_loop,
        nodes.WhileStmt: _yield_loop,
        nodes.IfStmt: _yield_if,
        nodes.TryStmt: _yield_try,
        nodes.WithStmt: _yield_with,
        nodes.MatchStmt: _yield_match,
        nodes.FuncDef: _yield_none,
        nodes.Decorator: _yield_none,
        nodes.ClassDef: _yield_none,
    }


def _callee(e):
    """The qualified name call ``e`` calls, or ''."""
    if not isinstance(e, nodes.CallExpr):
        return ""
    return getattr(e.callee, "fullname", None) or ""
