"""Per-function cost summaries and their composition through the call graph
into a polynomial per entry point."""

from __future__ import annotations

import functools
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from .poly import UNBOUNDED, Poly

LEAF, SUM, JOIN, SCALE, CALL, HOIST, TARGETS = KINDS = (
    "leaf",
    "sum",
    "join",
    "scale",
    "call",
    "hoist",
    "targets",
)
_ZERO = Poly()


@dataclass(frozen=True, order=True)
class Site:
    """A source position."""

    file: str = ""
    line: int = 0
    column: int = 0


@dataclass
class LedgerEntry:
    """Something whose cost has no bound: it contributes the `?` symbol."""

    kind: str
    function: str
    reason: str
    at: Site


class Cost:  # pylint: disable=too-many-instance-attributes
    """A cost expression over polynomials, sums, joins, scalings and calls.

    `HOIST` is a total the loops around it in its function leave alone (with
    `run`, every loop around it); `TARGETS` joins the functions `names` globs.
    """

    __slots__ = (
        "k",
        "p",
        "kids",
        "usr",
        "callee",
        "virtual",
        "pure",
        "run",
        "names",
        "at",
    )
    LEAF, SUM, JOIN, SCALE, CALL, HOIST, TARGETS = KINDS

    def __init__(
        self,
        k: str = LEAF,
        p: Poly = _ZERO,
        kids: tuple[Cost, ...] = (),
        usr: str = "",
        callee: str = "",
        virtual: bool = False,
        pure: bool = False,
        run: bool = False,
        names: tuple[str, ...] = (),
        at: Site = Site(),
    ):
        self.k, self.p, self.kids = k, p, tuple(kids)
        self.usr, self.callee, self.virtual, self.pure = usr, callee, virtual, pure
        self.run, self.names, self.at = run, tuple(names), at

    @property
    def zero(self) -> bool:
        """Whether this is the zero leaf."""
        return self.k == LEAF and self.p.zero

    @staticmethod
    def leaf(p: Poly) -> Cost:
        """The polynomial `p`."""
        return Cost(p=p)

    @staticmethod
    def _combine(k: str, a: Cost, b: Cost) -> Cost:
        if a.k == LEAF and b.k == LEAF:
            return Cost.leaf(a.p + b.p if k == SUM else a.p.join(b.p))
        if k == SUM and a.zero:
            return b
        if b.zero:
            return a
        kids: list[Cost] = []
        for x in (a, b):
            if x.k == k:
                kids.extend(x.kids)
            else:
                kids.append(x)
        return Cost(k, kids=tuple(kids))

    @staticmethod
    def sum(a: Cost, b: Cost) -> Cost:
        """`a + b`."""
        return Cost._combine(SUM, a, b)

    @staticmethod
    def join(a: Cost, b: Cost) -> Cost:
        """The larger of `a` and `b`."""
        return Cost._combine(JOIN, a, b)

    @staticmethod
    def scale(p: Poly, e: Cost) -> Cost:
        """`p * e`, which a `HOIST` inside `e` escapes."""
        if e.k == LEAF or p.zero:
            return Cost.leaf(p * e.p)
        if p.constant_value() == 1.0:
            return e
        return Cost(SCALE, p=p, kids=(e,))

    @staticmethod
    def call(
        usr: str, callee: str, at: Site, virtual: bool = False, pure: bool = False
    ) -> Cost:
        """A call to `usr`; a virtual one also reaches its overriders, and only
        them when the callee is pure."""
        return Cost(CALL, usr=usr, callee=callee, at=at, virtual=virtual, pure=pure)

    @staticmethod
    def hoist(e: Cost, run: bool = False) -> Cost:
        """`e` as a total the loops around it do not scale."""
        return e if e.zero else Cost(HOIST, kids=(e,), run=run)

    @staticmethod
    def targets(names: list[str], at: Site) -> Cost:
        """The join of the functions matching any glob of `names`."""
        return Cost(TARGETS, names=tuple(names), at=at)


@dataclass
class Function:
    """A function's cost summary; `loops`: a backward goto, an unbounded loop."""

    name: str
    plain: str
    at: Site
    body: Cost
    ledger: list[LedgerEntry] = field(default_factory=list)
    recursion: Poly | None = None
    loops: bool = False


