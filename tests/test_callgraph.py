import pytest

from virtuous_cycles import callgraph

VEC = "std::vector<float,std::allocator<float>>"
ITER = f"__gnu_cxx::__normal_iterator<float const *,{VEC}>"


@pytest.mark.parametrize(
    "header,name",
    [
        ("linear{2600885711533757196}\n", "linear"),
        ("class dsp::Window::sum(16974432264562397713)", "dsp::Window::sum"),
        (f"class {ITER}::base(7897297162595831931)", f"{ITER}::base"),
        (
            f"class {ITER}::operator+(class {ITER})(13754778265045036926)",
            f"{ITER}::operator+",
        ),
        (
            "class Pair<int,long>::operator()(18244103633668317586)",
            "Pair<int,long>::operator()",
        ),
        (
            "class Pair<int,long>::operator<(9357256370785042172)",
            "Pair<int,long>::operator<",
        ),
        (
            "__gnu_cxx::operator!=<16184723067e2c1a>{6623249692370458948}",
            "__gnu_cxx::operator!=<16184723067e2c1a>",
        ),
        ("std::operator<<<b7ca98c5140c72c>{1}", "std::operator<<<b7ca98c5140c72c>"),
        ("std::operator<<b7ca98c5140c72c>{1}", "std::operator<<b7ca98c5140c72c>"),
        ("class it::operator->(2)", "it::operator->"),
        (
            "class l::lambda_~(lambda_at_x.cpp:88_a7dd8f96(4132842077111324982)",
            "l::lambda_~",
        ),
        ("class l::operator_int_(*)(int)(13375893191956439559)", "l::operator_int_"),
    ],
)
def test_plain(header, name):
    assert callgraph.plain(header) == name


def test_split_callees_keeps_template_and_operator_commas():
    text = (
        f" {ITER}::operator->, std::map<int,{VEC}>::find, x::operator,,"
        " lambda_f.cc:1_ab::operator(), "
    )
    assert callgraph.split_callees(text) == [
        f"{ITER}::operator->",
        f"std::map<int,{VEC}>::find",
        "x::operator,",
        "lambda_f.cc:1_ab::operator()",
    ]


GRAPH = """\
a{1}
  source_file: f.cc
  proc_name: a{1}
  defined: true
  callees: b, c<int,long>::operator()

class b(2)
  callees: d

class c<int,long>::operator()(3)
  callees: \n
d{4}
  callees: b
e{5}
  callees: a
"""


def test_parse_and_reach():
    graph = callgraph.parse(GRAPH.splitlines(keepends=True))
    assert graph["a"] == {"b", "c<int,long>::operator()"}
    assert graph["c<int,long>::operator()"] == set()
    assert callgraph.reached(graph, ["a"]) == {"a", "b", "d", "c<int,long>::operator()"}
    assert callgraph.reached(graph, ["d", "e"]) == set(graph)
    assert callgraph.reached(graph, ["c*"]) == {"c<int,long>::operator()"}
    with pytest.raises(ValueError, match="no procedure matching root 'z'"):
        callgraph.reached(graph, ["z"])
