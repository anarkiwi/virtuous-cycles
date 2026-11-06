"""Adapter registry: an adapter maps its options to ``{key: value}``."""

import json
import shlex
import subprocess
from importlib.metadata import entry_points

ADAPTERS = {}
ENTRY_POINT_GROUP = "virtuous_cycles.adapters"


def register(name):
    """Decorator registering ``fn(options) -> dict[str, float]`` as ``name``."""

    def deco(fn):
        ADAPTERS[name] = fn
        return fn

    return deco


def get_adapter(name):
    """Look up an adapter, loading installed entry-point plugins on demand."""
    if name not in ADAPTERS:
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            if ep.name == name:
                ADAPTERS[name] = ep.load()
    try:
        return ADAPTERS[name]
    except KeyError:
        raise ValueError(f"unknown adapter {name!r}") from None


def numeric_map(obj, source):
    """Validate a decoded ``{key: number}`` object."""
    if not isinstance(obj, dict):
        raise ValueError(f"{source}: expected a JSON object of key to number")
    out = {}
    for k, v in obj.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"{source}: {k!r} is not a number: {v!r}")
        out[str(k)] = float(v)
    return out


@register("command")
def command(options):
    """Run ``options['run']`` and parse stdout as a JSON object of numbers."""
    run = options["run"]
    argv = shlex.split(run) if isinstance(run, str) else list(run)
    out = subprocess.run(
        argv, check=True, capture_output=True, text=True, cwd=options.get("cwd")
    ).stdout
    return numeric_map(json.loads(out), argv[0])


def parse_path(path):
    """Split a JSONPath-like path into segments; ``*`` is a wildcard."""
    path = path.strip()
    path = path[1:] if path.startswith("$") else path
    segs, i = [], 0
    while i < len(path):
        if path[i] == ".":
            i += 1
        elif path[i] == "[":
            j = path.index("]", i)
            tok = path[i + 1 : j].strip()
            if tok[:1] in "\"'":
                segs.append(tok[1:-1])
            else:
                segs.append(tok if tok == "*" else int(tok))
            i = j + 1
        else:
            j = i
            while j < len(path) and path[j] not in ".[":
                j += 1
            segs.append(path[i:j])
            i = j
    return segs


def walk(node, segs, captured=()):
    """Yield ``(captures, value)`` for every match of ``segs`` in ``node``."""
    if not segs:
        yield captured, node
        return
    seg, rest = segs[0], segs[1:]
    if seg == "*":
        items = node.items() if isinstance(node, dict) else enumerate(node)
        for k, child in items:
            yield from walk(child, rest, captured + (str(k),))
    elif isinstance(node, list) and str(seg).lstrip("-").isdigit():
        yield from walk(node[int(seg)], rest, captured)
    else:
        yield from walk(node[seg], rest, captured)


@register("json")
def json_path(options):
    """Values at ``options['path']`` in ``options['file']``.

    The key is the wildcard captures joined by ``options['sep']`` (default
    ``/``), or ``options['key']`` / the path itself when nothing is captured.
    """
    with open(options["file"], encoding="utf-8") as f:
        doc = json.load(f)
    sep, path = options.get("sep", "/"), options["path"]
    found = {
        sep.join(caps) if caps else options.get("key", path): v
        for caps, v in walk(doc, parse_path(path))
    }
    return numeric_map(found, f"{options['file']}:{path}")
