"""Whole-program facts gathered from mypy's trees before costing."""

from mypy import nodes
from mypy.subtypes import is_protocol_implementation
from mypy.typevars import fill_typevars_with_any

from virtuous_cycles.pycost.models import Weights, builtin_models
from virtuous_cycles.pycost.source import Meta, read

SAME_SIZE = {
    "builtins.enumerate",
    "builtins.reversed",
    "builtins.iter",
    "builtins.sorted",
    "builtins.list",
    "builtins.tuple",
    "builtins.set",
    "builtins.frozenset",
    "builtins.dict",
    "copy.copy",
    "copy.deepcopy",
}
SAME_SIZE_METHODS = {"keys", "values", "items", "copy"}
READ_FUNCS = SAME_SIZE | {
    "builtins.len",
    "builtins.sum",
    "builtins.min",
    "builtins.max",
    "builtins.any",
    "builtins.all",
    "builtins.zip",
    "builtins.map",
    "builtins.filter",
    "builtins.print",
    "builtins.isinstance",
}
READ_METHODS = SAME_SIZE_METHODS | {"index", "count", "get", "__contains__"}
OVERLOAD = ("typing.overload", "typing_extensions.overload")
CHILD_FIELDS = {
    nodes.MypyFile: ("defs",),
    nodes.Block: ("body",),
    nodes.ExpressionStmt: ("expr",),
    nodes.AssignmentStmt: ("lvalues", "rvalue"),
    nodes.OperatorAssignmentStmt: ("lvalue", "rvalue"),
    nodes.IfStmt: ("expr", "body", "else_body"),
    nodes.WhileStmt: ("expr", "body", "else_body"),
    nodes.TryStmt: ("body", "types", "vars", "handlers", "else_body", "finally_body"),
    nodes.WithStmt: ("expr", "target", "body"),
    nodes.RaiseStmt: ("expr", "from_expr"),
    nodes.AssertStmt: ("expr", "msg"),
    nodes.DelStmt: ("expr",),
    nodes.MatchStmt: ("subject", "guards", "bodies"),
    nodes.FuncDef: ("body",),
    nodes.LambdaExpr: ("body",),
    nodes.Decorator: ("decorators", "func"),
    nodes.OverloadedFuncDef: ("items", "impl"),
    nodes.ClassDef: ("decorators", "defs"),
    nodes.OpExpr: ("left", "right"),
    nodes.UnaryExpr: ("expr",),
    nodes.SliceExpr: ("begin_index", "end_index", "stride"),
    nodes.ConditionalExpr: ("cond", "if_expr", "else_expr"),
    nodes.StarExpr: ("expr",),
    nodes.ListComprehension: ("generator",),
    nodes.SetComprehension: ("generator",),
    nodes.AssignmentExpr: ("target", "value"),
    nodes.AwaitExpr: ("expr",),
    nodes.YieldExpr: ("expr",),
    nodes.YieldFromExpr: ("expr",),
    nodes.CastExpr: ("expr",),
    nodes.AssertTypeExpr: ("expr",),
    nodes.RevealExpr: ("expr",),
    nodes.SuperExpr: ("call",),
}


def _fields(names):
    def get(n):
        out = []
        for f in names:
            v = getattr(n, f)
            out.extend((x, False) for x in (v if isinstance(v, list) else [v]))
        return out

    return get


def _comprehension(n):
    lead = [n.left_expr] if isinstance(n, nodes.GeneratorExpr) else [n.key, n.value]
    return (
        [(x, False) for x in lead + n.indices]
        + [(x, True) for x in n.sequences]
        + [(c, False) for cs in n.condlists for c in cs]
    )


def _items(n):
    return [(x, False) for x in n.items]


CHILDREN = {t: _fields(f) for t, f in CHILD_FIELDS.items()} | {
    nodes.ListExpr: _items,
    nodes.TupleExpr: _items,
    nodes.SetExpr: _items,
    nodes.DictExpr: lambda n: [(x, False) for kv in n.items for x in kv],
    nodes.CallExpr: lambda n: [(n.callee, False)]
    + [(a, getattr(n.callee, "fullname", None) in READ_FUNCS) for a in n.args],
    nodes.MemberExpr: lambda n: [(n.expr, n.name in READ_METHODS)],
    nodes.IndexExpr: lambda n: [(n.base, True), (n.index, False)],
    nodes.ComparisonExpr: lambda n: [(x, True) for x in n.operands],
    nodes.ForStmt: lambda n: [
        (n.index, False),
        (n.expr, True),
        (n.body, False),
        (n.else_body, False),
    ],
    nodes.GeneratorExpr: _comprehension,
    nodes.DictionaryComprehension: _comprehension,
    nodes.ReturnStmt: lambda n: [(n.expr, True)],
}