@dataclass
class Entry:
    """An entry pattern's cost and the ledger of everything it reaches."""

    pattern: str
    functions: list[str]
    cost: Poly
    ledger: list[LedgerEntry]
    breakdown: list[tuple[str, Poly]]


_Parts = tuple[Poly, Poly, Poly]


def _total(v: _Parts) -> Poly:
    return v[0] + v[1] + v[2]


def _ledger_key(e: LedgerEntry) -> tuple[Site, str, str]:
    return e.at, e.kind, e.reason


def _class(chars: bytes) -> set[int]:
    """The bytes of a bracket expression's body, with `X-Y` ranges."""
    out: set[int] = set()
    i = 0
    while len(chars) - i >= 3:
        if chars[i + 1] != ord("-"):
            out.add(chars[i])
            i += 1
            continue
        if chars[i] > chars[i + 2]:
            raise ValueError
        out.update(range(chars[i], chars[i + 2] + 1))
        i += 3
    out.update(chars[i:])
    return out


def _brace_groups(s: bytes) -> list[tuple[int, int, list[bytes]]]:
    """The `(start, end, terms)` of each `{a,b}` of `s`."""
    groups: list[tuple[int, int, list[bytes]]] = []
    current: list[bytes] | None = None
    start = begin = i = 0
    while i < len(s):
        c = s[i : i + 1]
        if c == b"[":
            i = s.find(b"]", i + 2)
            if i < 0:
                raise ValueError("invalid glob pattern, unmatched '['")
        elif c == b"{":
            if current is not None:
                raise ValueError("nested brace expansions are not supported")
            current, start, begin = [], i, i + 1
        elif c == b"," and current is not None:
            current.append(s[begin:i])
            begin = i + 1
        elif c == b"}" and current is not None:
            if not current:
                raise ValueError(
                    "empty or singleton brace expansions are not supported"
                )
            current.append(s[begin:i])
            groups.append((start, i + 1, current))
            current = None
        elif c == b"\\":
            i += 1
            if i == len(s):
                raise ValueError("invalid glob pattern, stray '\\'")
        i += 1
    if current is not None:
        raise ValueError("incomplete brace expansion")
    return groups


def _braces(s: bytes) -> list[bytes]:
    """The subpatterns of the `{a,b}` expansions of `s`, in LLVM's order."""
    groups = _brace_groups(s) if b"{" in s else []
    if functools.reduce(lambda n, g: n * len(g[2]), groups, 1) > 4096:
        raise ValueError("too many brace expansions")
    subs = [s]
    for lo, hi, terms in reversed(groups):
        subs = [o[:lo] + t + o[hi:] for t in terms for o in subs]
    return subs


def _subglob(s: bytes) -> bytes:
    """A subpattern without braces as a bytes regex."""
    out, i = [], 0
    while i < len(s):
        c = s[i : i + 1]
        if c == b"[":
            i += 1
            j = s.find(b"]", i + 1)
            if j < 0:
                raise ValueError("invalid glob pattern, unmatched '['")
            invert = s[i : i + 1] in (b"^", b"!")
            try:
                chars = _class(s[i + invert : j])
            except ValueError:
                text = s.decode("utf-8", "surrogateescape")
                raise ValueError(f"invalid glob pattern: {text}") from None
            if invert:
                chars = set(range(256)) - chars
            body = b"".join(b"\\x%02x" % x for x in sorted(chars))
            out.append(b"[" + body + b"]" if chars else b"(?!)")
            i = j
        elif c == b"\\":
            i += 1
            if i == len(s):
                raise ValueError("invalid glob pattern, stray '\\'")
            out.append(re.escape(s[i : i + 1]))
        else:
            out.append({b"*": b".*", b"?": b"."}.get(c) or re.escape(c))
        i += 1
    return b"".join(out)


