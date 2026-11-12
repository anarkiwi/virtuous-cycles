"""What ``vc-py-cost`` reads from source text rather than from mypy's tree.

``# vc:`` pragmas, and ``Annotated[..., vc.Size(...)]`` metadata, which mypy
drops while analysing types.
"""

import ast
import io
import re
import tokenize
from dataclasses import dataclass, field

PRAGMA = re.compile(r"#\s*vc:\s*([A-Za-z_]+)\s*\((.*)\)\s*$")
CONTAINERS = {
    "list",
    "set",
    "frozenset",
    "tuple",
    "deque",
    "Sequence",
    "MutableSequence",
    "Set",
    "AbstractSet",
    "MutableSet",
    "Collection",
    "Iterable",
    "Iterator",
    "Generator",
    "AsyncIterator",
    "AsyncIterable",
    "AsyncGenerator",
    "List",
    "FrozenSet",
    "Tuple",
    "Deque",
    "NDArray",
}
WRAPPERS = {"Final", "ClassVar", "Optional", "Required", "NotRequired", "ReadOnly"}
SKIP = {
    tokenize.COMMENT,
    tokenize.NL,
    tokenize.NEWLINE,
    tokenize.INDENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
}


@dataclass(frozen=True)
class Pragma:
    """One ``# vc: tag(arg)`` comment."""

    tag: str
    arg: str
    line: int
    column: int


@dataclass(frozen=True)
class Meta:
    """A declaration's bounds: its own, then its elements', and so on."""

    shape: tuple = ()
    symbol: str | None = None


@dataclass
class Source:
    """One file's pragmas by the line of the statement they precede."""

    lines: list[str]
    pragmas: dict[int, list[Pragma]] = field(default_factory=dict)
    params: dict[tuple[int, str], Meta] = field(default_factory=dict)
    returns: dict[int, Meta] = field(default_factory=dict)
    assigns: dict[tuple[int, str], Meta] = field(default_factory=dict)

    def text(self, node):
        """``node``'s source with whitespace collapsed, in backquotes."""
        line, col = node.line, node.column
        end_line, end_col = node.end_line or line, node.end_column
        if line < 1 or end_col is None:
            return "``"
        rows = self.lines[line - 1 : end_line]
        if not rows:
            return "``"
        rows[-1] = rows[-1][:end_col] if len(rows) > 1 else rows[-1][col:end_col]
        if len(rows) > 1:
            rows[0] = rows[0][col:]
        return "`" + " ".join(" ".join(rows).split()) + "`"


def _name(node):
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _value(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, str)):
        return str(node.value)
    return None


def meta(node):
    """The ``Meta`` of an annotation expression."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            node = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return Meta()
    if not isinstance(node, ast.Subscript):
        return Meta()
    head = _name(node.value)
    args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    if head in WRAPPERS:
        return meta(args[0])
    if head == "Annotated":
        inner = meta(args[0])
        size, symbol = None, inner.symbol
        for extra in args[1:]:
            if isinstance(extra, ast.Call) and extra.args:
                kind = _name(extra.func)
                if kind == "Size":
                    size = _value(extra.args[0])
                elif kind == "Symbol":
                    symbol = _value(extra.args[0])
        return Meta(_trim((size,) + inner.shape[1:]), symbol)
    if head in CONTAINERS:
        return Meta(_trim((None,) + meta(args[0]).shape))
    return Meta()


def _trim(shape):
    while shape and shape[-1] is None:
        shape = shape[:-1]
    return shape


def _pragmas(text):
    out, pending, last = {}, [], 0
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                m = PRAGMA.match(tok.string)
                if m:
                    p = Pragma(m[1], m[2].strip(), tok.start[0], tok.start[1] + 1)
                    if last == tok.start[0]:
                        out.setdefault(last, []).append(p)
                    else:
                        pending.append(p)
            elif tok.type not in SKIP:
                last = tok.start[0]
                if pending:
                    out.setdefault(last, []).extend(pending)
                    pending = []
    except (tokenize.TokenError, SyntaxError):
        pass
    return out


def read(text):
    """Parse one file's pragmas and declaration metadata."""
    src = Source(text.splitlines(), _pragmas(text))
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return src
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            for arg in a.posonlyargs + a.args + a.kwonlyargs + [a.vararg, a.kwarg]:
                if arg is not None and arg.annotation is not None:
                    _put(src.params, (node.lineno, arg.arg), meta(arg.annotation))
            if node.returns is not None:
                _put(src.returns, node.lineno, meta(node.returns))
        elif isinstance(node, ast.AnnAssign):
            target = _name(node.target)
            if target:
                _put(src.assigns, (node.lineno, target), meta(node.annotation))
    return src


def _put(table, key, value):
    if value.shape or value.symbol:
        table[key] = value
