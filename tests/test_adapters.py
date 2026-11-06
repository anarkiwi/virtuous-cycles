import json
import sys

import pytest

from virtuous_cycles import adapters


def test_register_and_lookup():
    @adapters.register("test-const")
    def const(options):
        return {"k": options["v"]}

    assert adapters.get_adapter("test-const")({"v": 1.5}) == {"k": 1.5}
    with pytest.raises(ValueError, match="unknown adapter"):
        adapters.get_adapter("no-such-adapter")


def test_entry_point_plugin(monkeypatch):
    class EntryPoint:
        name = "test-plugin"

        @staticmethod
        def load():
            return lambda options: {"plugged": 1.0}

    monkeypatch.setattr(adapters, "entry_points", lambda group: [EntryPoint()])
    monkeypatch.delitem(adapters.ADAPTERS, "test-plugin", raising=False)
    assert adapters.get_adapter("test-plugin")({}) == {"plugged": 1.0}


@pytest.mark.parametrize(
    "path,segs",
    [
        ("$.a.b", ["a", "b"]),
        ("a[*].c", ["a", "*", "c"]),
        ("files.*['x.py'][0]", ["files", "*", "x.py", 0]),
        ('$["a.b"].c', ["a.b", "c"]),
    ],
)
def test_parse_path(path, segs):
    assert adapters.parse_path(path) == segs


def test_json_adapter(tmp_path):
    doc = {
        "files": {"a.py": {"summary": {"pct": 90}}, "b.py": {"summary": {"pct": 80.5}}},
        "totals": {"pct": 85},
        "runs": [{"n": "x", "t": 1}, {"n": "y", "t": 2}],
    }
    path = tmp_path / "m.json"
    path.write_text(json.dumps(doc))

    def run(**o):
        return adapters.get_adapter("json")({"file": str(path), **o})

    assert run(path="files.*.summary.pct") == {"a.py": 90.0, "b.py": 80.5}
    assert run(path="totals.pct") == {"totals.pct": 85.0}
    assert run(path="totals.pct", key="total") == {"total": 85.0}
    assert run(path="runs[*].t", sep=":") == {"0": 1.0, "1": 2.0}
    assert run(path="runs[-1].t", key="last") == {"last": 2.0}
    with pytest.raises(ValueError, match="not a number"):
        run(path="runs[0].n", key="n")
    with pytest.raises(KeyError):
        run(path="totals.missing")


def test_command_adapter(tmp_path):
    script = tmp_path / "emit.py"
    script.write_text('import json; print(json.dumps({"a": 1, "b": 2.5}))')
    cmd = adapters.get_adapter("command")
    assert cmd({"run": [sys.executable, str(script)]}) == {"a": 1.0, "b": 2.5}
    assert cmd({"run": f"{sys.executable} emit.py", "cwd": str(tmp_path)}) == {
        "a": 1.0,
        "b": 2.5,
    }
    script.write_text("print('[1, 2]')")
    with pytest.raises(ValueError, match="JSON object"):
        cmd({"run": [sys.executable, str(script)]})
    script.write_text("print('{\"a\": true}')")
    with pytest.raises(ValueError, match="not a number"):
        cmd({"run": [sys.executable, str(script)]})
