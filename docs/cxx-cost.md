# vc-cxx-cost

A clang 20 LibTooling tool (`cxx-cost/`) that bounds the worst-case operation
count of C++ entry points as a polynomial in declared capacities, and lists
everything it cannot bound in a ledger. The `cxx-cost` adapter
([adapters.md](adapters.md#cxx-cost)) ratchets its report.

## Build and run

```sh
docker build --target cxx-runtime -t vc-cxx-cost .
docker run --rm -v "$PWD:$PWD" -w "$PWD" vc-cxx-cost \
  -p build --files '/lib/dsp/' --entry 'ns::Detector::detect' -o cxx-cost.json
```

The binary links Ubuntu 24.04's clang 20. To run it in another Ubuntu 24.04
image (one that has the project's headers), copy
`/usr/lib/llvm-20/bin/vc-cxx-cost` from the `cxx-runtime` stage and install
`libclang-cpp20 libllvm20 libclang-common-20-dev`; it must stay in
`/usr/lib/llvm-20/bin` to find clang's builtin headers.

| option | meaning |
|---|---|
| `--entry GLOB` | entry point, repeatable; matches qualified names with or without template arguments (`ns::total<*`). An entry matching nothing is an error |
| `-p DIR` | directory holding `compile_commands.json` |
| `SOURCES...` | translation units; without them, every file of the database matching `--files REGEX` |
| `--drop-arg REGEX` | remove matching compiler arguments (flags clang rejects) |
| `--extra-arg ARG` | add a compiler argument |
| `--models FILE` | system-function models tried before the built-in ones (below) |
| `--root DIR` | report paths relative to `DIR` |
| `-o FILE` | report path (default stdout) |
| `-j N` | translation units in parallel (default: all cores) |

Exit status 2 if a translation unit does not compile, an entry matches
nothing, or an option is bad. Progress (`[k/N elapsed TU/s] file`) goes to
stderr.

## Cost model

One operation per statement executed (an expression, declaration, return,
condition test or loop increment) and per function entered; a call adds the
callee's cost. Costs are polynomials with non-negative coefficients in
symbols that are non-negative:

- sequence: sum; `if`/`?:`: coefficient-wise maximum of the branches (an
  upper bound of the larger); `switch`: sum of its cases;
- loop: trip count × (condition + body + increment) + one final condition;
- call: the callee's cost, composed through the call graph across all
  translation units;
- a function cost per entry point is the join of the functions its glob names.

Implicit and defaulted member functions cost 1; implicit destructors are not
counted.

### Trip counts

In order of preference:

1. `VC_BOUND(expr)` on the loop.
2. Counted `for` loops: one counter, stepped by a constant (`++i`, `i += 2`,
   `i--`, or `i-- > 0` in the condition), not written in the body, compared
   (`<`, `<=`, `!=`, `>`, `>=`, either side) with a bounded limit. Constant
   start and limit give the exact count; otherwise the limit's bound (+1 for
   `<=`/`>=`). `!=` with a step other than 1 needs constant ends that the step
   divides.
3. Range `for` over a container with a capacity: `vc::Capped<T, N>` (or any
   class template annotated `VC_CAPPED`, whose last non-type parameter is the
   capacity), `std::array<T, N>`, a C array, an initializer list, or a
   declaration annotated `VC_SIZE`.

Anything else (`while`, `do`, a loop on a value with no bound) costs `?`
iterations and is in the ledger.

A limit's bound comes from: integer constants; namespace or class constants
(a *symbol* named after the variable, or `VC_SYMBOL(name)`), whose value is
reported; `VC_SIZE` on the variable, field, parameter or function; `const`
locals from their initialiser; `.size()`/`.capacity()`/`std::size` of a
container with a capacity; `+`, `*`, `-`, `/`, `>>`, `<<`, `%`, `&`, `?:`,
`std::min` (the tighter bound), `std::max` (both bounds). A template
parameter's value is named by the one symbol with that value, else stays a
number.

### Calls

| callee | cost |
|---|---|
| a function with a body in the analysed units | its cost |
| `VC_COST(expr)` on any declaration | `expr` |
| virtual, not devirtualisable | join of every overrider in the analysed units (a pure method contributes none); none: `?` and a `virtual` ledger entry |
| a declaration with no body | `?`, `external` |
| a pointer, member pointer or `std::function` | `?`, `indirect` |
| a system-header function | its model |

Recursion is a cycle in the resolved call graph. Unannotated it costs `?` ×
the cycle's body costs and is in the ledger; `VC_RECURSION(n)` on a function of
the cycle bounds its activations per call to `n`. A backward `goto` makes the
function's body cost `?` times.

### Models

The first model whose glob matches a system function's qualified name (no
template arguments, no inline namespaces) costs it; one call with fewer than
`min_args` arguments is skipped. `n` is the size of argument `arg` (`-1`: the
object): an integer's bound, an iterator's container (`x.begin()`,
`std::begin(x)`, `x.data()`, `first + k`), or a container's capacity. A callable
argument (lambda, functor, function) multiplies by its cost.

| `cost` | operations |
|---|---|
| `const` | 1 |
| `linear` | 1 + n |
| `nlogn` | 1 + n·log2(n) |
| `log` | 1 + log2(n) |
| `indirect`, `opaque` | `?` |

Built in: `std::sort`-family `nlogn`; binary searches and heap pushes `log`;
the range algorithms of `<algorithm>`/`<numeric>` `linear` in the first
range; `*_n` in the count; `memcpy`/`memset`/`memmove`/`memcmp` in the byte
count; `std::map`/`set` lookups `log` in the object; `std::vector`
growth/assignment `linear`, moves `const`; `std::function` `indirect`; every
other `std::` function, libc math and `operator new`/`delete` `const`.
Any other system function is `opaque` until modelled:

```json
[{"match": "nlohmann::*", "cost": "const"},
 {"match": "fftwf_execute", "cost": "nlogn", "arg": 0}]
```

## Annotations

`#include <vc/cost.h>` (in `cxx-cost/include`). The macros are
`[[clang::annotate]]` attributes under clang 20 and expand to nothing under any
other compiler.

| macro | on | meaning |
|---|---|---|
| `VC_BOUND(expr)` | a loop | its trip count |
| `VC_COST(expr)` | a statement or function declaration | its whole cost |
| `VC_SIZE(expr)` | a variable, field, parameter or function | upper bound of the value (integer) or size (container) |
| `VC_RECURSION(expr)` | a function in a recursive cycle | activations of the cycle per call |
| `VC_SYMBOL(name)` | a constant | the symbol it is reported as |
| `VC_CAPPED` | a class template | its last non-type parameter is a capacity |

`expr` is a sum of products of non-negative integers, symbols, `s^k`,
`log2(...)` and parentheses; `a::b::name` is the symbol `name`, `x.n` and
`p->n` are symbols. `?` makes it unbounded and adds a ledger entry, as does an
annotation that does not parse or a `VC_BOUND` that is not on a loop.

`vc::Capped<T, N>` is a fixed-capacity array: `push_back` past `N` returns
false and counts the drop in `dropped()`.

## Report

```json
{
 "version": 1,
 "unbounded_symbol": "?",
 "symbols": {"kMaxBoxes": 256, "nfft": null},
 "entries": {
  "ns::detect": {
   "functions": ["ns::detect"],
   "polynomial": "2*kMaxBoxes^2 + 3*? + 7",
   "terms": [{"coefficient": 2, "powers": {"kMaxBoxes": 2}}, ...],
   "degree": {"kMaxBoxes": 2, "?": 1},
   "ledger": [{"kind": "loop", "function": "ns::g", "file": "lib/a.cc",
               "line": 12, "column": 3,
               "reason": "while loop with no bound on `n > 0`"}]
  }
 }
}
```

`symbols` lists the symbols the polynomials use and their values where every
translation unit agrees on one (`null` otherwise). `log2(s)` symbols take their
value from `s`. Ledger kinds: `loop`, `recursion`, `virtual`, `external`,
`indirect`, `library` (a modelled call on a range with no bound),
`annotation`. The ledger of an entry is that of every function it reaches.

## Tests

```sh
docker build --target cxx-test -t vc-cxx-cost:test . && docker run --rm vc-cxx-cost:test
```

clang-format, then the lit fixtures under `cxx-cost/test` (each FileChecks the
exact polynomial and ledger of small sources) on a coverage-instrumented build,
then a line-coverage gate. `ratchet.test` runs the report through
`virtuous-cycles check`: a nested loop over a capacity fails the budget and a
degree limit, an unbounded loop fails the ledger and cost budgets.