@functools.lru_cache(maxsize=None)
def glob(pattern: str) -> Callable[[str], bool]:
    """A matcher with `llvm::GlobPattern` semantics over UTF-8 bytes: `*`, `?`,
    `[..]`, `[!..]`, `\\` escapes and unnested `{a,b}` alternatives.
    ValueError with LLVM's message for a bad pattern."""
    raw = pattern.encode("utf-8", "surrogateescape")
    cut = next((i for i, c in enumerate(raw) if c in b"?*[{\\"), len(raw))
    if cut == len(raw):
        return lambda name: name == pattern
    subs = b"|".join(_subglob(s) for s in _braces(raw[cut:]))
    regex = re.compile(re.escape(raw[:cut]) + b"(?:" + subs + b")", re.DOTALL)
    return lambda name: bool(regex.fullmatch(name.encode("utf-8", "surrogateescape")))


def _entry_glob(pattern: str) -> Callable[[str], bool]:
    """`glob(pattern)`, a bad pattern's error naming it as an entry."""
    try:
        return glob(pattern)
    except ValueError as err:
        raise ValueError(f"bad entry pattern {pattern}: {err}") from None


class Program:
    """Function summaries over a set of translation units."""

    def __init__(self) -> None:
        self.functions: dict[str, Function] = {}
        self.overriders: dict[str, set[str]] = {}
        self.symbols: dict[str, float | None] = {}
        self.conflicts: set[str] = set()
        self._resolved: dict[str, _Parts] = {}

    def symbol(self, name: str, value: float | None) -> None:
        """Record a symbol and its value if known; two different values make
        it unknown."""
        if name not in self.symbols:
            self.symbols[name] = value
            return
        old = self.symbols[name]
        if value is None or old == value or name in self.conflicts:
            return
        if old is not None:
            self.conflicts.add(name)
        self.symbols[name] = None if name in self.conflicts else value

    def merge(self, other: Program) -> None:
        """Take `other`'s summaries; a function already present keeps its own."""
        for usr, f in other.functions.items():
            self.functions.setdefault(usr, f)
        for usr, o in other.overriders.items():
            self.overriders.setdefault(usr, set()).update(o)
        self.conflicts |= other.conflicts
        for name, value in other.symbols.items():
            self.symbol(name, value)
        for name in self.conflicts:
            self.symbols[name] = None

    def candidates(self, c: Cost) -> list[str]:
        """The USRs a `CALL` or `TARGETS` node may reach."""
        if c.k == TARGETS:
            out: set[str] = set()
            for pattern in c.names:
                try:
                    match = glob(pattern)
                except ValueError:
                    continue
                out.update(
                    u
                    for u, f in self.functions.items()
                    if match(f.name) or match(f.plain)
                )
            return sorted(out)
        if not c.virtual:
            return [c.usr]
        found = [] if c.pure else [c.usr]
        seen, work = {c.usr}, [c.usr]
        while work:
            for o in sorted(self.overriders.get(work.pop(), ())):
                if o not in seen:
                    seen.add(o)
                    work.append(o)
                    found.append(o)
        return found

    def edges(self, c: Cost) -> set[str]:
        """Every USR the calls and targets under `c` may reach."""
        out: set[str] = set()
        seen: set[int] = set()
        work = [c]
        while work:
            c = work.pop()
            if id(c) not in seen:
                seen.add(id(c))
                if c.k in (CALL, TARGETS):
                    out.update(self.candidates(c))
                work.extend(c.kids)
        return out

    def _eval(
        self, c: Cost, scc: set[str], ledger: list[LedgerEntry], owner: str
    ) -> _Parts:
        """`c` split into what the loops around it scale, what only the loops
        of its own function leave alone, and what no loop around it scales."""
        if c.k == LEAF:
            return c.p, _ZERO, _ZERO
        if c.k == SCALE:
            s, h, r = self._eval(c.kids[0], scc, ledger, owner)
            return c.p * s, h, r
        if c.k == HOIST:
            v = self._eval(c.kids[0], scc, ledger, owner)
            return (_ZERO, _ZERO, _total(v)) if c.run else (_ZERO, v[0] + v[1], v[2])
        if c.k == SUM:
            s = h = r = _ZERO
            for kid in c.kids:
                vs, vh, vr = self._eval(kid, scc, ledger, owner)
                s, h, r = s + vs, h + vh, r + vr
            return s, h, r
        if c.k == JOIN:
            j = _ZERO
            for kid in c.kids:
                j = j.join(_total(self._eval(kid, scc, ledger, owner)))
            return j, _ZERO, _ZERO
        return self._reach(c, scc, ledger, owner)

    def _reach(
        self, c: Cost, scc: set[str], ledger: list[LedgerEntry], owner: str
    ) -> _Parts:
        """A `CALL` or `TARGETS` node: one callee keeps its run-wide total
        apart; several are joined under the loops around the call."""
        unbounded = Poly.symbol(UNBOUNDED), _ZERO, _ZERO
        cands = self.candidates(c)
        if not cands:
            if c.k == TARGETS:
                kind = "annotation"
                reason = "VC_TARGETS names no analysed function: " + ", ".join(c.names)
            else:
                kind, reason = "virtual", f"virtual call to {c.callee} has no overrider"
            ledger.append(LedgerEntry(kind, owner, reason, c.at))
            return unbounded
        known: list[_Parts] = []
        for u in cands:
            if u in scc:
                continue
            if u in self._resolved:
                known.append(self._resolved[u])
                continue
            reason = f"call to {c.callee} whose body is not analysed"
            ledger.append(LedgerEntry("external", owner, reason, c.at))
            known.append(unbounded)
        if len(known) == 1:
            return known[0][0] + known[0][1], _ZERO, known[0][2]
        j = _ZERO
        for v in known:
            j = j.join(_total(v))
        return j, _ZERO, _ZERO

    def _close(self, scc: list[str], cyclic: bool) -> None:
        """Resolve a closed component, its members in USR order."""
        local, bound, members = _ZERO, None, set(scc)
        for m in scc:
            f = self.functions[m]
            s, h, r = self._eval(f.body, members, f.ledger, f.name)
            if not cyclic:
                self._resolved[m] = s + h, _ZERO, r
                return
            local = local + (s + h + r)
            if f.recursion is not None:
                bound = f.recursion if bound is None else bound.join(f.recursion)
        if bound is None:
            bound = Poly.symbol(UNBOUNDED)
            for m in scc:
                f = self.functions[m]
                reason = "recursive call with no bound"
                f.ledger.append(LedgerEntry("recursion", f.name, reason, f.at))
        for m in scc:
            self._resolved[m] = bound * local, _ZERO, _ZERO

    def _components(self, graph: dict[str, list[str]]) -> None:
        """Tarjan's strongly connected components, iteratively; each is
        resolved when it closes, after every component it calls."""
        index: dict[str, int] = {}
        low: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        work: list[tuple[str, Iterator[str]]] = []

        def enter(u: str) -> None:
            index[u] = low[u] = len(index)
            stack.append(u)
            on_stack.add(u)
            work.append((u, iter(graph[u])))

        for root in graph:
            if root in index:
                continue
            enter(root)
            while work:
                u, it = work[-1]
                for v in it:
                    if v not in index:
                        enter(v)
                        break
                    if v in on_stack:
                        low[u] = min(low[u], index[v])
                else:
                    work.pop()
                    if work:
                        p = work[-1][0]
                        low[p] = min(low[p], low[u])
                    if low[u] == index[u]:
                        scc = []
                        while not scc or scc[-1] != u:
                            scc.append(stack.pop())
                            on_stack.discard(scc[-1])
                        self._close(sorted(scc), len(scc) > 1 or u in graph[u])

    def _named(self, usr: str) -> Poly:
        """The resolved cost of `usr` with its capacities named."""
        return _total(self._resolved[usr]).name(self.symbols)

    def _entry(
        self,
        pattern: str,
        match: Callable[[str], bool],
        graph: dict[str, list[str]],
        breakdown: bool,
    ) -> Entry:
        """The entry of `pattern`, whose functions `match` names."""
        fns = self.functions
        names, cost, work = [], _ZERO, []
        for u in graph:
            if match(fns[u].name) or match(fns[u].plain):
                names.append(fns[u].name)
                cost = cost.join(self._named(u))
                work.append(u)
        if not work:
            raise ValueError(f"entry {pattern} matches no analysed function")
        seen, ledger = set(work), {}
        while work:
            u = work.pop()
            for e in fns[u].ledger:
                ledger.setdefault(_ledger_key(e), e)
            for v in graph[u]:
                if v not in seen:
                    seen.add(v)
                    work.append(v)
        parts = [(fns[u].name, self._named(u)) for u in (seen if breakdown else ())]
        return Entry(
            pattern,
            sorted(names),
            cost,
            [ledger[k] for k in sorted(ledger)],
            sorted(parts, key=lambda t: (t[0], str(t[1]))),
        )

    def resolve(self, patterns: list[str], breakdown: bool = False) -> list[Entry]:
        """Each pattern's cost: the join of the functions it names, and the
        ledger of everything they reach. ValueError for a bad pattern or one
        matching nothing."""
        fns = self.functions
        graph = {
            u: [v for v in sorted(self.edges(fns[u].body)) if v in fns]
            for u in sorted(fns)
        }
        self._components(graph)
        return [
            self._entry(pattern, _entry_glob(pattern), graph, breakdown)
            for pattern in patterns
        ]