def children(n):
    """Child nodes of a mypy statement or expression (None included), with
    whether a name read in that position leaves a container's size unchanged."""
    f = CHILDREN.get(type(n))
    return f(n) if f is not None else []


def func_of(node):
    """The function a definition calls into (a property's getter), or None."""
    if isinstance(node, nodes.Decorator):
        return node.func
    if isinstance(node, nodes.OverloadedFuncDef):
        if node.is_property:
            return func_of(node.items[0])
        return func_of(node.impl) if node.impl else None
    return node if isinstance(node, nodes.FuncItem) else None


def deco_name(d):
    """The qualified name of a decorator, called or not."""
    if isinstance(d, nodes.CallExpr):
        d = d.callee
    return getattr(d, "fullname", None) or ""


def var(e):
    """The variable a name or attribute refers to."""
    if isinstance(e, (nodes.NameExpr, nodes.MemberExpr)):
        v = e.node
        if v is None and isinstance(e, nodes.MemberExpr):
            v = e.def_var
        return v if isinstance(v, nodes.Var) else None
    return None


def abstract(node):
    """True if ``node`` has no body to run."""
    f = func_of(node)
    return f is not None and getattr(f, "abstract_status", 0) != nodes.NOT_ABSTRACT


STORES = {
    nodes.WithStmt: lambda n: n.target,
    nodes.TryStmt: lambda n: n.vars,
    nodes.AssignmentExpr: lambda n: [n.target],
    nodes.DelStmt: lambda n: [n.expr],
}


def _targets(node):
    """The children of ``node`` that are names it binds, not reads."""
    if isinstance(node, nodes.AssignmentStmt):
        return {id(x) for x in node.lvalues if not isinstance(x, nodes.IndexExpr)}
    if isinstance(node, nodes.ForStmt):
        return {id(node.index)}
    return set()


