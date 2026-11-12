import pickle

import pytest

from virtuous_cycles.cost.poly import Poly
from virtuous_cycles.cost.program import (
    Cost,
    Function,
    LedgerEntry,
    Program,
    Site,
    dumps,
    glob,
    report,
    to_json,
)

parse = Poly.parse
S1, S2, S3 = Site("a.cc", 1, 1), Site("a.cc", 2, 3), Site("b.cc", 1, 1)


def leaf(text):
    return Cost.leaf(parse(text))


def call(usr, **kw):
    return Cost.call(usr, usr, S2, **kw)


def program(**bodies):
    prog = Program()
    for i, (usr, body) in enumerate(sorted(bodies.items())):
        prog.functions[usr] = Function(usr, usr, Site("f.cc", i + 1, 1), body)
    return prog


def cost_of(prog, pattern, **kw):
    (entry,) = prog.resolve([pattern], **kw)
    return str(entry.cost)


def test_combine_folds_leaves():
    assert str(Cost.sum(leaf("n"), leaf("2")).p) == "n + 2"
    assert str(Cost.join(leaf("n + 3"), leaf("2*n")).p) == "2*n + 3"
    assert Cost.sum(leaf("n"), leaf("m")).k == Cost.LEAF


def test_combine_elides_zero_and_flattens():
    c, d, e = call("c"), call("d"), call("e")
    assert Cost.sum(leaf("0"), c) is c
    assert Cost.sum(c, leaf("0")) is c
    assert Cost.join(c, leaf("0")) is c
    j = Cost.join(leaf("0"), c)
    assert j.k == Cost.JOIN and j.kids[1] is c and j.kids[0].zero
    s = Cost.sum(Cost.sum(c, d), Cost.sum(e, c))
    assert s.k == Cost.SUM and s.kids == (c, d, e, c)
    assert Cost.sum(Cost.join(c, d), e).kids[0].k == Cost.JOIN
    prog = program(c=s, d=leaf("1"), e=leaf("2"))
    assert prog.edges(s) == {"c", "d", "e"}


def test_scale_and_hoist():
    c = call("c")
    assert str(Cost.scale(parse("n"), leaf("2")).p) == "2*n"
    assert Cost.scale(Poly(), c).zero
    assert Cost.scale(parse("1"), c) is c
    s = Cost.scale(parse("n"), c)
    assert s.k == Cost.SCALE and s.kids == (c,) and str(s.p) == "n"
    z = leaf("0")
    assert Cost.hoist(z) is z
    h = Cost.hoist(c, run=True)
    assert h.k == Cost.HOIST and h.run and h.kids == (c,)
    t = Cost.targets(["a*", "b"], S1)
    assert t.k == Cost.TARGETS and t.names == ("a*", "b") and t.at == S1
    v = Cost.call("u", "f", S1, virtual=True, pure=True)
    assert (v.usr, v.callee, v.virtual, v.pure) == ("u", "f", True, True)


def test_cost_pickles():
    c = Cost.sum(Cost.scale(parse("n"), call("g")), Cost.hoist(call("h"), run=True))
    back = pickle.loads(pickle.dumps(c))
    assert [k.k for k in back.kids] == [Cost.SCALE, Cost.HOIST]
    assert back.kids[0].kids[0].usr == "g" and back.kids[1].run


def test_symbol_conflicts():
    prog = Program()
    prog.symbol("k", 4.0)
    prog.symbol("k", 4.0)
    prog.symbol("k", None)
    assert prog.symbols == {"k": 4.0} and not prog.conflicts
    prog.symbol("k", 5.0)
    assert prog.symbols == {"k": None} and prog.conflicts == {"k"}
    prog.symbol("k", 6.0)
    assert prog.symbols == {"k": None}
    prog.symbol("u", None)
    prog.symbol("u", 3.0)
    assert prog.symbols["u"] == 3.0 and "u" not in prog.conflicts


def test_merge():
    a, b = program(f=leaf("1")), program(f=leaf("2"), g=leaf("3"))
    a.overriders = {"B": {"D1"}}
    b.overriders = {"B": {"D2"}, "C": set()}
    a.symbol("k", 1.0)
    b.symbol("k", 2.0)
    b.symbol("n", 8.0)
    b.conflicts = {"z"}
    a.merge(b)
    assert str(a.functions["f"].body.p) == "1"
    assert str(a.functions["g"].body.p) == "3"
    assert a.overriders == {"B": {"D1", "D2"}, "C": set()}
    assert a.conflicts == {"k", "z"}
    assert a.symbols == {"k": None, "n": 8.0, "z": None}


