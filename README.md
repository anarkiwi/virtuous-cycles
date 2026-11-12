# virtuous-cycles

Hold numeric code metrics to committed budgets that can only get stricter: a
ratchet, like [imbue-ai/ratchets](https://github.com/imbue-ai/ratchets) for lint
counts, but for any per-key number (Infer cost degree, coverage, sizes, ...).
Metrics may also carry hard limits.

## Install

```sh
pip install git+https://github.com/anarkiwi/virtuous-cycles
```

## Usage

`virtuous-cycles.toml`:

```toml
[[metric]]
name = "complexity"
adapter = "infer-cost"
budget = "budgets/complexity.json"
select = ["dsp::*", "infer-cost:unknown"]
[metric.options]
report = "infer-out/costs-report.json"
value = "degree"
```

```sh
virtuous-cycles tighten                 # record or ratchet budgets, drop gone keys
virtuous-cycles check                   # non-zero if anything is worse or unbudgeted
virtuous-cycles check --against origin/main   # also non-zero if a budget was loosened
virtuous-cycles report [--json]         # value, budget and status per key
```

Commit the budget files. To merge them by keeping the stricter value per key:

```sh
git config merge.virtuous-cycles.driver 'virtuous-cycles merge-driver %O %A %B %P'
echo 'budgets/*.json merge=virtuous-cycles' >> .gitattributes
```

## Docs

- [docs/usage.md](docs/usage.md): configuration, commands, budget files, merging, CI.
- [docs/adapters.md](docs/adapters.md): `infer-cost`, `json`, `command`, `cxx-cost`, `py-cost`, and writing an adapter.
- [docs/cxx-cost.md](docs/cxx-cost.md): `vc-cxx-cost`, a clang tool bounding C++
  worst-case cost as a polynomial in declared capacities, with a ledger of
  what it cannot bound.
- [docs/py-cost.md](docs/py-cost.md): `vc-py-cost` (`pip install
  'virtuous-cycles[py-cost]'`), the same bound for Python, built on mypy.
- [docs/development.md](docs/development.md): tests and the Infer fixture.

## License

Apache-2.0.
