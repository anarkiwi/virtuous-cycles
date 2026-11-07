import json
import subprocess
import sys

import pytest

from virtuous_cycles import budget
from virtuous_cycles.cli import main

CONFIG = """
[[metric]]
name = "cost"
adapter = "json"
budget = "budgets/cost.json"
select = ["f*", "g"]
[metric.options]
file = "values.json"
path = "cost.*"

[[metric]]
name = "cov"
adapter = "json"
direction = "higher"
budget = "budgets/cov.json"
[metric.options]
file = "values.json"
path = "cov.*"
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    for var, val in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }.items():
        monkeypatch.setenv(var, val)
    (tmp_path / "virtuous-cycles.toml").write_text(CONFIG)
    put(tmp_path, {"f1": 2, "f2": 4, "g": 1, "skip": 99}, {"a": 80})
    monkeypatch.chdir(tmp_path)
    return tmp_path


def put(root, cost, cov):
    (root / "values.json").write_text(json.dumps({"cost": cost, "cov": cov}))


def run(*argv):
    return main(["-q", *argv])


def git(root, *argv):
    return subprocess.run(
        ["git", "-C", str(root), *argv], check=True, capture_output=True, text=True
    )


def test_check_fails_until_budgeted(project, capsys):
    assert run("check") == 1
    assert "cost: f1: 2 has no budget" in capsys.readouterr().out
    assert run("tighten") == 0
    assert budget.load(project / "budgets/cost.json", "lower") == {
        "f1": 2,
        "f2": 4,
        "g": 1,
    }
    assert run("check") == 0
    assert capsys.readouterr().out.endswith("ok\n")


def test_regressions_and_ratchet(project, capsys):
    run("tighten")
    put(project, {"f1": 3, "f2": 1, "g": 1}, {"a": 70, "b": 5})
    capsys.readouterr()
    assert run("check") == 1
    out = capsys.readouterr().out
    assert "cost: f1: 3 worse than budget 2" in out
    assert "cov: a: 70 worse than budget 80" in out
    assert "cov: b: 5 has no budget" in out
    assert "f2" not in out
    put(project, {"f1": 2, "f2": 1}, {"a": 90})
    run("tighten")
    assert budget.load(project / "budgets/cost.json") == {"f1": 2, "f2": 1}
    assert budget.load(project / "budgets/cov.json") == {"a": 90}


def test_report(project, capsys):
    run("tighten")
    put(project, {"f1": 1, "f2": 5, "h": 0}, {"a": 80, "new": 1})
    capsys.readouterr()
    assert run("report", "--json") == 0
    status = {
        (r["metric"], r["key"]): r["status"]
        for r in json.loads(capsys.readouterr().out)
    }
    assert status == {
        ("cost", "f1"): "better",
        ("cost", "f2"): "worse",
        ("cost", "g"): "gone",
        ("cov", "a"): "ok",
        ("cov", "new"): "new",
    }
    assert run("-m", "cost", "report") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["metric", "key", "value", "budget", "status"]
    assert lines[3].split() == ["cost", "g", "-", "1", "gone"]
    assert len(lines) == 4


def test_check_against_ref(project, capsys):
    git(project, "init", "-q")
    run("check", "--against", "HEAD")
    assert "virtuous-cycles:" in capsys.readouterr().err
    run("tighten")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "budgets")
    assert run("check", "--against", "HEAD") == 0
    put(project, {"f1": 5, "f2": 4, "g": 1}, {"a": 80})
    run("tighten")
    data = json.loads((project / "budgets/cost.json").read_text())
    data["budgets"]["f1"] = 5
    (project / "budgets/cost.json").write_text(json.dumps(data))
    capsys.readouterr()
    assert run("check", "--against", "HEAD") == 1
    assert "cost: f1: budget loosened 2 -> 5 since HEAD" in capsys.readouterr().out
    assert run("check") == 0
    assert run("check", "--against", "no-such-ref") == 2


def test_check_against_direction_change_and_absent_file(project, capsys):
    git(project, "init", "-q")
    run("tighten")
    (project / "budgets/cov.json").write_text(budget.dumps({"a": 80}, "lower"))
    git(project, "add", "-A")
    git(project, "commit", "-qm", "budgets")
    (project / "budgets/cov.json").write_text(budget.dumps({"a": 80}, "higher"))
    capsys.readouterr()
    assert run("-m", "cov", "check", "--against", "HEAD") == 1
    assert "direction changed" in capsys.readouterr().out
    (project / "budgets/cost.json").rename(project / "budgets/cost2.json")
    (project / "virtuous-cycles.toml").write_text(
        CONFIG.replace("cost.json", "cost2.json")
    )
    assert run("-m", "cost", "check", "--against", "HEAD") == 0


def test_config_errors(tmp_path, capsys):
    assert main(["-c", str(tmp_path / "missing.toml"), "check"]) == 2
    (tmp_path / "virtuous-cycles.toml").write_text(
        CONFIG.replace('"json"', '"nope"', 1)
    )
    assert main(["-q", "-c", str(tmp_path / "virtuous-cycles.toml"), "report"]) == 2
    assert "unknown adapter 'nope'" in capsys.readouterr().err


def test_merge_driver_in_real_merge(project):
    git(project, "init", "-q", "-b", "main")
    git(
        project,
        "config",
        "merge.virtuous-cycles.driver",
        f"{sys.executable} -m virtuous_cycles.cli merge-driver %O %A %B %P",
    )
    (project / ".gitattributes").write_text("budgets/*.json merge=virtuous-cycles\n")
    path = project / "budgets/cost.json"
    budget.save(path, {"f1": 5, "f2": 5, "g": 5, "gone": 1}, "lower")
    git(project, "add", "-A")
    git(project, "commit", "-qm", "base")
    git(project, "checkout", "-qb", "side")
    budget.save(path, {"f1": 3, "f2": 5, "g": 4, "gone": 1, "side": 2}, "lower")
    git(project, "commit", "-qam", "side")
    git(project, "checkout", "-q", "main")
    budget.save(path, {"f1": 4, "f2": 2, "g": 5, "main": 7}, "lower")
    git(project, "commit", "-qam", "main")
    git(project, "merge", "-q", "--no-edit", "side")
    assert budget.load(path, "lower") == {
        "f1": 3,
        "f2": 2,
        "g": 4,
        "main": 7,
        "side": 2,
    }


def test_merge_driver_conflicts(tmp_path):
    base, ours, theirs = (tmp_path / n for n in ("o", "a", "b"))
    base.write_text("")
    ours.write_text(budget.dumps({"k": 1}, "lower"))
    theirs.write_text(budget.dumps({"k": 2}, "higher"))
    assert main(["merge-driver", str(base), str(ours), str(theirs)]) == 1
    theirs.write_text(budget.dumps({"k": 0, "j": 1}, "lower"))
    assert main(["merge-driver", str(base), str(ours), str(theirs), "x.json"]) == 0
    assert budget.load(ours, "lower") == {"k": 0, "j": 1}


def test_limits_fail_check_within_budget(project, capsys):
    run("tighten")
    with open(project / "virtuous-cycles.toml", "a", encoding="utf-8") as f:
        f.write('[metric.limits]\n"*" = 50\n"a" = 85\n')
    with open(project / "virtuous-cycles.toml", encoding="utf-8") as f:
        text = f.read()
    (project / "virtuous-cycles.toml").write_text(
        text.replace(
            'path = "cost.*"\n',
            'path = "cost.*"\n[metric.limits]\n"f*" = 3\n"f2" = 9\n',
        )
    )
    capsys.readouterr()
    assert run("check") == 1
    out = capsys.readouterr().out.splitlines()
    assert sorted(out) == [
        "cost: f2: 4 over limit 3",
        "cov: a: 80 over limit 85",
    ]
    assert run("report", "--json") == 0
    status = {
        (r["metric"], r["key"]): r["status"]
        for r in json.loads(capsys.readouterr().out)
    }
    assert status == {
        ("cost", "f1"): "ok",
        ("cost", "f2"): "over",
        ("cost", "g"): "ok",
        ("cov", "a"): "over",
    }
    put(project, {"f1": 2, "f2": 3, "g": 1}, {"a": 85})
    assert run("check") == 0
