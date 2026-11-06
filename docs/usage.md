# Usage

## Configuration

`virtuous-cycles.toml` (or `-c PATH`) holds a list of `[[metric]]` tables.
Relative paths, in the table and in adapter options, are relative to the
config file's directory; commands run there.

| field       | default        | meaning                                                  |
|-------------|----------------|----------------------------------------------------------|
| `adapter`   | required       | registered adapter name                                  |
| `budget`    | required       | committed budget file for this metric                    |
| `name`      | the adapter    | label in output and for `-m/--metric`; unique            |
| `direction` | `lower`        | `lower` or `higher` is better                            |
| `select`    | `["*"]`        | `fnmatch` globs (case-sensitive); a key is kept if any matches |
| `options`   | `{}`           | passed to the adapter                                    |

## Commands

Global flags: `-c/--config PATH`, `-m/--metric NAME` (repeatable), `-q/--quiet`
(no progress bars on stderr).

- `check`: exit 1 if a value is worse than its budget or a selected key has no
  budget. Keys in the budget that are no longer measured are not failures.
- `check --against REF`: also exit 1 if any key's budget in the working tree is
  looser than in the same budget file at git `REF` (read with `git show`), or
  the file's direction changed. Keys added or removed since `REF` are allowed:
  a removed key that still exists fails the plain check as unbudgeted.
- `tighten`: for each measured key, set the budget to the current value where
  that is stricter, add keys with no budget at their current value, and drop
  budget keys no longer measured. It never loosens an existing budget.
- `report [--json]`: one row per key with value, budget and status (`ok`,
  `better`, `worse`, `new`, `gone`).

Exit status 2 is a configuration, adapter or git error.

## Budget files

```json
{
 "direction": "lower",
 "budgets": {
  "dsp::product": 2.0,
  "unknown": Infinity
 }
}
```

One key per line, sorted, so diffs and merges stay small. `Infinity` (Python's
JSON extension) records an unbounded value; any finite value later tightens it.

## Merging

`merge-driver %O %A %B [%P]` merges budget files three ways. A key present on
both sides takes the stricter value; a key on one side only is kept if that side
added it and dropped if the other side removed it. Mismatched directions are a
conflict (exit 1).

```sh
git config merge.virtuous-cycles.driver 'virtuous-cycles merge-driver %O %A %B %P'
git config merge.virtuous-cycles.name 'keep the stricter budget per key'
```

`.gitattributes`:

```
budgets/*.json merge=virtuous-cycles
```

## CI

On pull requests, check values and that no budget was loosened relative to the base:

```sh
virtuous-cycles check --against origin/${GITHUB_BASE_REF}
```

Developers run `virtuous-cycles tighten` after an improvement and commit the
budget change.
