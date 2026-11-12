import math
import pickle

import pytest

from virtuous_cycles.cost.poly import UNBOUNDED, Poly, number, stod

parse = Poly.parse


@pytest.mark.parametrize(
    "text,expected",
    [
        ("2*n^2 + log2(4*n)", "2*n^2 + log2(n) + 2"),
        ("a::b::name", "name"),
        ("x.n * p->m", "p->m*x.n"),
        ("a.b::c", "c"),
        ("3u + 2UL + 7lu", "12"),
        ("0x10", "16"),
        ("0x1p3*n", "8*n"),
        ("1e3", "1000"),
        ("1.", "1"),
        ("1.5*n", "1.5*n"),
        ("(n + 1)^2", "n^2 + 2*n + 1"),
        ("n^0", "1"),
        ("n ^ 3", "n^3"),
        ("log2(?)", "?"),
        ("log2 (n*m^2)", "2*log2(m) + log2(n)"),
        ("log2(5)", "3"),
        ("n + n^2*m + 3", "m*n^2 + n + 3"),
        ("b + a", "a + b"),
        ("\t?\n*\vk\f+\r1 ", "?*k + 1"),
        ("0", "0"),
        ("log2", "log2"),
    ],
)
def test_parse(text, expected):
    assert str(parse(text)) == expected


@pytest.mark.parametrize(
    "text",
    ["", " ", "n^", "2 3", "(n", "(n +", "log2(n", "+", "n+", "n*", ".5", "n $"],
)
def test_parse_rejects(text):
    assert parse(text) is None


@pytest.mark.parametrize("text", ["a::", "a.1", "p->", "a::1"])
def test_parse_separator_needs_identifier(text):
    assert parse(text) is None


def test_parse_skips_nul_as_suffix():
    assert str(parse("4\0")) == "4"


def test_terms_in_map_order():
    assert list(parse("b*a + b + a^2 + 2").terms) == [
        (),
        (("a", 1), ("b", 1)),
        (("a", 2),),
        (("b", 1),),
    ]


@pytest.mark.parametrize(
    "value,text",
    [
        (1.0, "1"),
        (0.5, "0.5"),
        (123456789012345.0, "123456789012345"),
        (1e15, "1e+15"),
        (math.inf, "inf"),
        (2.0 / 3.0, "0.666667"),
    ],
)
def test_number(value, text):
    assert number(value) == text


def test_str_coefficients_and_powers():
    assert str(Poly()) == "0"
    assert str(Poly.constant(1)) == "1"
    assert str(Poly.constant(3) * Poly.symbol("n") * Poly.symbol("n")) == "3*n^2"
    assert str(Poly.constant(0.5) * Poly.symbol("n")) == "0.5*n"


def test_nonpositive_coefficients_dropped():
    assert Poly.constant(0).zero
    assert Poly.constant(-1).zero
    assert Poly({(("n", 1),): -2.0}).zero
    assert not Poly.constant(1).zero


def test_log2():
    assert str(Poly.constant(5).log2()) == "3"
    assert str(Poly.constant(4).log2()) == "2"
    assert Poly.constant(1).log2().zero
    assert Poly.constant(0.5).log2().zero
    assert Poly().log2().zero
    assert str(parse("3*n^2 + 5*m").log2()) == "log2(m) + 2*log2(n) + 3"
    assert str(parse("n*? + 1").log2()) == "? + log2(n) + 1"
    assert str(Poly.symbol("n").log2().log2()) == "log2(log2(n))"


def test_add_mul_join():
    assert str(parse("n + 1") + parse("n + m")) == "m + 2*n + 1"
    assert str(parse("n + 1") * parse("n + 2")) == "n^2 + 3*n + 2"
    assert str(parse("2*n + 3").join(parse("n^2 + 5"))) == "n^2 + 2*n + 5"
    assert (parse("n") * Poly()).zero
    assert (Poly.constant(1e-200) * Poly.constant(1e-200)).zero


def test_tighter():
    a, b = parse("n^2"), parse("100*n")
    assert Poly.tighter(a, b) is b
    a, b = parse("2*n"), parse("3*n")
    assert Poly.tighter(a, b) is a
    a, b = parse("n"), parse("m")
    assert Poly.tighter(a, b) is a


def test_queries():
    p = parse("2*n^2*m + 3*m + 4")
    assert p.constant_value() is None
    assert parse("7").constant_value() == 7.0
    assert Poly().constant_value() == 0.0
    assert parse("n").constant_value() is None
    assert p.degree("n") == 2 and p.degree("m") == 1 and p.degree("k") == 0
    assert p.total_degree() == 3 and Poly().total_degree() == 0
    assert p.coefficient_sum() == 9.0


def test_capacity_and_name():
    k16 = Poly.capacity(16)
    assert str(k16) == "#16"
    assert str(k16.name({"K": 16.0, "N": None})) == "K"
    assert str(k16.name({"A": 16.0, "B": 16.0})) == "16"
    assert str(k16.name({"A": 8.0})) == "16"
    assert str(k16.log2()) == "log2(#16)"
    assert str(k16.log2().name({"K": 16.0})) == "log2(K)"
    assert str(k16.log2().name({"A": 16.0, "B": 16.0})) == "4"
    assert str((Poly.constant(3) * Poly.capacity(8) * Poly.capacity(8)).name({})) == (
        "192"
    )
    assert str((Poly.capacity(2.5) * parse("n")).name({})) == "2.5*n"
    assert str((k16 * parse("n + 1")).name({"K": 16.0})) == "K*n + K"


def test_name_log2_without_close_is_value():
    assert str(Poly.symbol("log2(#5").name({})) == "5"
    assert str(Poly.symbol("log2(#5").name({"K": 5.0})) == "K"


def test_eq_hash_repr_pickle():
    assert parse("n + 1") == parse("1 + n")
    assert hash(parse("n + 1")) == hash(parse("1 + n"))
    assert parse("n") != parse("m")
    assert parse("n") != "n"
    assert repr(parse("2*n")) == "Poly('2*n')"
    p = parse("2*n^2 + ?")
    assert pickle.loads(pickle.dumps(p)) == p
    assert UNBOUNDED == "?"


@pytest.mark.parametrize(
    "text,pos,value,end",
    [
        ("16", 0, 16.0, 2),
        (" -1.5e2x", 0, -150.0, 7),
        ("#2.5", 1, 2.5, 4),
        ("0x1p3", 0, 8.0, 5),
        ("0x", 0, 0.0, 1),
        ("1e", 0, 1.0, 1),
        ("inf", 0, math.inf, 3),
        ("-Infinity", 0, -math.inf, 9),
    ],
)
def test_stod(text, pos, value, end):
    assert stod(text, pos) == (value, end)


def test_stod_nan_and_errors():
    value, end = stod("nan(abc)z")
    assert math.isnan(value) and end == 8
    for bad in ["x", "", "1e999", "0x1p99999"]:
        with pytest.raises(ValueError):
            stod(bad)
