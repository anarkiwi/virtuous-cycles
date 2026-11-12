import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from virtuous_cycles import vc
from virtuous_cycles.pycost import cli
from virtuous_cycles.pycost.extract import Analysis, extract
from virtuous_cycles.pycost.models import (
    Weights,
    builtin_models,
    parse_models,
    parse_weights,
)
from virtuous_cycles.pycost.source import Meta, meta, read

FIX = Path(__file__).parent / "py_cost"


@pytest.fixture(scope="module")
def analysis():
    sources, result = cli._build([str(FIX / "pyfix")])  # pylint: disable=W0212
    return Analysis(result, sorted(s.module for s in sources), str(FIX))


def resolve(a, *patterns):
    program = extract(a, sorted(a.trees))
    return {e.pattern: e for e in program.resolve(list(patterns))}, program


def kinds(entry):
    return sorted({l.kind for l in entry.ledger})


CASES = [
    ("pyfix.loops.linear", "2*n + 4", []),
    ("pyfix.loops.nested", "2*n^2 + 3*n + 6", []),
    ("pyfix.loops.constant", "11", []),
    ("pyfix.loops.down", "2*m + 7", []),
    ("pyfix.loops.capped", "2*kMax + 5", []),
    ("pyfix.loops.unbounded", "2*? + 3", ["loop"]),
    ("pyfix.loops.bounded", "2*kMax + 3", []),
    ("pyfix.loops.misplaced", "3", ["annotation"]),
    ("pyfix.loops.grid", "2*m*n + 2*n + 4", []),
    ("pyfix.loops.shared", "2*kPool + 2*n + 4", []),
    ("pyfix.loops.local", "log2(n)*n + 2*n + 9", []),
    ("pyfix.loops.mutated", "2*? + 7", ["loop"]),
    ("pyfix.loops.squares", "3*n + 2", []),
    ("pyfix.loops.counted", "2*n^2 + 3*n + 5", []),
    ("pyfix.loops.bad_annotation", "2*? + 3", ["annotation"]),
    ("pyfix.calls.twice", "6", []),
    ("pyfix.calls.fact", "4*?", ["recursion"]),
    ("pyfix.calls.walk", "4*depth", []),
    ("pyfix.calls.use_priced", "3*kMax + 2", []),
    ("pyfix.calls.keyed", "2*log2(n)*n + 3", []),
    ("pyfix.calls.via_local", "5", []),
    ("pyfix.calls.indirect", "? + 2", ["indirect"]),
    ("pyfix.calls.chosen", "8", []),
    ("pyfix.calls.call_wrapped", "? + 2", ["indirect"]),
    ("pyfix.calls.untyped", "? + 2", ["untyped"]),
    ("pyfix.calls.branches", "6", []),
    ("pyfix.calls.risky", "8", []),
    ("pyfix.calls.matcher", "6", []),
    ("pyfix.classes.total", "2*kMax + 7", []),
    ("pyfix.classes.exact", "4", []),
    ("pyfix.classes.make_sub", "9", []),
    ("pyfix.classes.proto", "2*kMax + 7", []),
    ("pyfix.classes.none", "? + 2", ["virtual"]),
    ("pyfix.classes.prop", "4", []),
    ("pyfix.classes.point", "6", []),
    ("pyfix.classes.use_ctx", "7", []),
    ("pyfix.classes.dyn", "? + 2", ["dynamic"]),
    ("pyfix.classes.run", "6*kChannels + 2*kNotes + 4", []),
    ("pyfix.gens.consume", "4*n + 6", []),
    ("pyfix.gens.gen_not_counter", "4*n + 6", []),
    ("pyfix.gens.offset", "4*n + 31", []),
    ("pyfix.gens.consume_chain", "3*n + 9", []),
    ("pyfix.gens.lib", "? + 2*n + 8", ["library"]),
    ("pyfix.gens.external", "? + 2", ["external"]),
    ("pyfix.classes.vec_ops", "28", []),
    ("pyfix.classes.accumulate", "8", []),
    ("pyfix.classes.warm", "19", []),
    ("pyfix.classes.build_maker", "14", []),
    ("pyfix.classes.speak", "8", []),
    ("pyfix.classes.finals", "11", []),
    ("pyfix.classes.drain", "7*kMax + 8", []),
    ("pyfix.classes.use_lazy", "2*kMax + 7", []),
    ("pyfix.classes.use_bag", "4*n + 6", []),
    ("pyfix.classes.use_odd", "3*? + 5", ["annotation"]),
    ("pyfix.gens.consume_capped", "2*k + 2*n + 6", []),
    ("pyfix.gens.consume_shapes", "n + 43", []),
    ("pyfix.gens.consume_unsized", "2*? + 6", ["loop"]),
    ("pyfix.gens.consume_walk", "5*? + 2", ["library", "recursion"]),
    ("pyfix.gens.tail", "? + 2", ["library"]),
    ("pyfix.loops.sizes", "2*k + 4*n + 38", []),
    ("pyfix.loops.arith", "6*n + 108", []),
    ("pyfix.loops.displays", "2*m + 4*n + 53", []),
    ("pyfix.loops.comps", "2*? + 5*n + 8", ["loop"]),
    ("pyfix.loops.pairs", "2*n + 5", []),
    ("pyfix.loops.misc", "2*n + 16", []),
    ("pyfix.calls.call_any", "? + 2", ["untyped"]),
    ("pyfix.calls.rank", "2*log2(n)*n + 6", []),
    ("pyfix.calls.use_pick", "4", []),
    ("pyfix.calls.use_produce", "3*kMax + 6", []),
    ("pyfix.calls.outer", "7", []),
    ("pyfix.calls.use_opened", "5", []),
    ("pyfix.calls.use_cached", "6", []),
    ("pyfix.calls.gather_all", "28", []),
    ("pyfix.loops.bounds_more", "2*k^2 + 5*k + 2*m + 14*n + 32", []),
    ("pyfix.loops.unsized", "17*? + 20", ["library", "loop"]),
    ("pyfix.loops.use_made", "2*k + 6", []),
    ("pyfix.loops.anything", "2*? + 3", ["annotation"]),
    ("pyfix.loops.Cursor.scan", "n + 3", []),
    ("pyfix.gens.consume_sparse", "? + 8*n + 12", ["library"]),
    ("pyfix.gens.opaque", "? + 2", ["external"]),
    ("pyfix.calls.misc2", "22", []),
    ("pyfix.calls.via_builtin", "? + 3", ["indirect"]),
    ("pyfix.calls.held", "? + 4", ["indirect"]),
    ("pyfix.calls.partial_call", "? + 4", ["indirect"]),
    ("pyfix.classes.generic", "2*kMax + 8", []),
]


