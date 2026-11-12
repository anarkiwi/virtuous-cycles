"""vc-py-cost: worst-case cost of Python entry points as a polynomial in declared
capacities, with a ledger of what has no bound."""

import argparse
import contextlib
import multiprocessing
import os
import re
import sys
import time

from tqdm import tqdm

from mypy import build
from mypy.errors import CompileError
from mypy.main import process_options

from virtuous_cycles.cost.program import Program, dumps
from virtuous_cycles.pycost.extract import Analysis, extract
from virtuous_cycles.pycost.models import Weights, parse_models, parse_weights

_ANALYSIS = None


def _extract(module):
    return module, extract(_ANALYSIS, [module])


def _parser():
    ap = argparse.ArgumentParser(
        prog="vc-py-cost",
        description=__doc__,
        epilog="Other arguments (sources, -p PACKAGE, --config-file, ...) go to mypy.",
    )
    ap.add_argument("--entry", action="append", required=True, metavar="GLOB")
    ap.add_argument("-o", dest="output", default="-", help="report path (- for stdout)")
    ap.add_argument("--root", default="", help="report paths relative to DIR")
    ap.add_argument("--models", help="JSON models tried before the built-in ones")
    ap.add_argument(
        "--weights", help='JSON {"statement": X, "condition": Y, "call": Z}'
    )
    ap.add_argument(
        "--tolerate-errors-in",
        metavar="REGEX",
        help="type errors in matching files are printed but do not fail the run",
    )
    ap.add_argument("--breakdown", action="store_true")
    ap.add_argument("-j", type=int, default=0, help="parallel workers (default: all)")
    return ap


def _read(path, parse, what):
    try:
        with open(path, encoding="utf-8") as f:
            return parse(f.read())
    except (OSError, ValueError) as e:
        raise SystemExit(f"vc-py-cost: {what} {path}: {e}") from e


def _build(mypy_args):
    sources, options = process_options(mypy_args, require_targets=True)
    options.preserve_asts = True
    options.export_types = True
    options.incremental = False
    options.check_untyped_defs = True
    options.cache_dir = os.devnull
    try:
        return sources, build.build(sources, options)
    except CompileError as e:
        for m in e.messages:  # pylint: disable=no-member
            print(m, file=sys.stderr)
        raise SystemExit(2) from e


def _errors(result, tolerate):
    failed = set()
    for path, infos in result.manager.errors.error_info_map.items():
        if any(i.severity == "error" for i in infos):
            if not (tolerate and tolerate.search(path)):
                failed.add(path)
    for m in result.errors:
        print(m, file=sys.stderr)
    return failed


def _options(args):
    """The models, weights and tolerated-error pattern ``args`` name."""
    models = _read(args.models, parse_models, "models") if args.models else []
    weights = (
        _read(args.weights, parse_weights, "weights") if args.weights else Weights()
    )
    try:
        tolerate = (
            re.compile(args.tolerate_errors_in) if args.tolerate_errors_in else None
        )
    except re.error as e:
        raise SystemExit(f"vc-py-cost: --tolerate-errors-in: {e}") from e
    return models, weights, tolerate


def _summarise(modules, jobs):
    """The merged summaries of ``modules``, extracted by ``jobs`` workers."""
    program = Program()
    progress = tqdm(total=len(modules), unit="mod", file=sys.stderr, desc="vc-py-cost")
    with contextlib.ExitStack() as stack:
        if jobs > 1:
            pool = stack.enter_context(multiprocessing.get_context("fork").Pool(jobs))
            parts = pool.imap_unordered(_extract, modules)
        else:
            parts = map(_extract, modules)
        for module, part in parts:
            program.merge(part)
            progress.set_postfix_str(module, refresh=False)
            progress.update()
    progress.close()
    return program


def _write(path, text):
    if path == "-":
        sys.stdout.write(text)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def _modules(mypy_args):
    """The mypy build of ``mypy_args`` and the source modules it analysed."""
    start = time.monotonic()
    sources, result = _build(mypy_args)
    modules = sorted(
        {s.module for s in sources if getattr(result.graph.get(s.module), "tree", None)}
    )
    print(
        f"vc-py-cost: mypy analysed {len(modules)} modules"
        f" in {time.monotonic() - start:.1f}s",
        file=sys.stderr,
    )
    return result, modules


def main(argv=None):
    """Run the analysis; exit status 2 on errors."""
    # pylint: disable=global-statement
    global _ANALYSIS
    args, mypy_args = _parser().parse_known_args(argv)
    models, weights, tolerate = _options(args)
    root = os.path.normpath(os.path.abspath(args.root)) if args.root else ""
    result, modules = _modules(mypy_args)
    failed = _errors(result, tolerate)
    _ANALYSIS = Analysis(result, modules, root, models, weights)
    program = _summarise(modules, min(args.j or os.cpu_count() or 1, len(modules)))
    try:
        entries = program.resolve(args.entry, args.breakdown)
    except ValueError as e:
        print(f"vc-py-cost: {e}", file=sys.stderr)
        return 2
    _write(args.output, dumps(program, entries))
    for path in sorted(failed):
        print(f"vc-py-cost: {path} has type errors", file=sys.stderr)
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
