# Development

Everything runs in Docker; nothing is installed on the host.

```sh
scripts/docker-test                  # black --check, pylint, pytest (xdist, coverage gate)
scripts/docker-test pytest tests/test_infer.py
```

`scripts/docker-test` builds the `test` stage of `Dockerfile` and runs it as
the calling user against the checkout, bind-mounted at the same path.

## Infer fixture

`tests/infer/costs-report.json` and `tests/infer/procs.txt` (the call graph) are real output of a pinned Infer release on
`tests/infer/example.cpp` (linear and quadratic loops, a two-symbol loop,
overloads, templates, operators, a lambda, and an unmodelled call giving ⊤). `tests/infer/Dockerfile` pins the
release; CI builds its `check` stage, which reruns Infer and compares the
procedures, degrees, polynomials and call graph with the committed files. To regenerate:

```sh
docker build --target fixture --output tests/infer tests/infer
```

`tests/infer/probe/` holds further Infer v1.3.0 reports on small sources
(`shapes*.cc`), produced in the C locale (ASCII operators), covering ⊤,
nested loops, `min`/`max` bounds and member-path symbols.
