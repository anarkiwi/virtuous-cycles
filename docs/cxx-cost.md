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

Each release publishes that image as `ghcr.io/anarkiwi/virtuous-cycles/cxx-cost:<tag>`,
so CI need not build it. In GitHub Actions, `uses: anarkiwi/virtuous-cycles/cxx-cost@<tag>`
pulls it and puts a `vc-cxx-cost` command on `PATH`:

```yaml
- uses: anarkiwi/virtuous-cycles/cxx-cost@v0.5.0
- run: vc-cxx-cost -p build --entry 'ns::Detector::detect' -o cxx-cost.json
```

To build without Docker, on Ubuntu 24.04: `apt install clang-20 libclang-20-dev
llvm-20-dev libclang-common-20-dev libclang-rt-20-dev libstdc++-14-dev cmake
ninja-build`, then `CC=clang-20 CXX=clang++-20 cmake -S cxx-cost -B build -G Ninja
-DCMAKE_PREFIX_PATH=/usr/lib/llvm-20 && cmake --build build`, and copy
`vc-cxx-cost` to `/usr/lib/llvm-20/bin` (where it finds clang's builtin headers).

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
| `--root DIR` | report paths relative to `DIR` (a relative `DIR`, such as `.`, is made absolute first) |
| `--weights FILE` | what each kind of operation costs (below) |
| `--tolerate-errors-in REGEX` | compile errors in files matching `REGEX` are printed but do not fail the run (below) |
| `--breakdown` | list the cost of every function an entry reaches |
| `-o FILE` | report path (default stdout) |
| `--emit-ir FILE` | write the merged per-function summaries before composition (the input `python -m virtuous_cycles.cost.ir` composes); for cross-checking |
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
  upper bound of the larger); `switch`: the most expensive path, which is from
  each case label to the first statement that cannot fall through (`break`,
  `continue`, `return`, `goto`, `throw`), so a case that falls through adds its
  successor;
- loop: trip count × (condition + body + increment) + one final condition;
- call: the callee's cost, composed through the call graph across all
  translation units;
- a function cost per entry point is the join of the functions its glob names.

Implicit and defaulted member functions cost 1; implicit destructors are not
counted.

`--weights FILE` takes `{"statement": X, "condition": Y, "call": Z}` (any subset;
the rest stay 1) and gives each kind its own cost: `statement` is an expression,
declaration or return, `condition` an `if`, loop or `switch` test and a loop
step, `call` a function entered and a modelled library call. Use it to turn
operation counts into something nearer time on a target, for instance a larger
`call` for a core without a hardware divider.

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

4. A pointer or iterator walked from the start of an array or container to its
   end, once per element, with the variable not written in the body:
   `for (T *p = a; p < a + N; ++p)` runs `N` times, and `for (auto i = c.begin();
   i != c.end(); ++i)` runs as many times as `c` has capacity (`vc::Capped`,
   `std::array`, a C array, or `VC_SIZE` on the container). A body that steps
   the iterator itself (`erase(i--)`) is not counted.

Anything else (`while`, `do`, a loop on a value with no bound) costs `?`
iterations and is in the ledger. `VC_TOTAL(expr)` on a loop bounds its trip
count summed over every iteration of the loops around it in the same function,
for work that all of them share:

```cpp
for (Channel &C : Channels)                 // 9 channels
  VC_TOTAL(kNotes) for (Note *N : C.notes)  // all channels draw on kNotes notes
    N->tick();
```

costs `kNotes` ticks, not `9 * kNotes`.

`VC_TOTAL` is per call of its function. When the loop is in a function that the
loop over channels *calls*, the total has to cross the call, and
`VC_RUN_TOTAL(expr)` does: it bounds the trip count summed over every execution
of the loop in one run of the entry point, however many calls deep, and neither
the loops around it in its function nor those around the calls that reach it
multiply it.

```cpp
void Channel::tick() {                      // called once per channel
  VC_RUN_TOTAL(kNotes) for (Note *N : notes_) N->tick();   // 9 channels, kNotes notes in all
}
```

Only the loop's own cost moves out; its setup and the call overhead still scale
as usual. A loop reached from two call sites counts once per site. The total is
scaled by the loops around the call when the call is joined with others (a
virtual call, `VC_TARGETS`, or either branch of `?:`/`if`) or is in a recursive
cycle, so those are over-counted rather than under-counted.

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
| a pointer, member pointer or `std::function` | `?`, `indirect`, unless the statement has `VC_TARGETS` |
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
| `VC_TOTAL(expr)` | a loop | its trip count summed over the loops around it in its function |
| `VC_RUN_TOTAL(expr)` | a loop | its trip count summed over every execution in one run of the entry point, across calls |
| `VC_TARGETS(a, b)` | a statement | one operation plus the costliest of the named functions (globs over qualified names, as for `--entry`) |
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
`indirect`, `library` (a modelled call on a range with no bound), `annotation`,
`error` (an expression or function with compile errors, below). The ledger of
an entry is that of every function it reaches. With `--breakdown` each entry
also has `"breakdown"`: the cost of every function it reaches,
`[{"function": ..., "polynomial": ...}]`, sorted by name.

### Errors in third-party headers

By default a translation unit with any compile error fails the run.
`--tolerate-errors-in REGEX` prints errors in files matching `REGEX` but does not
count them, and lifts clang's 19-error limit. Tolerating an error never hides
cost: an expression clang could not resolve costs `?` and a function declared
with errors adds `?`, each with a ledger entry of kind `error`. It helps when a
vendored header fails in code the analysed sources do not use; code that does
depend on a rejected declaration stays unbounded, and is better fixed by
patching or stubbing the header.

## Tests

```sh
docker build --target cxx-test -t vc-cxx-cost:test . && docker run --rm vc-cxx-cost:test
```

clang-format, then the lit fixtures under `cxx-cost/test` (each FileChecks the
exact polynomial and ledger of small sources) on a coverage-instrumented build,
then a line-coverage gate. `ratchet.test` runs the report through
`virtuous-cycles check`: a nested loop over a capacity fails the budget and a
degree limit, an unbounded loop fails the ledger and cost budgets. Every
fixture runs the tool through `test/crosscheck.py`, which also composes its
`--emit-ir` output with the Python backend and fails on any difference from
the C++ report.
