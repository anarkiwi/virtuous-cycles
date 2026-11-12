"""Per-function cost summaries of Python modules from a mypy build."""

from mypy import nodes
from mypy.nodes import ARG_POS
from mypy.operators import op_methods, reverse_op_methods
from mypy.typevars import fill_typevars_with_any
from mypy.types import (
    AnyType,
    CallableType,
    NoneType,
    TypeType,
    UnionType,
    get_proper_type,
)

from virtuous_cycles.cost.poly import UNBOUNDED, Poly
from virtuous_cycles.cost.program import Cost, Function, Program
from virtuous_cycles.pycost.bounds import LOOP_TAGS, Bounds
from virtuous_cycles.pycost.context import ZERO, instance, joined, lookup, total
from virtuous_cycles.pycost.scan import Analysis, children, deco_name, func_of

__all__ = ["Analysis", "Extractor", "extract"]

DUNDERS = {
    "builtins.len": "__len__",
    "builtins.iter": "__iter__",
    "builtins.next": "__next__",
    "builtins.reversed": "__reversed__",
    "builtins.repr": "__repr__",
    "builtins.str": "__str__",
    "builtins.hash": "__hash__",
    "builtins.abs": "__abs__",
    "builtins.bool": "__bool__",
}
_UNTAGGED = (None, None)
SCALING = {
    "linear": lambda n: n,
    "nlogn": lambda n: n * n.log2(),
    "log": lambda n: n.log2(),
}


def _accessor(d, f):
    """True if decorator ``d`` on ``f`` is its property's ``setter``/``deleter``."""
    return (
        isinstance(d, nodes.MemberExpr)
        and d.name in ("setter", "getter", "deleter")
        and isinstance(d.expr, nodes.NameExpr)
        and d.expr.name == f.name
    )


def _is_property(node):
    if isinstance(node, nodes.OverloadedFuncDef):
        return node.is_property
    return isinstance(node, nodes.Decorator) and (
        node.var.is_property
        or any(deco_name(d) == "functools.cached_property" for d in node.decorators)
    )


