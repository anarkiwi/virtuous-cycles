import copy
import json
import runpy
import sys

import pytest

from virtuous_cycles.cost import ir
from virtuous_cycles.cost.program import Cost, Site

LOOP = {
    "kind": "loop",
    "function": "g",
    "reason": "while loop with no bound",
    "at": ["a.cc", 9, 1],
}

PROGRAM = {
    "functions": {
        "c:@F@f": {
            "name": "f",
            "plain": "f",
            "at": ["a.cc", 1, 1],
            "body": 3,
            "ledger": [],
            "recursion": [[1.0, {"n": 1}]],
            "loops": False,
        },
        "c:@F@g": {
            "name": "g",
            "plain": "g",
            "at": ["a.cc", 8, 1],
            "body": 8,
            "ledger": [LOOP],
            "recursion": None,
            "loops": True,
        },
        "c:@F@h": {
            "name": "h",
            "plain": "h",
            "at": ["b.cc", 2, 1],
            "body": 9,
            "ledger": [],
            "recursion": None,
            "loops": False,
        },
    },
    "nodes": [
        {"k": "leaf", "p": [[2.0, {"n": 1}]]},
        {
            "k": "call",
            "usr": "c:@F@g",
            "callee": "g",
            "virtual": False,
            "pure": False,
            "at": ["a.cc", 4, 3],
        },
        {"k": "targets", "names": ["h*"], "at": ["a.cc", 5, 3]},
        {"k": "sum", "kids": [0, 1, 2]},
        {"k": "leaf", "p": [[1.0, {}]]},
        {"k": "leaf", "p": [[3.0, {}]]},
        {"k": "hoist", "run": True, "kids": [5]},
        {"k": "sum", "kids": [4, 6]},
        {"k": "scale", "p": [[1.0, {"m": 1}]], "kids": [7]},
        {"k": "join", "kids": [0, 1]},
    ],
    "overriders": {"c:@F@g": ["c:@F@h"]},
    "symbols": {"m": None, "n": 10.0},
    "conflicts": ["m"],
}

IR = {"version": 1, "entries": ["f", "h"], "breakdown": True, "program": PROGRAM}


def test_load_builds_nodes_as_given_and_shared():
    prog, entries, breakdown = ir.load(copy.deepcopy(IR))
    assert entries == ["f", "h"] and breakdown is True
    f, g, h = (prog.functions[u] for u in ("c:@F@f", "c:@F@g", "c:@F@h"))
    assert [k.k for k in f.body.kids] == [Cost.LEAF, Cost.CALL, Cost.TARGETS]
    assert h.body.k == Cost.JOIN
    assert h.body.kids[0] is f.body.kids[0] and h.body.kids[1] is f.body.kids[1]
    assert f.body.kids[1].at == Site("a.cc", 4, 3)
    assert f.body.kids[2].names == ("h*",)
    assert g.body.k == Cost.SCALE and str(g.body.p) == "m"
    assert g.body.kids[0].kids[1].run
    assert str(f.recursion) == "n" and g.recursion is None and g.loops
    assert g.ledger[0].at == Site("a.cc", 9, 1)
    assert prog.overriders == {"c:@F@g": {"c:@F@h"}}
    assert prog.symbols == {"m": None, "n": 10.0} and prog.conflicts == {"m"}


def test_resolve_loaded():
    prog, entries, breakdown = ir.load(copy.deepcopy(IR))
    f, h = prog.resolve(entries, breakdown)
    assert str(f.cost) == "2*m + 4*n + 6"
    assert str(h.cost) == "m + 2*n + 3"
    assert [(n, str(p)) for n, p in f.breakdown] == [
        ("f", "2*m + 4*n + 6"),
        ("g", "m + 3"),
        ("h", "m + 2*n + 3"),
    ]
    assert [x.reason for x in f.ledger] == ["while loop with no bound"]


def test_dump_round_trip():
    prog, _, _ = ir.load(json.loads(json.dumps(IR)))
    assert ir.dump(prog) == PROGRAM


def test_load_builds_kids_listed_after_parent():
    obj = copy.deepcopy(IR)
    obj["program"]["nodes"] = [
        {"k": "sum", "kids": [2, 1, 2]},
        {"k": "leaf", "p": [[1.0, {}]]},
        {"k": "leaf", "p": [[2.0, {"n": 1}]]},
    ]
    obj["program"]["functions"] = {"u": dict(PROGRAM["functions"]["c:@F@h"], body=0)}
    prog, _, _ = ir.load(obj)
    body = prog.functions["u"].body
    assert body.kids[0] is body.kids[2] and str(body.kids[1].p) == "1"
    assert ir.dump(prog)["nodes"] == [
        {"k": "leaf", "p": [[2.0, {"n": 1}]]},
        {"k": "leaf", "p": [[1.0, {}]]},
        {"k": "sum", "kids": [0, 1, 0]},
    ]


def test_load_rejects_version():
    with pytest.raises(ValueError, match="unsupported IR version 2"):
        ir.load(dict(IR, version=2))


def write(tmp_path, obj):
    path = tmp_path / "ir.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def test_main(tmp_path, capsys):
    assert ir.main([write(tmp_path, IR)]) == 0
    out = capsys.readouterr().out
    assert out.endswith("}\n") and out.startswith('{\n "version": 1,\n')
    rep = json.loads(out)
    assert rep["symbols"] == {"m": None, "n": 10}
    assert rep["entries"]["f"]["polynomial"] == "2*m + 4*n + 6"
    assert rep["entries"]["f"]["ledger"] == [
        {
            "kind": "loop",
            "function": "g",
            "file": "a.cc",
            "line": 9,
            "column": 1,
            "reason": "while loop with no bound",
        }
    ]
    assert rep["entries"]["h"]["breakdown"][0] == {
        "function": "g",
        "polynomial": "m + 3",
    }


def test_main_resolve_error(tmp_path, capsys):
    assert ir.main([write(tmp_path, dict(IR, entries=["zzz"]))]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "vc-cxx-cost: entry zzz matches no analysed function\n"


def test_module_entry_point(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["ir", write(tmp_path, IR)])
    monkeypatch.delitem(sys.modules, "virtuous_cycles.cost.ir")
    with pytest.raises(SystemExit) as exit_:
        runpy.run_module("virtuous_cycles.cost.ir", run_name="__main__")
    assert exit_.value.code == 0
    assert json.loads(capsys.readouterr().out)["version"] == 1