def _used(entries: list[Entry]) -> list[str]:
    """The symbols the entry polynomials use, `log2(s)` as `s`."""
    used = set()
    for e in entries:
        for m in e.cost.terms:
            for s, _ in m:
                if s.startswith("log2(") and s.endswith(")"):
                    used.add(s[5:-1])
                elif s != UNBOUNDED:
                    used.add(s)
    return sorted(used)


def _report_entry(e: Entry) -> dict:
    out = {
        "functions": e.functions,
        "polynomial": str(e.cost),
        "terms": [
            {"coefficient": c, "powers": dict(m)} for m, c in e.cost.terms.items()
        ],
        "degree": {
            s: e.cost.degree(s) for s in sorted({s for m in e.cost.terms for s, _ in m})
        },
    }
    if e.breakdown:
        out["breakdown"] = [
            {"function": n, "polynomial": str(p)} for n, p in e.breakdown
        ]
    out["ledger"] = [
        {
            "kind": x.kind,
            "function": x.function,
            "file": x.at.file,
            "line": x.at.line,
            "column": x.at.column,
            "reason": x.reason,
        }
        for x in e.ledger
    ]
    return out


def report(program: Program, entries: list[Entry]) -> dict:
    """The JSON report of `entries`, as `writeJson` structures it."""
    return {
        "version": 1,
        "unbounded_symbol": UNBOUNDED,
        "symbols": {s: program.symbols.get(s) for s in _used(entries)},
        "entries": {e.pattern: _report_entry(e) for e in entries},
    }