@pytest.mark.parametrize("entry,poly,ledger", CASES, ids=[c[0] for c in CASES])
def test_cost(analysis, entry, poly, ledger):
    entries, _ = resolve(analysis, entry)
    e = entries[entry]
    assert str(e.cost) == poly
    assert kinds(e) == ledger


def test_symbols_and_reasons(analysis):
    entries, program = resolve(
        analysis, "pyfix.loops.capped", "pyfix.loops.unbounded", "pyfix.loops.mutated"
    )
    assert program.symbols["kMax"] == 16
    (why,) = entries["pyfix.loops.unbounded"].ledger
    assert why.reason == "while loop with no bound on `k > 0`"
    assert (why.at.file, why.at.line, why.at.column) == ("pyfix/loops.py", 47, 5)
    (why,) = entries["pyfix.loops.mutated"].ledger
    assert why.reason == "for loop over `ys` (list[int]), which has no size"


def test_ledger_sites_follow_generators(analysis):
    entries, _ = resolve(analysis, "pyfix.classes.use_odd")
    (why,) = entries["pyfix.classes.use_odd"].ledger
    assert (why.at.file, why.at.line) == ("pyfix/gens.py", 115)


def test_glob_joins_functions(analysis):
    entries, _ = resolve(analysis, "pyfix.classes.{exact,make_sub}")
    e = entries["pyfix.classes.{exact,make_sub}"]
    assert e.functions == ["pyfix.classes.exact", "pyfix.classes.make_sub"]
    assert str(e.cost) == "9"


def test_meta():
    import ast  # pylint: disable=import-outside-toplevel

    def m(text):
        return meta(ast.parse(text, mode="eval").body)

    assert m('Annotated[list[Annotated[int, vc.Size("k")]], vc.Size("n")]').shape == (
        "n",
        "k",
    )
    assert m('Final[Annotated[int, Symbol("N")]]').symbol == "N"
    assert m("'Annotated[set[int], Size(3)]'").shape == ("3",)
    assert m("'not valid ('") == m("int") == m("dict[str, int]")
    assert m("list[Annotated[int, Size('k')]]").shape == (None, "k")


def test_meta_ignores_unknown_extras():
    import ast  # pylint: disable=import-outside-toplevel

    for text in (
        "Annotated[int, vc.Size(n)]",
        "Annotated[int, 'doc', Other(3)]",
        "a.b()[int]",
    ):
        assert meta(ast.parse(text, mode="eval").body) == Meta()


def test_source_text():
    src = read("x = (1 +\n     2)\na[0]: Annotated[int, Size(2)] = 1\n")
    assert src.text(SimpleNamespace(line=1, column=4, end_line=2, end_column=7)) == (
        "`(1 + 2)`"
    )
    assert src.text(SimpleNamespace(line=3, column=0, end_line=3, end_column=1)) == (
        "`a`"
    )
    for line, end in ((0, 1), (1, None), (9, 1)):
        node = SimpleNamespace(line=line, column=0, end_line=None, end_column=end)
        assert src.text(node) == "``"
    assert not src.assigns