class Extractor(Bounds):
    """Cost summaries of the functions of some modules, into ``out``."""

    def one(self):
        """A statement."""
        return self.op(self.a.weights.statement)

    def test(self):
        """A condition."""
        return self.op(self.a.weights.condition)

    def entry(self):
        """A function entered."""
        return self.op(self.a.weights.call)

    def run(self, module):
        """Summarise every function of ``module``."""
        self.module = module
        for f in self.a.items[module]:
            self.function(f)

    def finish(self):
        """Record the symbols annotations named."""
        for s in sorted(self.mentioned):
            if s != UNBOUNDED and not s.startswith("log2("):
                self.out.symbol(s, self.a.known.get(s))

    def function(self, f):
        """The summary of one function."""
        usr, name, _ = self.a.funcs[id(f)]
        fn = Function(name, name, self.site(f), ZERO)
        self.out.functions[usr] = fn
        self.cur = fn
        tags = self.decorations(f)
        if "cost" in tags:
            fn.body = Cost.leaf(self.parsed(tags["cost"], f))
        else:
            if "recursion" in tags:
                fn.recursion = self.parsed(tags["recursion"], f)
            fn.body = Cost.sum(self.entry(), self.block(f.body))
        self.cur = None

    def block(self, b):
        """A block's statements in sequence."""
        if b is None or b.is_unreachable:
            return ZERO
        return total(self.stmt(s) for s in b.body)

    def stmt(self, s):
        """One statement."""
        tags = self.pragmas(s)
        if "cost" in tags:
            return Cost.leaf(self.parsed(tags["cost"].arg, s))
        if "targets" in tags:
            names = [n.strip() for n in tags["targets"].arg.split(",") if n.strip()]
            return Cost.sum(self.one(), Cost.targets(names, self.site(s)))
        t = type(s)
        if t not in (nodes.ForStmt, nodes.WhileStmt):
            for tag in LOOP_TAGS:
                if tag in tags:
                    self.unbounded(
                        "annotation", "a bound on something that is not a loop", s
                    )
        return self._STMT.get(t, Extractor._one_stmt)(self, s)

    def _one_stmt(self, _s):
        """A statement with nothing more to it."""
        return self.one()

    def _nothing(self, _s):
        return ZERO

    def _loop_tags(self, s):
        tags = self.pragmas(s)
        bound = total_ = None
        for tag in LOOP_TAGS:
            if tag in tags:
                p = self.parsed(tags[tag].arg, s)
                if tag == "bound":
                    bound = p
                else:
                    total_ = (p, tag == "run_total")
        return bound, total_

    def _loop(self, s, tags, inferred, why, once, each):
        """``once`` plus the trip count times ``each``."""
        bound, total_ = tags
        if total_ is not None:
            return Cost.sum(once, Cost.hoist(Cost.scale(total_[0], each), total_[1]))
        t = bound if bound is not None else inferred
        if t is None:
            t = self.unbounded("loop", why, s).p
        return Cost.sum(once, Cost.scale(t, each))

    def _for(self, s):
        tags = self._loop_tags(s)
        t = self.typeof(s.expr)
        once = Cost.sum(self.one(), self.expr(s.expr))
        each = Cost.sum(self.test(), self.block(s.body))
        name, nxt = (
            ("__aiter__", "__anext__") if s.is_async else ("__iter__", "__next__")
        )
        if not self._generator_call(s.expr) and self.user_method(t, name):
            once = Cost.sum(once, self.method(t, name, s.expr, [], implicit=True))
            it = get_proper_type(s.inferred_iterator_type)
            gens = [_generator(func_of(n)) for n in self.dispatch(instance(t), name)]
            if not all(gens) and self.user_method(it, nxt):
                each = Cost.sum(each, self.method(it, nxt, s.expr, [], implicit=True))
        inferred = self.size(s.expr) if tags == _UNTAGGED else None
        why = f"for loop over {self.text(s.expr)} ({t}), which has no size"
        loop = self._loop(s, tags, inferred, why, once, each)
        return Cost.sum(loop, self.block(s.else_body))

    def _generator_call(self, e):
        """True if ``e`` calls only analysed generator functions."""
        if not isinstance(e, nodes.CallExpr):
            return False
        c = e.callee
        if isinstance(c, nodes.MemberExpr) and c.node is None:
            defs = self.dispatch(instance(self.typeof(c.expr)), c.name)
        else:
            defs = [getattr(c, "node", None)]
        fs = [func_of(n) for n in defs]
        return bool(fs) and all(self.a.analysed(f) and _generator(f) for f in fs)

    def _while(self, s):
        tags = self._loop_tags(s)
        cond = Cost.sum(self.test(), self.expr(s.expr))
        why = f"while loop with no bound on {self.text(s.expr)}"
        each = Cost.sum(cond, self.block(s.body))
        return Cost.sum(
            self._loop(s, tags, None, why, cond, each), self.block(s.else_body)
        )

    def _if(self, s, k=0):
        if k == len(s.expr):
            return self.block(s.else_body)
        cond = Cost.sum(self.test(), self.expr(s.expr[k]))
        return Cost.sum(cond, Cost.join(self.block(s.body[k]), self._if(s, k + 1)))

    def _expression(self, s):
        if isinstance(s.expr, (nodes.StrExpr, nodes.EllipsisExpr)):
            return ZERO
        return Cost.sum(self.one(), self.expr(s.expr))

    def _assignment(self, s):
        r = Cost.sum(self.one(), self.expr(s.rvalue))
        return Cost.sum(r, total(self._store(lv, s.rvalue) for lv in s.lvalues))

    def _augmented(self, s):
        lv = s.lvalue
        r = total(
            [
                self.one(),
                self.expr(s.rvalue),
                self._object(lv),
                self._access(lv, "__getitem__"),
                self._access(lv, "__setitem__", s.rvalue),
            ]
        )
        t = self.typeof(lv)
        name = op_methods.get(s.op)
        for m in ("__i" + name[2:], name) if name and t is not None else ():
            if lookup(t, m):
                return Cost.sum(r, self.method(t, m, lv, [s.rvalue], implicit=True))
        return r

    def _return(self, s):
        return Cost.sum(self.one(), self.expr(s.expr))

    def _raise(self, s):
        return total([self.one(), self.expr(s.expr), self.expr(s.from_expr)])

    def _assert(self, s):
        return total([self.test(), self.expr(s.expr), self.expr(s.msg)])

    def _del(self, s):
        return Cost.sum(self.one(), self._delete(s.expr))

    def _try(self, s):
        alt = self.block(s.else_body)
        r = self.block(s.body)
        for h in s.handlers:
            r = Cost.sum(r, self.test())
            alt = Cost.join(alt, self.block(h))
        return total([r, alt, self.block(s.finally_body)])

    def _with(self, s):
        enter, leave = (
            ("__aenter__", "__aexit__") if s.is_async else ("__enter__", "__exit__")
        )
        r = self.block(s.body)
        for x in s.expr:
            t = self.typeof(x)
            r = total(
                [
                    r,
                    self.one(),
                    self.expr(x),
                    self.method(t, enter, x, [], implicit=True),
                    self.method(t, leave, x, [], implicit=True),
                ]
            )
        return r

    def _match(self, s):
        r = Cost.sum(self.test(), self.expr(s.subject))
        alt = ZERO
        for guard, body in zip(s.guards, s.bodies):
            r = total([r, self.test(), self.expr(guard)])
            alt = Cost.join(alt, self.block(body))
        return Cost.sum(r, alt)

    def _decorator(self, s):
        return Cost.sum(self.one(), self.exprs(s.decorators))

    def _object(self, lv):
        """Evaluating an assignment target's object and index."""
        if isinstance(lv, nodes.IndexExpr):
            return Cost.sum(self.expr(lv.base), self.expr(lv.index))
        if isinstance(lv, nodes.MemberExpr):
            return self.expr(lv.expr)
        return ZERO

    def _access(self, lv, name, value=None):
        """Reading, writing or deleting target ``lv`` through ``name``."""
        if isinstance(lv, nodes.IndexExpr):
            return self._subscript(lv, name, value)
        t = self.typeof(lv.expr) if isinstance(lv, nodes.MemberExpr) else None
        if name == "__delitem__" or t is None or not self.prop(t, lv.name):
            return ZERO
        return self.method(
            t, lv.name, lv, [], implicit=True, setter=name == "__setitem__"
        )

    def _store(self, lv, rvalue):
        """Assigning ``rvalue`` to ``lv``."""
        if isinstance(lv, (nodes.TupleExpr, nodes.ListExpr)):
            return total(self._store(x, None) for x in lv.items)
        if isinstance(lv, nodes.StarExpr):
            return self._store(lv.expr, None)
        return Cost.sum(self._object(lv), self._access(lv, "__setitem__", rvalue))

    def _delete(self, e):
        """``del e``."""
        if isinstance(e, (nodes.TupleExpr, nodes.ListExpr)):
            return total(self._delete(x) for x in e.items)
        return Cost.sum(self._object(e), self._access(e, "__delitem__"))

    def exprs(self, xs):
        """A sequence of expressions."""
        return total(self.expr(x) for x in xs)

    def expr(self, e):
        """The cost of evaluating ``e``."""
        if e is None:
            return ZERO
        f = self._EXPR.get(type(e))
        if f is not None:
            return f(self, e)
        return self.exprs(x for x, _ in children(e) if isinstance(x, nodes.Expression))

    def _call_expr(self, e):
        if e.analyzed is not None:
            cast = isinstance(e.analyzed, nodes.CastExpr)
            return self.expr(e.analyzed) if cast else ZERO
        c = e.callee
        if isinstance(c, nodes.MemberExpr):
            callee = self.expr(c.expr)
        elif isinstance(c, (nodes.NameExpr, nodes.SuperExpr)):
            callee = ZERO
        else:
            callee = self.expr(c)
        return total([callee, self.exprs(e.args), self.call(e)])

    def _member(self, e):
        r = self.expr(e.expr)
        ty = self.typeof(e.expr)
        if self.prop(ty, e.name):
            r = Cost.sum(r, self.method(ty, e.name, e, [], implicit=True))
        return r

    def _op(self, e):
        r = Cost.sum(self.expr(e.left), self.expr(e.right))
        if e.op in ("and", "or") or e.analyzed is not None:
            return r
        return Cost.sum(r, self._operator(e.method_type, e.op, e.left, e.right))

    def _comparison(self, e):
        r = self.exprs(e.operands)
        for k, o in enumerate(e.operators):
            left, right = e.operands[k], e.operands[k + 1]
            if o in ("in", "not in"):
                r = Cost.sum(r, self._dunder(right, "__contains__", [left]))
            elif o in op_methods:
                name, rev = op_methods[o], reverse_op_methods[op_methods[o]]
                if not self.user_method(self.typeof(left), name) and self.user_method(
                    self.typeof(right), rev
                ):
                    left, right, name = right, left, rev
                r = Cost.sum(r, self._dunder(left, name, [right]))
        return r

    def _unary(self, e):
        op = self._operator(e.method_type, e.op, e.expr, None)
        return Cost.sum(self.expr(e.expr), op)

    def _index(self, e):
        if e.analyzed is not None:
            return ZERO
        r = Cost.sum(self.expr(e.base), self.expr(e.index))
        return Cost.sum(r, self._subscript(e, "__getitem__", None))

    def _conditional(self, e):
        branches = Cost.join(self.expr(e.if_expr), self.expr(e.else_expr))
        return Cost.sum(self.expr(e.cond), branches)

    def _listcomp(self, e):
        return self._comprehension(e.generator, [e.generator.left_expr])

    def _genexpr(self, e):
        return self._comprehension(e, [e.left_expr])

    def _dictcomp(self, e):
        return self._comprehension(e, [e.key, e.value])

    def _comprehension(self, g, elements):
        """Nested generator loops around ``elements``."""
        inner = Cost.sum(self.one(), self.exprs(elements))
        for k in range(len(g.sequences) - 1, -1, -1):
            each = total(
                [self.test(), inner]
                + [Cost.sum(self.test(), self.expr(c)) for c in g.condlists[k]]
            )
            seq = g.sequences[k]
            why = (
                f"comprehension over {self.text(seq)} ({self.typeof(seq)}),"
                " which has no size"
            )
            loop = self._loop(seq, _UNTAGGED, self.size(seq), why, ZERO, each)
            inner = Cost.sum(self.expr(seq), loop)
        return inner

    def _operator(self, mt, op, recv, other):
        """An operator's method: ``recv``'s, or the reflected one of ``other``."""
        d = getattr(mt, "definition", None) if isinstance(mt, CallableType) else None
        if d is None:
            return ZERO
        rev = reverse_op_methods.get(op_methods.get(op, ""))
        if d.name == rev and other is not None:
            recv, other = other, recv
        args = [] if other is None else [other]
        if self.a.analysed(d):
            return self.method(self.typeof(recv), d.name, recv, args, implicit=True)
        return self._dunder(recv, d.name, args, d.fullname)

    def _dunder(self, recv, name, args, fullname=None):
        """The method ``name`` an operator runs on ``recv``."""
        t = self.typeof(recv)
        if self.user_method(t, name):
            return self.method(t, name, recv, args, implicit=True)
        if fullname is None:
            fullname = getattr(lookup(t, name), "fullname", None)
        if fullname is None:
            return ZERO
        return self.system(fullname, recv, args, [], recv, implicit=True)

    def _subscript(self, e, name, value):
        """``e.base[e.index]`` through ``name``."""
        t = self.typeof(e.base)
        args = [e.index] + ([value] if value is not None else [])
        if self.user_method(t, name):
            return self.method(t, name, e.base, args, implicit=True)
        if isinstance(e.index, nodes.SliceExpr):
            n = self.size(e.base)
            if n is None:
                return self.unbounded(
                    "library",
                    f"slice of {self.text(e.base)} ({t}), which has no size",
                    e,
                )
            return Cost.leaf(n)
        node = lookup(t, name)
        if node is not None:
            return self.system(node.fullname, e.base, [e.index], [], e, implicit=True)
        return ZERO

    def call(self, e):
        """The callee's cost for call ``e``."""
        c = e.callee
        pos = [a for a, k in zip(e.args, e.arg_kinds) if k == ARG_POS]
        if isinstance(c, nodes.SuperExpr):
            d = getattr(self.typeof(c), "definition", None)
            return self.direct(d, c, pos, e.args, e) if d is not None else self.one()
        node = getattr(c, "node", None)
        if isinstance(c, nodes.MemberExpr) and node is None:
            t = self.typeof(c.expr)
            if not (isinstance(t, CallableType) and t.is_type_obj()):
                return self.method(t, c.name, c.expr, pos, e.args, e)
            node = lookup(fill_typevars_with_any(t.type_object()), c.name)
        if isinstance(node, nodes.TypeInfo):
            return self._construct(node, pos, e.args, e)
        if isinstance(node, (nodes.FuncBase, nodes.Decorator)):
            r = self.direct(node, None, pos, e.args, e)
            dunder = DUNDERS.get(node.fullname)
            if dunder and pos and self.user_method(self.typeof(pos[0]), dunder):
                t = self.typeof(pos[0])
                r = Cost.sum(r, self.method(t, dunder, pos[0], [], implicit=True))
            return r
        var = node if isinstance(node, nodes.Var) else None
        return self._value_call(c, var, pos, e)

    def _value_call(self, c, var, pos, e):
        """A call through a value: a variable bound to one function, an object
        with ``__call__``, or nothing known."""
        target = self._function_ref(c)
        if target is not None:
            return self.target(target, e)
        t = self.typeof(c) if var is None else get_proper_type(var.type)
        if isinstance(t, AnyType) or t is None:
            return self.unbounded(
                "untyped", f"call through {self.text(c)}, whose type is unknown", e
            )
        if lookup(t, "__call__") is not None:
            return self.method(t, "__call__", c, pos, pos, e)
        return self.unbounded("indirect", f"call through {self.text(c)} ({t})", e)

    def _function_ref(self, x):
        """The analysed function ``x`` names, through one-assignment locals."""
        seen = set()
        while x is not None and id(x) not in seen:
            seen.add(id(x))
            if isinstance(x, nodes.LambdaExpr):
                return x
            node = getattr(x, "node", None)
            if isinstance(node, (nodes.FuncBase, nodes.Decorator)):
                return node if self.a.analysed(node) else None
            if not isinstance(node, nodes.Var) or self.a.assigns.get(id(node)) != 1:
                return None
            x = self.a.rvalue.get(id(node))
        return None

    def _callable(self, args):
        """The costliest function passed in ``args``, or one call."""
        r = ZERO
        for a in args:
            f = self._function_ref(a)
            if f is not None:
                r = Cost.join(r, self.target(f, a))
            elif self.user_method(self.typeof(a), "__call__"):
                r = Cost.join(r, self.method(self.typeof(a), "__call__", a, []))
        return self.entry() if r.zero else r

    def direct(self, node, recv, pos, args, e, implicit=False):
        """A call to a definition known statically."""
        if self.a.analysed(node):
            return self.target(node, e)
        f = func_of(node)
        if isinstance(f, nodes.FuncDef) and self.a.ours(f.info):
            return self.entry()
        return self.system(node.fullname, recv, pos, args, e, implicit)

    def target(self, node, e, setter=False):
        """A call into an analysed definition."""
        if isinstance(node, nodes.OverloadedFuncDef):
            if node.is_property:
                item = node.items[1 if setter and len(node.items) > 1 else 0]
                return self.target(item, e)
            return self.target(node.impl, e)
        f = func_of(node)
        _, name, _ = self.a.funcs[id(f)]
        d = self.a.decorator.get(id(f))
        if d is not None:
            tags = self.decorations(f)
            if "cost" in tags:
                return Cost.leaf(self.parsed(tags["cost"], e))
            for x in d.decorators:
                m = self.a.model(deco_name(x), 0)
                if not _accessor(x, f) and (m is None or m.kind != "transparent"):
                    return self.unbounded(
                        "indirect",
                        f"call to {name} through decorator"
                        f" {deco_name(x) or self.text(x)}, which has no model",
                        e,
                    )
        return Cost.call(self.a.funcs[id(f)][0], name, self.site(e))

    def _construct(self, info, pos, args, e):
        """``C(...)``: ``__new__``, ``__init__`` and a dataclass's ``__post_init__``."""
        if not self.a.ours(info):
            return self.system(info.fullname, None, pos, args, e)
        r = ZERO
        for name in ("__new__", "__init__", "__post_init__"):
            sym = info.get(name)
            node = sym.node if sym is not None else None
            if node is None or (
                name == "__post_init__" and "dataclass" not in info.metadata
            ):
                continue
            if self.a.analysed(node):
                r = Cost.sum(r, self.target(node, e))
            elif name == "__init__":
                r = Cost.sum(r, self.direct(node, None, pos, args, e))
        return r if not r.zero else self.entry()

    def prop(self, t, name):
        """True if ``name`` on ``t`` is a property defined in analysed code."""
        node = lookup(t, name)
        return self.a.analysed(node) and _is_property(node)

    def method(
        self, t, name, recv, pos, args=None, e=None, implicit=False, setter=False
    ):
        """A call of method ``name`` on ``recv`` of type ``t``; ``implicit`` for
        the methods operators and statements call, ``setter`` for a property's."""
        e = e if e is not None else recv
        t = get_proper_type(t) if t is not None else None
        if isinstance(t, UnionType):
            return joined(
                self.method(x, name, recv, pos, args, e, implicit, setter)
                for x in t.items
                if not isinstance(get_proper_type(x), NoneType)
            )
        if isinstance(t, TypeType):
            t = t.item
        if isinstance(t, AnyType) or t is None:
            return self.unbounded(
                "untyped",
                f"call to {name} on {self.text(recv)}, whose type is unknown",
                e,
            )
        inst = instance(t)
        cands = self.dispatch(inst, name)
        if not cands:
            return self._no_method(inst, name, e, implicit)
        parts = []
        for n in cands:
            if isinstance(n, nodes.Var):
                v = get_proper_type(n.type)
                if lookup(v, "__call__") is not None:
                    parts.append(self.method(v, "__call__", recv, pos, args, e))
                else:
                    parts.append(
                        self.unbounded(
                            "indirect",
                            f"call through attribute {name} of {inst} ({v})",
                            e,
                        )
                    )
            elif self.a.analysed(n):
                parts.append(self.target(n, e, setter))
            elif isinstance(n, (nodes.FuncBase, nodes.Decorator)):
                parts.append(
                    self.direct(
                        n, recv, pos, pos if args is None else args, e, implicit
                    )
                )
        return joined(parts)

    def _no_method(self, inst, name, e, implicit):
        """A call of ``name`` on instance type ``inst`` that runs no concrete
        definition."""
        if lookup(inst, name) is not None:
            return self.unbounded(
                "virtual", f"call to {name} on {inst} has no implementation", e
            )
        if lookup(inst, "__getattr__") is not None:
            return self.unbounded(
                "dynamic", f"call to {name} through __getattr__ of {inst}", e
            )
        return ZERO if implicit else self.entry()

    def system(self, name, recv, pos, args, e, implicit=False):
        """A call into code that is not analysed, costed by its model; an
        operator's (``implicit``) costs nothing beyond its statement when constant."""
        m = self.a.model(name, len(pos))
        if m is None:
            return self.unbounded("external", f"call to {name}, which has no model", e)
        if m.kind in ("const", "transparent"):
            return ZERO if implicit else self.entry()
        if m.kind == "indirect":
            return self.unbounded("indirect", f"call through {name}", e)
        if m.kind == "opaque":
            return self.unbounded("external", f"call to {name}, modelled opaque", e)
        of = recv if m.arg < 0 else pos[m.arg] if m.arg < len(pos) else None
        n = Poly.constant(1) if of is None else self.size(of)
        if n is None:
            return self.unbounded(
                "library", f"call to {name} on a range with no bound", e
            )
        scaled = Cost.scale(SCALING[m.kind](n), self._callable(args))
        return scaled if implicit else Cost.sum(self.entry(), scaled)

    _STMT = {
        nodes.ForStmt: _for,
        nodes.WhileStmt: _while,
        nodes.IfStmt: _if,
        nodes.Block: lambda self, s: self.block(s),
        nodes.ExpressionStmt: _expression,
        nodes.AssignmentStmt: _assignment,
        nodes.OperatorAssignmentStmt: _augmented,
        nodes.ReturnStmt: _return,
        nodes.RaiseStmt: _raise,
        nodes.AssertStmt: _assert,
        nodes.DelStmt: _del,
        nodes.TryStmt: _try,
        nodes.WithStmt: _with,
        nodes.MatchStmt: _match,
        nodes.PassStmt: _nothing,
        nodes.GlobalDecl: _nothing,
        nodes.NonlocalDecl: _nothing,
        nodes.Decorator: _decorator,
    }
    _EXPR = {
        nodes.CallExpr: _call_expr,
        nodes.MemberExpr: _member,
        nodes.OpExpr: _op,
        nodes.ComparisonExpr: _comparison,
        nodes.UnaryExpr: _unary,
        nodes.IndexExpr: _index,
        nodes.ConditionalExpr: _conditional,
        nodes.ListComprehension: _listcomp,
        nodes.SetComprehension: _listcomp,
        nodes.GeneratorExpr: _genexpr,
        nodes.DictionaryComprehension: _dictcomp,
        nodes.LambdaExpr: _nothing,
    }


def extract(analysis, modules):
    """A ``Program`` of the functions of ``modules``."""
    out = Program()
    x = Extractor(analysis, out)
    for m in modules:
        x.run(m)
    x.finish()
    return out


def _generator(f):
    return isinstance(f, nodes.FuncDef) and (f.is_generator or f.is_async_generator)