_ESCAPE = {i: f"\\u{i:04x}" for i in range(0x20)}
_ESCAPE.update({0x09: "\\t", 0x0A: "\\n", 0x0D: "\\r", 0x22: '\\"', 0x5C: "\\\\"})


def _json(v, indent: str, out: list[str]) -> None:
    """Append `v` as `llvm::json::OStream` with indent 1 writes it."""
    if isinstance(v, (dict, list)):
        items = v.items() if isinstance(v, dict) else ((None, x) for x in v)
        brackets = "{}" if isinstance(v, dict) else "[]"
        out.append(brackets[0])
        inner, sep = indent + " ", "\n"
        for key, x in items:
            out.append(sep + inner)
            sep = ",\n"
            if key is not None:
                out.append(f'"{key.translate(_ESCAPE)}": ')
            _json(x, inner, out)
        out.append(("" if sep == "\n" else "\n" + indent) + brackets[1])
    elif v is None or isinstance(v, bool):
        out.append({None: "null", True: "true", False: "false"}[v])
    elif isinstance(v, int):
        out.append(str(v))
    elif isinstance(v, float):
        out.append(f"{v:.17g}")
    else:
        out.append(f'"{v.translate(_ESCAPE)}"')


def to_json(value) -> str:
    """`value` as JSON text in `llvm::json::OStream` form (indent 1, doubles as
    `%.17g`), with a trailing newline."""
    out: list[str] = []
    _json(value, "", out)
    return "".join(out) + "\n"


def dumps(program: Program, entries: list[Entry]) -> str:
    """The JSON report text, as `writeJson` writes it."""
    return to_json(report(program, entries))
