# Adapters

An adapter is a function `(options: dict) -> dict[str, float]` registered by
name. Values are compared with the metric's `direction`; `inf` is allowed.

```python
from virtuous_cycles import register

@register("clang-loops")
def clang_loops(options):
    return {"ns::f": 2.0}
```

Out-of-tree adapters register through the `virtuous_cycles.adapters` entry-point
group and load on first use:

```toml
[project.entry-points."virtuous_cycles.adapters"]
clang-loops = "my_package.adapters:clang_loops"
```

## `infer-cost`

Reads [Infer](https://fbinfer.com/docs/checker-cost)'s `costs-report.json`
(`infer --cost-only`). One key per procedure plus a count of unbounded ones.

| option        | default                        | meaning |
|---------------|--------------------------------|---------|
| `report`      | `infer-out/costs-report.json`  | report path |
| `value`       | `degree`                       | `degree` or `polynomial` |
| `symbols`     | `{}`                           | symbol text to value for `polynomial`, e.g. `{n = 4096, "this->len" = 64}` |
| `default`     | none                           | value for symbols not in `symbols`; without it an unlisted symbol is an error |
| `key`         | `{procedure_id}`               | `str.format` template over the entry (`procedure_id`, `procedure_name`, `hash`) and its `loc` (`file`, `lnum`) |
| `cost`        | `exec_cost`                    | cost field to read |
| `unknown_key` | `infer-cost:unknown`           | key holding the number of keys whose cost is ⊤ (`inf`) |
| `callgraph`   | none                           | output of `infer debug --procedures --procedures-name --procedures-callees --select all`; keeps only procedures reached from `roots` |
| `roots`       | required with `callgraph`      | entry-point procedure globs (`fnmatch`, case-sensitive), e.g. `["ns::Detector::detect"]`; one that matches nothing is an error |

- `degree` is Infer's encoded degree divided by 100: `1` for O(n), `2` for
  O(n x m), and a log factor adds `0.01`.
- `polynomial` evaluates `hum_polynomial` at the given symbol values. Symbols
  are written as Infer prints them (`n`, `this->len`, `(*p).size`,
  `v.cpp.vector_elem.length`). Both UTF-8 (`⋅`, `×`, superscripts) and C-locale
  (`.`, `x`, `^`) output parse.
- An unbounded cost (Infer's ⊤, `hum_degree` `Top`) is `inf`; unreachable code
  is `0`.
- Infer's `procedure_id` does not carry C++ parameter types, so overloads share
  a key; the key keeps the worst of them. Add `{file}` to the template to
  separate same-named procedures across files.

## `json`

| option | meaning |
|--------|---------|
| `file` | JSON file |
| `path` | JSONPath-like: `$.a.b`, `a[0]`, `a[-1]`, `a["k.with.dots"]`, `*` / `[*]` wildcards |
| `sep`  | joins wildcard captures into the key (default `/`) |
| `key`  | key when the path has no wildcard (default: the path) |

`path = "files.*.summary.percent_covered"` over coverage.py's JSON gives one key
per file.

## `command`

| option | meaning |
|--------|---------|
| `run`  | argv list, or a string split with `shlex` (no shell) |
| `cwd`  | working directory |

The command must exit 0 and print a JSON object of key to number.

### Reachability

With `callgraph` and `roots`, only procedures reachable from the roots are
kept, and the unknown count covers only those. Names in the call graph are
normalised to `procedure_id` spelling: the `{id}`/`(id)` suffix, a leading
`class ` and the parameter list are dropped; commas and `<`/`>` inside template
arguments and C++ operator names (`operator()`, `operator->`, `operator<<`)
are not separators.

```toml
[[metric]]
name = "boxer-cost"
adapter = "infer-cost"
budget = "budgets/boxer-cost.json"
[metric.options]
report = "infer-out/costs-report.json"
callgraph = "procs.txt"
roots = ["ns::Detector::detect", "ns::SceneBoxer::cut"]
```

The unknown count is an ordinary key, so the same budget ratchets it: select
only `infer-cost:unknown` in a metric to hold just the count of unbounded
procedures.