def test_loop_nest_scales_body_and_hoist_escapes():
    inner = Cost.sum(call("g"), Cost.hoist(leaf("5")))
    prog = program(f=Cost.scale(parse("n"), Cost.scale(parse("m"), inner)), g=leaf("3"))
    assert cost_of(prog, "f") == "3*m*n + 5"


def test_run_total_escapes_loops_across_calls():
    g = Cost.sum(leaf("1"), Cost.hoist(leaf("7"), run=True))
    prog = program(f=Cost.scale(parse("n"), Cost.scale(parse("m"), call("g"))), g=g)
    assert cost_of(prog, "f") == "m*n + 7"
    assert cost_of(prog, "g") == "8"


def test_function_hoist_stops_at_call():
    g = Cost.sum(leaf("1"), Cost.hoist(leaf("7")))
    prog = program(f=Cost.scale(parse("n"), Cost.scale(parse("m"), call("g"))), g=g)
    assert cost_of(prog, "f") == "8*m*n"


def test_join_keeps_hoisted_parts_under_loops():
    body = Cost.join(Cost.hoist(leaf("4")), call("g"))
    g = Cost.sum(leaf("1"), Cost.hoist(leaf("2"), run=True))
    prog = program(f=Cost.scale(parse("n"), body), g=g)
    assert cost_of(prog, "f") == "4*n"


def test_several_candidates_join_run_totals():
    base = Cost.sum(leaf("1"), Cost.hoist(leaf("7"), run=True))
    body = Cost.scale(parse("n"), call("B", virtual=True))
    prog = program(B=base, D=leaf("2"), f=body)
    prog.overriders = {"B": {"D"}}
    assert cost_of(prog, "f") == "8*n"


def test_virtual_candidates():
    prog = program(B=leaf("9"), D1=leaf("5"), D2=leaf("3"))
    prog.overriders = {"B": {"D1"}, "D1": {"D2", "B"}}
    assert prog.candidates(call("B", virtual=True)) == ["B", "D1", "D2"]
    assert prog.candidates(call("B", virtual=True, pure=True)) == ["D1", "D2"]
    assert prog.candidates(call("B")) == ["B"]
    prog.functions["v"] = Function("v", "v", S1, call("B", virtual=True))
    prog.functions["p"] = Function("p", "p", S1, call("B", virtual=True, pure=True))
    assert cost_of(prog, "v") == "9"
    assert cost_of(prog, "p") == "5"


def test_virtual_without_overrider_and_external():
    prog = program(f=call("B", virtual=True, pure=True), g=call("ext"))
    f, g = prog.resolve(["f", "g"])
    assert str(f.cost) == "?" and str(g.cost) == "?"
    assert f.ledger == [
        LedgerEntry("virtual", "f", "virtual call to B has no overrider", S2)
    ]
    assert g.ledger == [
        LedgerEntry("external", "g", "call to ext whose body is not analysed", S2)
    ]
    prog.overriders = {"C": {"missing"}}
    prog.functions["h"] = Function("h", "h", S1, call("C", virtual=True, pure=True))
    (h,) = prog.resolve(["h"])
    assert h.ledger[0].reason == "call to C whose body is not analysed"


def test_targets_glob_with_braces():
    prog = Program()
    for usr, name, c in [("u1", "ns::alpha", "2"), ("u2", "ns::beta", "7")]:
        prog.functions[usr] = Function(name, name, S1, leaf(c))
    prog.functions["u3"] = Function("ns::gamma<int>", "ns::gamma", S1, leaf("4"))
    t = Cost.targets(["ns::{alpha,beta}", "{bad}"], S3)
    assert prog.candidates(t) == ["u1", "u2"]
    assert prog.candidates(Cost.targets(["ns::gamma"], S3)) == ["u3"]
    prog.functions["e"] = Function("e", "e", S1, Cost.sum(leaf("1"), t))
    assert cost_of(prog, "e") == "8"
    prog.functions["n"] = Function("n", "n", S1, Cost.targets(["no*", "x"], S3))
    (n,) = prog.resolve(["n"])
    assert str(n.cost) == "?"
    assert n.ledger == [
        LedgerEntry(
            "annotation", "n", "VC_TARGETS names no analysed function: no*, x", S3
        )
    ]


def test_recursion_without_bound():
    prog = program(
        f=Cost.sum(leaf("1"), Cost.sum(call("g"), call("k"))),
        g=Cost.sum(leaf("2"), call("f")),
        k=leaf("4"),
    )
    (e,) = prog.resolve(["f"])
    assert str(e.cost) == "7*?"
    assert e.ledger == [
        LedgerEntry(
            "recursion", "f", "recursive call with no bound", Site("f.cc", 1, 1)
        ),
        LedgerEntry(
            "recursion", "g", "recursive call with no bound", Site("f.cc", 2, 1)
        ),
    ]
    assert prog.functions["f"].ledger == [e.ledger[0]]
    assert not prog.functions["k"].ledger


