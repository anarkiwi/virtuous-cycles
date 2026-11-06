import math

import pytest

from virtuous_cycles import budget

INF = math.inf


@pytest.mark.parametrize(
    "value,limit,direction,expected",
    [
        (2, 1, "lower", True),
        (1, 1, "lower", False),
        (0, 1, "lower", False),
        (0, 1, "higher", True),
        (2, 1, "higher", False),
        (INF, INF, "lower", False),
        (INF, 3, "lower", True),
    ],
)
def test_worse(value, limit, direction, expected):
    assert budget.worse(value, limit, direction) is expected


def test_tighten_keeps_stricter_adds_new_drops_gone():
    old = {"a": 3.0, "b": 1.0, "gone": 5.0, "top": INF}
    now = {"a": 2.0, "b": 4.0, "new": 7.0, "top": 9.0}
    assert budget.tighten(old, now, "lower") == {
        "a": 2.0,
        "b": 1.0,
        "new": 7.0,
        "top": 9.0,
    }
    assert budget.tighten(old, now, "higher")["a"] == 3.0


def test_loosened_ignores_added_and_removed_keys():
    old = {"a": 1.0, "b": 2.0, "c": 3.0}
    new = {"a": 2.0, "b": 1.0, "d": 9.0}
    assert budget.loosened(old, new, "lower") == {"a": (1.0, 2.0)}
    assert budget.loosened(old, new, "higher") == {"b": (2.0, 1.0)}


def test_merge_three_way():
    base = {"both": 5.0, "ours_rm": 1.0, "theirs_rm": 1.0}
    ours = {"both": 3.0, "theirs_rm": 1.0, "ours_add": 2.0}
    theirs = {"both": 4.0, "ours_rm": 1.0, "theirs_add": 6.0}
    assert budget.merge(base, ours, theirs, "lower") == {
        "both": 3.0,
        "ours_add": 2.0,
        "theirs_add": 6.0,
    }
    assert budget.merge(base, ours, theirs, "higher")["both"] == 4.0


def test_roundtrip_with_infinity(tmp_path):
    path = tmp_path / "sub" / "b.json"
    budget.save(path, {"z": INF, "a": 0.1 + 0.2}, "lower")
    assert budget.load(path, "lower") == {"z": INF, "a": 0.1 + 0.2}
    assert list(budget.load(path)) == ["a", "z"]
    with pytest.raises(ValueError, match="direction"):
        budget.load(path, "higher")


def test_missing_and_malformed(tmp_path):
    assert not budget.load(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("[1]")
    with pytest.raises(ValueError, match="not a budget"):
        budget.load(bad)


@pytest.mark.parametrize(
    "value,text", [(None, "-"), (3.0, "3"), (2.5, "2.5"), (INF, "inf")]
)
def test_fmt(value, text):
    assert budget.fmt(value) == text