class Analysis:  # pylint: disable=too-many-instance-attributes
    """Whole-program facts: the analysed functions and classes, what each
    variable is assigned, and the declared bounds."""

    def __init__(self, result, modules, root="", models=None, weights=None):
        self.types = result.types
        self.root = root
        self.models = (models or []) + builtin_models()
        self.weights = weights or Weights()
        self.trees = {m: result.graph[m].tree for m in modules}
        self.sources = {}
        self.funcs = {}
        self.items = {m: [] for m in modules}
        self.decorator = {}
        self.infos = []
        self.assigns = {}
        self.rvalue = {}
        self.binding = {}
        self.escaped = set()
        self.decl = {}
        self.ret = {}
        self.known = {}
        self.final = {}
        self.model_cache = {}
        self.protocols = {}
        for m, tree in self.trees.items():
            with open(tree.path, encoding="utf-8") as f:
                self.sources[m] = read(f.read())
            self._scan(m, tree, m)
        self.subclasses = {}
        for info in self.infos:
            for base in info.mro[1:]:
                self.subclasses.setdefault(base.fullname, []).append(info)

    def analysed(self, node):
        """True if ``node``'s body is summarised."""
        f = func_of(node)
        return f is not None and id(f) in self.funcs

    def implementers(self, info):
        """The analysed classes that implement protocol ``info`` structurally."""
        if not info.is_protocol:
            return []
        if info.fullname not in self.protocols:
            proto = fill_typevars_with_any(info)
            self.protocols[info.fullname] = [
                c
                for c in self.infos
                if c is not info
                and not c.is_protocol
                and is_protocol_implementation(fill_typevars_with_any(c), proto)
            ]
        return self.protocols[info.fullname]

    def ours(self, info):
        """True if class ``info`` is defined in an analysed module."""
        return (
            info is not None
            and info is not nodes.FUNC_NO_INFO
            and info.module_name in self.trees
        )

    def model(self, name, nargs):
        """The first model that costs a call to ``name``."""
        key = (name, nargs)
        if key not in self.model_cache:
            self.model_cache[key] = next(
                (m for m in self.models if m.applies(name, nargs)), None
            )
        return self.model_cache[key]

    def _register(self, m, f, name):
        self.funcs[id(f)] = (f"{name}@{f.line}:{f.column}", name, m)
        self.items[m].append(f)

    def _assign(self, v, rvalue=None):
        self.assigns[id(v)] = self.assigns.get(id(v), 0) + 1
        if rvalue is not None:
            self.rvalue[id(v)] = rvalue

    def _final(self, v, m):
        if not (v.is_final and isinstance(v.final_value, int)):
            return
        src = self.sources[m].assigns.get((v.line, v.name), Meta())
        name = src.symbol or v.name
        value = float(max(0, v.final_value))
        self.final[id(v)] = name
        self.known[name] = value if self.known.get(name, value) == value else None

    def _lvalue(self, lv, m, rvalue, line):
        if isinstance(lv, (nodes.TupleExpr, nodes.ListExpr)):
            for x in lv.items:
                self._lvalue(x, m, None, line)
            return
        if isinstance(lv, nodes.StarExpr):
            self._lvalue(lv.expr, m, None, line)
            return
        if isinstance(lv, nodes.IndexExpr):
            v = var(lv.base)
            if v is not None:
                self.escaped.add(id(v))
            return
        v = var(lv)
        if v is None:
            return
        self._assign(v, rvalue)
        meta = self.sources[m].assigns.get((line, v.name))
        if meta is not None:
            self.decl[id(v)] = meta
        self._final(v, m)

    def _bind(self, m, index, seq):
        """What a loop variable ranges over."""
        if isinstance(index, nodes.NameExpr) and isinstance(index.node, nodes.Var):
            self._assign(index.node)
            self.binding[id(index.node)] = ("elem", seq)
            return
        if not isinstance(index, (nodes.TupleExpr, nodes.ListExpr)):
            self._lvalue(index, m, None, 0)
            return
        name = getattr(getattr(seq, "callee", None), "fullname", None)
        args = seq.args if isinstance(seq, nodes.CallExpr) else []
        for k, x in enumerate(index.items):
            if not (isinstance(x, nodes.NameExpr) and isinstance(x.node, nodes.Var)):
                self._lvalue(x, m, None, 0)
                continue
            self._assign(x.node)
            if name == "builtins.enumerate" and args:
                self.binding[id(x.node)] = (
                    ("count", seq) if k == 0 else ("elem", args[0])
                )
            elif name == "builtins.zip" and k < len(args):
                self.binding[id(x.node)] = ("elem", args[k])

    def _scan(self, m, node, prefix, parent_read=False):
        t = type(node)
        if t is nodes.NameExpr:
            if isinstance(node.node, nodes.Var) and not parent_read:
                self.escaped.add(id(node.node))
            return
        hook = self._SCAN.get(t)
        if hook is not None:
            prefix = hook(self, m, node, prefix)
            if prefix is None:
                return
        skip = _targets(node)
        for child, read_only in children(node):
            if child is not None and id(child) not in skip:
                self._scan(m, child, prefix, read_only)

    def _class(self, _m, node, prefix):
        self.infos.append(node.info)
        return f"{prefix}.{node.name}"

    def _decorated(self, _m, node, prefix):
        if any(deco_name(d) in OVERLOAD for d in node.decorators):
            return None
        self.decorator[id(node.func)] = node
        return prefix

    def _function(self, m, node, prefix):
        prefix = f"{prefix}.{node.name}"
        self._register(m, node, prefix)
        src = self.sources[m]
        self.ret[id(node)] = src.returns.get(node.line, Meta())
        for a in node.arguments:
            self._assign(a.variable)
            meta = src.params.get((node.line, a.variable.name))
            if meta is not None:
                self.decl[id(a.variable)] = meta
            if a.initializer is not None:
                self._scan(m, a.initializer, prefix)
        return prefix

    def _lambda(self, m, node, prefix):
        self._register(m, node, f"{prefix}.(lambda:{node.line}:{node.column + 1})")
        for a in node.arguments:
            self._assign(a.variable)
        return prefix

    def _assignment(self, m, node, prefix):
        single = len(node.lvalues) == 1
        for lv in node.lvalues:
            self._lvalue(lv, m, node.rvalue if single else None, node.line)
        return prefix

    def _augmented(self, _m, node, prefix):
        v = var(node.lvalue)
        if v is not None:
            self._assign(v)
            self._assign(v)
        return prefix

    def _loop(self, m, node, prefix):
        self._bind(m, node.index, node.expr)
        return prefix

    def _comprehension(self, m, node, prefix):
        for index, seq in zip(node.indices, node.sequences):
            self._bind(m, index, seq)
        return prefix

    def _stores(self, m, node, prefix):
        for x in STORES[type(node)](node):
            if x is not None:
                self._lvalue(x, m, None, node.line)
        return prefix

    _SCAN = {
        nodes.ClassDef: _class,
        nodes.Decorator: _decorated,
        nodes.FuncDef: _function,
        nodes.LambdaExpr: _lambda,
        nodes.AssignmentStmt: _assignment,
        nodes.OperatorAssignmentStmt: _augmented,
        nodes.ForStmt: _loop,
        nodes.GeneratorExpr: _comprehension,
        nodes.DictionaryComprehension: _comprehension,
        nodes.WithStmt: _stores,
        nodes.TryStmt: _stores,
        nodes.AssignmentExpr: _stores,
        nodes.DelStmt: _stores,
    }