def test_recursion_with_bound():
    prog = program(f=Cost.sum(leaf("1"), call("g")), g=Cost.sum(leaf("2"), call("f")))
    prog.functions["f"].recursion = parse("n")
    prog.functions["g"].recursion = parse("m")
    (e,) = prog.resolve(["g"])
    assert str(e.cost) == "3*m + 3*n" and e.ledger == []


def test_self_recursion_and_single_bound():
    prog = program(h=Cost.sum(leaf("1"), call("h")), r=Cost.sum(leaf("2"), call("r")))
    prog.functions["r"].recursion = parse("d")
    h, r = prog.resolve(["h", "r"])
    assert str(h.cost) == "?" and [x.kind for x in h.ledger] == ["recursion"]
    assert str(r.cost) == "2*d" and r.ledger == []


def test_deep_call_chain_is_iterative():
    depth = 3000
    bodies = {
        f"f{i:05d}": Cost.sum(leaf("1"), call(f"f{i + 1:05d}")) for i in range(depth)
    }
    bodies[f"f{depth:05d}"] = leaf("1")
    assert cost_of(program(**bodies), "f00000") == str(depth + 1)
    bodies[f"f{depth:05d}"] = Cost.sum(leaf("1"), call("f00000"))
    assert cost_of(program(**bodies), "f00000") == f"{depth + 1}*?"


def test_name_symbols_and_breakdown():
    k = Cost.leaf(Poly.capacity(16) * parse("n"))
    prog = program(f=Cost.sum(k, call("g")), g=Cost.leaf(Poly.capacity(16).log2()))
    prog.symbol("K", 16.0)
    (e,) = prog.resolve(["f"], breakdown=True)
    assert str(e.cost) == "K*n + log2(K)"
    assert [(n, str(p)) for n, p in e.breakdown] == [
        ("f", "K*n + log2(K)"),
        ("g", "log2(K)"),
    ]
    (e,) = prog.resolve(["f"])
    assert e.breakdown == []
    prog.symbol("J", 16.0)
    assert cost_of(prog, "f") == "16*n + 4"


def test_entry_functions_join_ledger_dedup_and_order():
    prog = Program()
    prog.functions["b"] = Function("ns::b", "ns::b", S1, leaf("n"))
    prog.functions["a"] = Function("ns::a<int>", "ns::a", S1, leaf("m"))
    prog.functions["a"].ledger = [
        LedgerEntry("loop", "ns::a", "r", S3),
        LedgerEntry("loop", "ns::a", "same", S1),
    ]
    prog.functions["b"].ledger = [LedgerEntry("loop", "ns::b", "same", S1)]
    (e,) = prog.resolve(["ns::*"])
    assert e.functions == ["ns::a<int>", "ns::b"] and str(e.cost) == "m + n"
    assert e.ledger == [
        LedgerEntry("loop", "ns::b", "same", S1),
        LedgerEntry("loop", "ns::a", "r", S3),
    ]
    assert prog.resolve(["ns::a"])[0].functions == ["ns::a<int>"]


def test_resolve_errors():
    prog = program(f=leaf("1"))
    with pytest.raises(ValueError, match=r"^entry nope matches no analysed function$"):
        prog.resolve(["f", "nope"])
    with pytest.raises(ValueError) as err:
        prog.resolve(["{f}"])
    assert str(err.value) == (
        "bad entry pattern {f}: empty or singleton brace expansions are not supported"
    )


@pytest.mark.parametrize(
    "pattern,name,expected",
    [
        ("x", "x", True),
        ("x", "xy", False),
        ("ns::*", "ns::f", True),
        ("ns::*", "nt::f", False),
        ("*::f", "a::b::f", True),
        ("a*b*c", "abxbc", True),
        ("a*b*c", "abxbcx", False),
        ("a?c", "abc", True),
        ("a?c", "ac", False),
        ("[a-c]x", "bx", True),
        ("[a-c]x", "dx", False),
        ("[!a-c]x", "bx", False),
        ("[^a-c]x", "dx", True),
        ("[]a]", "]", True),
        ("[]a]", "a", True),
        ("[a-]", "-", True),
        ("[!]", "q", True),
        ("a\\*", "a*", True),
        ("a\\*", "ab", False),
        ("{a,b}x", "bx", True),
        ("{a,b}{c,d}", "ad", True),
        ("{a,b}{c,d}", "ab", False),
        ("{a\\,b,c}", "a,b", True),
        ("{[,]x,y}", ",x", True),
        ("{[,]x,y}", "y", True),
        ("a}", "a}", True),
        ("x,{a,b}", "x,b", True),
        ("?", "é", False),
        ("??", "é", True),
        ("*", "", True),
        ("a*", "a", True),
        ("[xa-c]", "b", True),
        ("[xa-c]", "x", True),
        ("[xa-c]", "-", False),
        ("a[b]*", "a", False),
        ("[!\x00-\udcff]", "a", False),
    ],
)
def test_glob(pattern, name, expected):
    assert glob(pattern)(name) is expected


