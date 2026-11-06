import pytest

from virtuous_cycles import config

ONE = '[[metric]]\nadapter = "json"\nbudget = "b"\n'


def load_one(tmp_path, text):
    metrics = config.load(write(tmp_path, text))
    assert len(metrics) == 1
    return metrics[0]


def write(tmp_path, text):
    path = tmp_path / "virtuous-cycles.toml"
    path.write_text(text)
    return path


def test_defaults_and_select(tmp_path):
    m = load_one(tmp_path, ONE)
    assert (m.name, m.direction, m.select, m.options) == ("json", "lower", ("*",), {})
    m = config.Metric("n", "json", "b", select=("foo::*", "bar"))
    selected = m.selected({"foo::x": 1, "bar": 2, "baz": 3, "Foo::y": 4})
    assert selected == {"foo::x": 1, "bar": 2}


def test_full_entry(tmp_path):
    m = load_one(
        tmp_path,
        '[[metric]]\nname = "cov"\nadapter = "json"\nbudget = "b.json"\n'
        'direction = "higher"\nselect = "src/*"\n[metric.options]\nfile = "c.json"\n',
    )
    assert (m.name, m.direction, m.select) == ("cov", "higher", ("src/*",))
    assert m.options == {"file": "c.json"}


@pytest.mark.parametrize(
    "text,match",
    [
        ("", "no \\[\\[metric\\]\\]"),
        ('[[metric]]\nadapter = "json"\n', "required"),
        (ONE + "bogus = 1\n", "unknown fields"),
        (ONE + 'direction = "up"\n', "direction"),
        (ONE + ONE.replace('"b"', '"c"'), "duplicate metric name"),
        (
            ONE + ONE.replace("[[metric]]\n", '[[metric]]\nname = "x"\n'),
            "duplicate metric budget",
        ),
    ],
)
def test_invalid(tmp_path, text, match):
    with pytest.raises(ValueError, match=match):
        config.load(write(tmp_path, text))
