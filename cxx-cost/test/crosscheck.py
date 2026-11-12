"""Run vc-cxx-cost and check that the Python backend composes its IR alike.

Usage: crosscheck.py TOOL ARGS...  The tool's output and exit status pass
through unchanged; a report that differs from the Python backend's exits 3.
"""

import difflib
import json
import os
import subprocess
import sys
import tempfile


def report_path(args):
    """The `-o` path among the tool's own options, or None for stdout."""
    for i, arg in enumerate(args):
        if arg == "--":
            break
        name, eq, value = arg.lstrip("-").partition("=")
        if arg.startswith("-") and name == "o":
            path = value if eq else (args[i + 1 :] or [None])[0]
            return None if path == "-" else path
    return None


def stamp(path):
    """The modification time of `path`, or None if it does not exist."""
    return os.stat(path).st_mtime_ns if path and os.path.exists(path) else None


def pretty(report):
    """`report` as diffable lines."""
    return json.dumps(report, indent=1, sort_keys=True).splitlines(keepends=True)


def compare(ir, text):
    """None if the Python backend's report from `ir` equals `text`, else why."""
    python = subprocess.run(
        [sys.executable, "-m", "virtuous_cycles.cost.ir", ir],
        capture_output=True,
        text=True,
        check=False,
    )
    if python.returncode:
        return f"python backend exited {python.returncode}\n{python.stderr}"
    want, got = json.loads(text), json.loads(python.stdout)
    if want == got:
        return None
    return "".join(difflib.unified_diff(pretty(want), pretty(got), "cxx", "python"))


def main():
    """Run the tool, pass its output through and cross-check its report."""
    tool, args = sys.argv[1], sys.argv[2:]
    out = report_path(args)
    before = stamp(out)
    with tempfile.TemporaryDirectory() as tmp:
        ir = os.path.join(tmp, "ir.json")
        run = subprocess.run(
            [tool, "--emit-ir", ir, *args],
            stdout=None if out else subprocess.PIPE,
            check=False,
        )
        if not out:
            sys.stdout.buffer.write(run.stdout)
            sys.stdout.flush()
        if run.returncode in (0, 2) and os.path.exists(ir):
            text = None if out else run.stdout.decode()
            if out and stamp(out) not in (None, before):
                with open(out, encoding="utf-8") as f:
                    text = f.read()
            if text and text.strip():
                why = compare(ir, text)
                if why:
                    sys.stderr.write(why)
                    return 3
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