@pytest.mark.parametrize(
    "pattern,message",
    [
        ("{a}", "empty or singleton brace expansions are not supported"),
        ("{a,{b,c}}", "nested brace expansions are not supported"),
        ("{a,b", "incomplete brace expansion"),
        ("{a,b}[x", "invalid glob pattern, unmatched '['"),
        ("{a,b}\\", "invalid glob pattern, stray '\\'"),
        ("[abc", "invalid glob pattern, unmatched '['"),
        ("a\\", "invalid glob pattern, stray '\\'"),
        ("x[b-a]", "invalid glob pattern: [b-a]"),
        ("p{a,b}[b-a]", "invalid glob pattern: a[b-a]"),
        ("{a,b}" * 13, "too many brace expansions"),
    ],
)
def test_glob_errors(pattern, message):
    with pytest.raises(ValueError) as err:
        glob(pattern)
    assert str(err.value) == message


def test_glob_is_cached():
    assert glob("c*") is glob("c*")


def report_program():
    body = Cost.sum(leaf("2*K^2 + 7"), Cost.call("ext", "ext", Site("a.cc", 3, 5)))
    prog = program(**{"ns::f": body})
    prog.symbol("K", 256.0)
    return prog


def test_report():
    prog = report_program()
    assert report(prog, prog.resolve(["ns::f"])) == {
        "version": 1,
        "unbounded_symbol": "?",
        "symbols": {"K": 256.0},
        "entries": {
            "ns::f": {
                "functions": ["ns::f"],
                "polynomial": "2*K^2 + ? + 7",
                "terms": [
                    {"coefficient": 7.0, "powers": {}},
                    {"coefficient": 1.0, "powers": {"?": 1}},
                    {"coefficient": 2.0, "powers": {"K": 2}},
                ],
                "degree": {"?": 1, "K": 2},
                "ledger": [
                    {
                        "kind": "external",
                        "function": "ns::f",
                        "file": "a.cc",
                        "line": 3,
                        "column": 5,
                        "reason": "call to ext whose body is not analysed",
                    }
                ],
            }
        },
    }


def test_report_symbols_and_breakdown():
    prog = program(f=Cost.sum(leaf("log2(n) + m"), call("g")), g=leaf("1"))
    prog.symbol("n", 8.0)
    rep = report(prog, prog.resolve(["f"], breakdown=True))
    assert rep["symbols"] == {"m": None, "n": 8.0}
    assert rep["entries"]["f"]["breakdown"] == [
        {"function": "f", "polynomial": "log2(n) + m + 1"},
        {"function": "g", "polynomial": "1"},
    ]
    assert list(rep["entries"]["f"]) == [
        "functions",
        "polynomial",
        "terms",
        "degree",
        "breakdown",
        "ledger",
    ]


EXPECTED_DUMPS = """{
 "version": 1,
 "unbounded_symbol": "?",
 "symbols": {
  "K": 256
 },
 "entries": {
  "ns::f": {
   "functions": [
    "ns::f"
   ],
   "polynomial": "2*K^2 + ? + 7",
   "terms": [
    {
     "coefficient": 7,
     "powers": {}
    },
    {
     "coefficient": 1,
     "powers": {
      "?": 1
     }
    },
    {
     "coefficient": 2,
     "powers": {
      "K": 2
     }
    }
   ],
   "degree": {
    "?": 1,
    "K": 2
   },
   "ledger": [
    {
     "kind": "external",
     "function": "ns::f",
     "file": "a.cc",
     "line": 3,
     "column": 5,
     "reason": "call to ext whose body is not analysed"
    }
   ]
  }
 }
}
"""


def test_dumps():
    prog = report_program()
    assert dumps(prog, prog.resolve(["ns::f"])) == EXPECTED_DUMPS


def test_to_json_scalars_and_escapes():
    value = {"a\tb": ['\x08"\\é\x7f\n\r', 0.1, 1e20, None, True, False, [], {}]}
    assert to_json(value) == (
        '{\n "a\\tb": [\n  "\\u0008\\"\\\\é\x7f\\n\\r",\n  0.10000000000000001,'
        "\n  1e+20,\n  null,\n  true,\n  false,\n  [],\n  {}\n ]\n}\n"
    )
