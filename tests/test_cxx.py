import json
import math

import pytest

from virtuous_cycles import get_adapter

DETECT = "ns::Detector::detect"
SCAN = "ns::scan"
OTHER = "other::f"
LEDGER = {"kind": "loop", "function": "ns::g", "file": "a.cc", "line": 1}
REPORT = {
    "version": 1,
    "unbounded_symbol": "?",
    "symbols": {"kMaxBoxes": 4, "nfft": None, "n": 5},
    "entries": {
        DETECT: {
            "terms": [
                {"coefficient": 2, "powers": {"kMaxBoxes": 2, "log2(nfft)": 1}},
                {"coefficient": 7, "powers": {}},
            ],
            "degree": {"kMaxBoxes": 2, "log2(nfft)": 1},
            "ledger": [],
        },
        SCAN: {
            "terms": [
                {"coefficient": 3, "powers": {"?": 1}},
                {"coefficient": 1, "powers": {"n": 2}},
            ],
            "degree": {"?": 1, "n": 2},
            "ledger": [LEDGER, {**LEDGER, "line": 2}],
        },
        OTHER: {
            "terms": [{"coefficient": 5, "powers": {"z": 1}}],
            "degree": {"z": 1},
            "ledger": [LEDGER],
        },
    },
}


@pytest.fixture
def cxx(tmp_path):
    def run(report=None, **options):
        path = tmp_path / "cxx-cost.json"
        path.write_text(json.dumps(REPORT if report is None else report))
        return get_adapter("cxx-cost")({"report": str(path), **options})

    return run


def test_all_keys_with_option_symbols(cxx):
    assert cxx(symbols={"nfft": 1024, "z": 2}) == {
        f"{DETECT}:cost": 2 * 4**2 * 10 + 7,
        f"{DETECT}:unbounded": 0.0,
        f"{DETECT}:degree:kMaxBoxes": 2.0,
        f"{DETECT}:degree:log2(nfft)": 1.0,
        f"{SCAN}:cost": math.inf,
        f"{SCAN}:unbounded": 2.0,
        f"{SCAN}:degree:?": 1.0,
        f"{SCAN}:degree:n": 2.0,
        f"{OTHER}:cost": 10.0,
        f"{OTHER}:unbounded": 1.0,
        f"{OTHER}:degree:z": 1.0,
    }


@pytest.mark.parametrize(
    "options,expected",
    [
        ({"symbols": {"nfft": 1024, "kMaxBoxes": 8}}, 2 * 64 * 10 + 7),
        ({"default": 2}, 2 * 16 * 1 + 7),
        ({"default": 2, "symbols": {"nfft": 0.5}}, 7),
        ({"default": 2, "symbols": {"nfft": 1}}, 7),
        ({"default": 1024, "symbols": {"kMaxBoxes": 1}}, 2 * 10 + 7),
    ],
)
def test_detect_cost_resolution(cxx, options, expected):
    got = cxx(entries=["*Detector*"], values=["cost"], **options)
    assert got == {f"{DETECT}:cost": expected}


def test_report_value_beats_default(cxx):
    got = cxx(entries=[SCAN], values=["cost"], default=1)
    assert math.isinf(got[f"{SCAN}:cost"])
    report = json.loads(json.dumps(REPORT))
    report["entries"][SCAN]["terms"].pop(0)
    assert cxx(report, entries=[SCAN], values=["cost"], default=1) == {
        f"{SCAN}:cost": 25.0
    }


def test_missing_symbol_names_it(cxx):
    with pytest.raises(ValueError, match="'nfft'"):
        cxx(entries=[DETECT], values=["cost"])
    with pytest.raises(ValueError, match="'z'"):
        cxx(symbols={"nfft": 4})


def test_unused_symbols_are_not_resolved(cxx):
    assert cxx(entries=["ns::*"], values=["unbounded"]) == {
        f"{DETECT}:unbounded": 0.0,
        f"{SCAN}:unbounded": 2.0,
    }
    assert cxx(values=["degree"], entries=[OTHER]) == {f"{OTHER}:degree:z": 1.0}


def test_custom_unbounded_symbol(cxx):
    report = json.loads(json.dumps(REPORT))
    report["unbounded_symbol"] = "n"
    got = cxx(report, entries=[SCAN], values=["cost"], symbols={"?": 2})
    assert got == {f"{SCAN}:cost": math.inf}
    report["entries"][SCAN]["terms"].pop()
    got = cxx(report, entries=[SCAN], values=["cost"], symbols={"?": 2})
    assert got == {f"{SCAN}:cost": 6.0}


@pytest.mark.parametrize("version", [0, 2, None])
def test_bad_version(cxx, version):
    with pytest.raises(ValueError, match="version"):
        cxx({**REPORT, "version": version})


def test_bad_values(cxx):
    with pytest.raises(ValueError, match="values"):
        cxx(values=["cost", "bogus"])
