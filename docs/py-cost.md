# vc-py-cost

A mypy-based tool that bounds the worst-case operation count of Python entry
points as a polynomial in declared capacities, and lists everything it cannot
bound in a ledger. It is the Python counterpart of [vc-cxx-cost](cxx-cost.md):
the same cost model, annotations (as Python syntax), report format and
composition backend (`virtuous_cycles.cost`, cross-checked against the C++ one
on every C++ fixture). The `py-cost` adapter ([adapters.md](adapters.md#py-cost))
ratchets its report.

## Install and run

```sh
pip install 'virtuous-cycles[py-cost] @ git+https://github.com/anarkiwi/virtuous-cycles'
vc-py-cost --entry 'pkg.dsp.Detector.detect' --root . -o py-cost.json src/pkg
```

Arguments the tool does not know go to mypy, so sources may be files,
directories, `-p PACKAGE` or `-m MODULE`, with any mypy option (`--config-file`,
`--python-version`, ...). The modules named are analysed; everything they import
is only type-checked, and calls into it are costed by [models](#models).

| option | meaning |
|---|---|
| `--entry GLOB` | entry point, repeatable; a glob (`*`, `?`, `[...]`, `{a,b}`) over qualified names (`pkg.mod.Class.method`). An entry matching nothing is an error |
| `--models FILE` | models tried before the built-in ones |
| `--weights FILE` | `{"statement": X, "condition": Y, "call": Z}`, as for vc-cxx-cost |
| `--root DIR` | report paths relative to `DIR` |
| `--tolerate-errors-in REGEX` | type errors in matching files are printed but do not fail the run |
| `--breakdown` | list the cost of every function an entry reaches |
| `-o FILE` | report path (default stdout) |
| `-j N` | modules extracted in parallel after the mypy build (default: all cores) |

Exit status 2 on a syntax error, a type error outside `--tolerate-errors-in`, an
entry matching nothing, or a bad option. mypy runs with `check_untyped_defs` and
no cache. Progress goes to stderr.

## Cost model

As for vc-cxx-cost: one operation per statement executed and per function
entered, one per condition test (`if`, `while`, a `for` iteration, `assert`,
each `except` and `case`), a call adds the callee's cost, branches join, loops
multiply by their trip count. Python specifics:

- docstrings, `...`, `pass`, `global` and `nonlocal` cost nothing; blocks mypy
  marks unreachable (`if TYPE_CHECKING:`, version checks) cost nothing;
- operators, subscripts and attribute reads cost nothing beyond their statement
  unless they run analysed code (`__add__`, `__getitem__`, a property, ...) or a
  modelled non-constant method (`x in some_list`, `some_list[a:b]`);
- `try`: the body, a test per handler, the costliest of `else` and the
  handlers, then `finally`; `with`: each item's expression, `__enter__` and
  `__exit__`, then the body; `match`: the subject, a test and guard per case, the
  costliest body;
- a comprehension or generator expression is a loop per `for` clause, each
  iteration one test, its `if` clauses, and one operation for the element;
- a generator function's cost is its whole body; iterating it runs as many times
  as it yields (below).

### Trip counts

1. `# vc: bound(expr)` on the loop.
2. `for` over `range(...)`: constant ends give the exact count, otherwise the
   bound of the end it counts towards (a negative constant other end adds its
   magnitude; a start that is not a constant is taken as non-negative). The step
   must be a constant.
3. `for` over anything with a size: a declared `vc.Size`, a list, tuple, set or
   dict display, a string, a fixed-length tuple type, a comprehension (the
   product of its loops), a slice (its container's size), `enumerate`,
   `reversed`, `sorted`, `list`/`tuple`/`set`/`dict`/`copy` of a sized value,
   `zip` and `map` (the tighter size), `filter`, `.keys()`/`.values()`/`.items()`,
   list `+` and `*`, a generator call (its yields), a function with `@vc.size`
   or a sized return annotation.
4. A local assigned once takes the size of its value if the value is immutable
   (`int`, `str`, `tuple`, `frozenset`, `range`, ...), or if the variable is only
   read: iterated, passed to `len`/`sorted`/`sum`/..., indexed, compared,
   returned, or used through a read-only method. Anything else (an `append`, an
   index assignment, passing it to another function) drops the size.
5. A loop variable is bounded by what it ranges over: `i` in `range(n)` by `n`,
   the index of `enumerate(xs)` by `len(xs)`, an element by the declared bound of
   the elements (`Annotated[list[Annotated[int, vc.Size("k")]], ...]`).

`while` loops and everything else cost `?` iterations and are in the ledger.
`# vc: total(expr)` and `# vc: run_total(expr)` bound a loop's trip count summed
over the loops around it in its function, or over the whole run of the entry
point across calls, exactly as `VC_TOTAL` and `VC_RUN_TOTAL`.

Integer bounds: literals; `Final` constants, as symbols named after the
variable (or `vc.Symbol`) with their value reported; `vc.Size`; locals assigned
once; `len(...)` of a sized value; `+`, `*`, `-`, `//`, `>>`, `<<`, `%`, `&`,
conditional expressions, `min` (the tighter bound) and `max` (both bounds), as
for vc-cxx-cost.

A generator yields: one per `yield`, the size of the iterable of a `yield
from`, multiplied through the loops around them; branches join. A generator
whose yields have no bound, or that yields from itself, has no size.

### Calls

| callee | cost |
|---|---|
| a function, method, lambda or nested function in the analysed modules | its cost |
| a method on an instance | the join of every analysed implementation the receiver's class or its analysed subclasses can run (a `Protocol`: every analysed class that implements it); abstract methods contribute none; none at all: `?`, `virtual`. `@final` methods and classes dispatch statically |
| `super().m()`, `Class.m()`, `module.f()` | that definition |
| `C(...)` | `__new__` and `__init__` (and a dataclass's `__post_init__`); generated methods cost one call |
| a property read or write | its getter or setter |
| a local assigned once to a function or lambda | that function |
| a `Callable` value | `?`, `indirect`, unless the statement has `# vc: targets(...)` |
| a value of type `Any` | `?`, `untyped` |
| a name only `__getattr__` provides | `?`, `dynamic` |
| a function through a decorator with no `transparent` model | `?`, `indirect` |
| code outside the analysed modules | its model |

Built-ins such as `len`, `iter` or `abs` on an analysed class add the dunder
method they call. Recursion is a cycle in the call graph, as for vc-cxx-cost;
`@vc.recursion(expr)` bounds it.

### Models

Models are matched against the qualified name of the function called
(`builtins.sorted`, `builtins.list.append`, `numpy.sort`); the first whose glob
matches and whose positional argument count is within `min_args`..`max_args`
costs it. `arg` is the argument whose size is `n` (`-1`: the object); an integer
argument's bound counts as its size. A function or lambda argument multiplies
by its cost.

| `cost` | operations |
|---|---|
| `const` | 1 |
| `linear` | 1 + n |
| `nlogn` | 1 + n·log2(n) |
| `log` | 1 + log2(n) |
| `indirect`, `opaque` | `?` |
| `transparent` | a decorator that calls the function it decorates |

Built in: `sorted`, `list.sort`, `heapq.nlargest`/`nsmallest`, `numpy.sort`
and its relatives `nlogn`; `bisect` and heap pushes and pops `log`; consuming
built-ins (`sum`, `min`/`max` of one iterable, `any`, `all`, container
constructors of one argument, `str.join`, `list.extend`, `set`/`dict` updates,
`copy`, `functools.reduce`, `heapq.heapify`) `linear` in their argument; list
and deque searches, inserts and removals, and container comparisons `linear` in
the object; numpy reductions and element-wise functions `linear` in the first
argument, `ndarray` methods and operators in the object, any other `numpy`
function `opaque`; `staticmethod`, `classmethod`, `property`,
`functools.cache`/`lru_cache`/`wraps`/`cached_property`,
`contextlib.contextmanager`, `numba.njit`/`jit`, `typing.final`/`overload` and
the `vc` decorators `transparent`; every other function of `builtins`, `math`,
`operator`, `typing`, `functools`, `itertools`, `collections`, `random`, `time`,
`io`, `os`, `logging` and the like `const`. Hashed containers are costed by their
average, not worst, case. Anything else is `?`, `external`, until modelled:

```json
[{"match": "json.loads", "cost": "linear", "arg": 0},
 {"match": "mypkg.retry", "cost": "transparent"}]
```

## Annotations

`from virtuous_cycles import vc`. The annotations do nothing at runtime.

| annotation | on | meaning |
|---|---|---|
| `# vc: bound(expr)` | a loop | its trip count |
| `# vc: total(expr)` | a loop | its trip count summed over the loops around it in its function |
| `# vc: run_total(expr)` | a loop | its trip count summed over every execution in one run of the entry point, across calls |
| `# vc: targets(glob, ...)` | a statement | one operation plus the costliest of the named functions |
| `# vc: cost(expr)` | a statement | its whole cost |
| `Annotated[T, vc.Size(expr)]` | a variable, parameter, field or return type | upper bound of the value (an integer) or length (a container); nest for elements |
| `Annotated[int, vc.Symbol("name")]` | a `Final` constant | the symbol it is reported as |
| `@vc.cost(expr)` | a function | its whole cost |
| `@vc.size(expr)` | a function | the bound of what it returns; for a generator, its yields |
| `@vc.recursion(expr)` | a function in a recursive cycle | activations of the cycle per call |

A `# vc:` comment applies to the statement on its line, or, on lines of its own,
to the next statement. `expr` has the syntax of vc-cxx-cost's annotations.

## Report

The report of [vc-cxx-cost](cxx-cost.md#report), with Python names and an
additional ledger kind for each of `untyped` and `dynamic`. Columns are
1-based.

## Tests

```sh
scripts/docker-test pytest tests/test_pycost.py
```

`tests/py_cost/pyfix` is a package of small functions; `tests/test_pycost.py`
checks each one's polynomial and ledger kinds against hand-derived values.
