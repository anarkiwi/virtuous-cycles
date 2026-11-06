import json
import math
from pathlib import Path

import pytest

from virtuous_cycles import get_adapter
from virtuous_cycles.cli import main
from virtuous_cycles.infer import Polynomial

REPORT = Path(__file__).parent / "infer" / "costs-report.json"
INF = math.inf


def infer(**options):
    return get_adapter("infer-cost")({"report": str(REPORT), **options})


def test_degree_from_real_report():
    assert infer() == {
        "constant": 0.0,
        "linear": 1.0,
        "quadratic": 2.0,
        "unknown": INF,
        "dsp::halving": 1.0,
        "dsp::product": 2.0,
        "dsp::Window::sum": 1.0,
        "use": 1.0,
        "compare": 1.0,
        "Pair<int,long>::operator()": 1.0,
        "Pair<int,long>::operator<": 0.0,
        "lambda_example.cpp:88_264f29e8::operator()": 0.0,
        "infer-cost:unknown": 1.0,
    }


def test_polynomial_from_real_report():
    got = infer(value="polynomial", symbols={"n": 4096, "m": 10}, default=100)
    assert got["constant"] == 2
    assert got["linear"] == 5 + 8 * 4096 + 2 * 4097
    assert got["quadratic"] == 5 + 5 * 4096 + 11 * 4096**2 + 2 * 4096 * 4097 + 2 * 4097
    assert got["dsp::product"] == 5 + 5 * 10 + 5 * 10 * 4096 + 2 * 10 * 4097 + 2 * 11
    assert got["dsp::Window::sum"] == 10 + 8 * 4096 + 2 * 4097
    assert got["unknown"] == INF
    with pytest.raises(ValueError, match="no value for symbol 'this->len'"):
        infer(value="polynomial", symbols={"n": 1, "m": 1})


def test_options():
    got = infer(key="{file}:{procedure_name}", unknown_key="top")
    assert got["example.cpp:sum"] == 1.0
    assert got["example.cpp:dsp::halving"] == 1.0
    assert got["top"] == 1.0
    with pytest.raises(ValueError, match="degree or polynomial"):
        infer(value="cubic")


@pytest.mark.parametrize(
    "text,value",
    [
        ("⊤", INF),
        (" ⊥ ", 0.0),
        ("7", 7.0),
        ("2 ⋅ n × m", 2 * 3 * 5),
        ("n² + n^2", 18.0),
        ("3 ⋅ (n - 1)", 6.0),
        ("-n + 10", 7.0),
        ("this->len + (*p).size + a.length(v) + |f|", 4.0 + 6.0 + 8.0 + 9.0),
        ("log(n + 5) × max(2⋅n, m) + min(n, 1)", 3.0 * 6.0 + 1.0),
        ("log(1)", 0.0),
        ("x[*] ⋅ 2", 22.0),
        ("7 + 9 . n + 4 . n x m + 2 . n x (1+max(0, m))", 7 + 27 + 60 + 36.0),
        ("3 . (-max(-36, n)) + 2.n + a->b[*].c.length", -9 + 6 + 11.0),
        ("x x x", 121.0),
        ("(n+1) ⋅ 2", 8.0),
    ],
)
def test_polynomial_grammar(text, value):
    symbols = {
        "n": 3,
        "m": 5,
        "this->len": 4,
        "(*p).size": 6,
        "a.length(v)": 8,
        "|f|": 9,
    }
    assert Polynomial(text, symbols, default=11).evaluate() == value


@pytest.mark.parametrize(
    "text,match",
    [
        ("n + ", "expected an operand"),
        ("n + )", "expected an operand"),
        ("(n + 1", "unbalanced"),
        ("n )", "trailing input"),
        ("min(n, 1", "expected '\\)'"),
        ("q", "no value for symbol 'q'"),
    ],
)
def test_polynomial_errors(text, match):
    with pytest.raises(ValueError, match=match):
        Polynomial(text, {"n": 1}).evaluate()


def test_cli_on_real_report(tmp_path, capsys):
    text = f"""
[[metric]]
name = "complexity"
adapter = "infer-cost"
budget = "complexity.json"
select = ["dsp::*", "infer-cost:unknown"]
[metric.options]
report = "{REPORT}"
"""
    (tmp_path / "virtuous-cycles.toml").write_text(text)
    cfg = str(tmp_path / "virtuous-cycles.toml")
    assert main(["-q", "-c", cfg, "tighten"]) == 0
    assert main(["-q", "-c", cfg, "check"]) == 0
    capsys.readouterr()
    assert main(["-q", "-c", cfg, "report"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert [line.split()[1] for line in out[1:]] == [
        "dsp::Window::sum",
        "dsp::halving",
        "dsp::product",
        "infer-cost:unknown",
    ]


def test_unreachable_is_zero(tmp_path):
    report = tmp_path / "costs-report.json"
    hum = {"hum_polynomial": "⊥", "hum_degree": "Unreachable", "big_o": "Unreachable"}
    report.write_text(
        json.dumps(
            [{"procedure_id": "dead", "exec_cost": {"polynomial": "", "hum": hum}}]
        )
    )
    for value in ("degree", "polynomial"):
        got = get_adapter("infer-cost")({"report": str(report), "value": value})
        assert got == {"dead": 0.0, "infer-cost:unknown": 0.0}


PROCS = Path(__file__).parent / "infer" / "procs.txt"


@pytest.mark.parametrize(
    "roots,keys",
    [
        (["use"], {"use", "dsp::Window::sum", "linear"}),
        (
            ["compare"],
            {
                "compare",
                "Pair<int,long>::operator()",
                "Pair<int,long>::operator<",
                "lambda_example.cpp:88_264f29e8::operator()",
            },
        ),
        (
            ["unknown", "dsp::*"],
            {"unknown", "dsp::halving", "dsp::product", "dsp::Window::sum", "linear"},
        ),
    ],
)
def test_reachability_filter(roots, keys):
    got = infer(callgraph=str(PROCS), roots=roots)
    assert got.pop("infer-cost:unknown") == ("unknown" in keys)
    assert set(got) == keys


PROBES = sorted((Path(__file__).parent / "infer" / "probe").glob("costs-report-*.json"))


@pytest.mark.parametrize("report", PROBES, ids=lambda p: p.stem)
def test_probe_reports_parse_in_both_modes(report):
    options = {"report": str(report)}
    degree = get_adapter("infer-cost")(options)
    poly = get_adapter("infer-cost")({**options, "value": "polynomial", "default": 64})
    assert degree.keys() == poly.keys()
    for key, value in degree.items():
        assert math.isinf(value) == math.isinf(poly[key]), key


def test_probe_c_locale_polynomials():
    report = str(Path(__file__).parent / "infer" / "probe" / "costs-report-2.json")
    got = get_adapter("infer-cost")(
        {"report": report, "value": "polynomial", "symbols": {"hi": 10, "lo": 4}}
    )
    assert got["outer_const_inner_stride"] == 10250 + 12288 * 6
    assert got["infer-cost:unknown"] == sum(map(math.isinf, got.values()))