def test_read_pragmas_and_declarations():
    src = read(
        "def f(x: Annotated[int, Size('n')]) -> Annotated[list, Size(2)]:\n"
        "    y: Annotated[list, Size('k')] = []\n"
        "    # vc: bound(n)\n"
        "    # vc: cost(3)\n"
        "    while x:  # vc: total(k)\n"
        "        pass\n"
        "    # not a pragma\n"
    )
    assert [p.tag for p in src.pragmas[5]] == ["bound", "cost", "total"]
    assert src.pragmas[5][2].column == 15
    assert src.params[(1, "x")].shape == ("n",)
    assert src.returns[1].shape == ("2",)
    assert src.assigns[(2, "y")].shape == ("k",)
    assert not read("def (:\n").pragmas


def test_models():
    by = builtin_models()
    first = next(m for m in by if m.applies("builtins.sorted", 1))
    assert (first.kind, first.arg) == ("nlogn", 0)
    assert next(m for m in by if m.applies("builtins.max", 2)).kind == "const"
    assert next(m for m in by if m.applies("builtins.max", 1)).kind == "linear"
    assert not any(m.applies("json.loads", 1) for m in by)
    models = parse_models('[{"match": "json.*", "cost": "linear", "arg": -1}]')
    assert len(models) == 1
    assert models[0].applies("json.loads", 0) and models[0].arg == -1
    for bad in ('{"a": 1}', '[{"match": "x", "cost": "huge"}]', "[1]"):
        with pytest.raises(ValueError):
            parse_models(bad)
    assert parse_weights('{"call": 4}') == Weights(call=4.0)
    for bad in ("[]", '{"call": -1}', '{"loop": 1}', '{"call": true}'):
        with pytest.raises(ValueError):
            parse_weights(bad)


def test_vc_runtime():
    @vc.cost("n")
    @vc.recursion(2)
    @vc.size("k")
    def f():
        return 3

    assert f() == 3
    assert vc.Size("n").expr == "n" and vc.Symbol("s").name == "s"


def run_cli(args, capsys):
    rc = cli.main(args)
    out = capsys.readouterr()
    return rc, out.out, out.err


def test_cli_report(capsys, tmp_path):
    out = tmp_path / "r.json"
    rc, _, err = run_cli(
        [
            "--entry",
            "pyfix.loops.linear",
            "--breakdown",
            "--root",
            str(FIX),
            "-o",
            str(out),
            "-j",
            "2",
            str(FIX / "pyfix"),
        ],
        capsys,
    )
    assert rc == 0 and "mypy analysed 5 modules" in err
    report = json.loads(out.read_text())
    e = report["entries"]["pyfix.loops.linear"]
    assert e["polynomial"] == "2*n + 4"
    assert e["degree"] == {"n": 1}
    assert e["breakdown"] == [
        {"function": "pyfix.loops.linear", "polynomial": "2*n + 4"}
    ]
    assert report["symbols"] == {"n": None}


def test_cli_models_weights(capsys, tmp_path):
    models = tmp_path / "m.json"
    models.write_text(
        '[{"match": "json.loads", "cost": "const"},'
        ' {"match": "pyfix.calls.deco", "cost": "transparent"},'
        ' {"match": "json.dumps", "cost": "opaque"}]'
    )
    weights = tmp_path / "w.json"
    weights.write_text('{"call": 3}')
    rc, out, _ = run_cli(
        ["--entry", "pyfix.gens.external", "--entry", "pyfix.calls.call_wrapped"]
        + ["--entry", "pyfix.gens.opaque"]
        + ["--models", str(models), "--weights", str(weights), "-j", "1"]
        + [str(FIX / "pyfix")],
        capsys,
    )
    entries = json.loads(out)["entries"]
    assert rc == 0
    assert entries["pyfix.gens.external"]["polynomial"] == "7"
    assert entries["pyfix.calls.call_wrapped"]["polynomial"] == "8"
    assert entries["pyfix.calls.call_wrapped"]["ledger"] == []
    (why,) = entries["pyfix.gens.opaque"]["ledger"]
    assert why["reason"] == "call to json.dumps, modelled opaque"


def test_cli_errors(capsys, tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("def f() -> int:\n    return 'x'\n")
    rc, out, err = run_cli(["--entry", "bad.f", "-j", "1", str(bad)], capsys)
    assert rc == 2 and "has type errors" in err
    assert json.loads(out)["entries"]["bad.f"]["polynomial"] == "2"
    rc, _, err = run_cli(
        ["--entry", "bad.f", "--tolerate-errors-in", "bad", str(bad)], capsys
    )
    assert rc == 0 and "Incompatible return value" in err
    rc, _, err = run_cli(["--entry", "bad.nothing", str(bad)], capsys)
    assert rc == 2 and "matches no analysed function" in err
    syntax = tmp_path / "syntax.py"
    syntax.write_text("def (:\n")
    with pytest.raises(SystemExit) as exc:
        cli.main(["--entry", "x", str(syntax)])
    assert exc.value.code == 2
    for args in (
        ["--models", str(tmp_path / "none.json")],
        ["--tolerate-errors-in", "("],
    ):
        with pytest.raises(SystemExit):
            cli.main(["--entry", "x"] + args + [str(bad)])
