# pylint: skip-file
import functools
from contextlib import contextmanager
from typing import Annotated, Any, Callable, Iterator, overload

from pyfix.loops import kMax
from virtuous_cycles import vc


def leaf(x: int) -> int:
    return x + 1


def twice(x: int) -> int:
    return leaf(x) + leaf(x)


def fact(n: int) -> int:
    if n <= 1:
        return 1
    return n * fact(n - 1)


@vc.recursion("depth")
def walk(n: int) -> int:
    if n <= 1:
        return 1
    return walk(n - 1) + walk(n - 2)


@vc.cost("3 * kMax")
def priced(x: int) -> int:
    return x


def use_priced() -> int:
    return priced(1)


def keyed(xs: Annotated[list[int], vc.Size("n")]) -> list[int]:
    return sorted(xs, key=lambda v: -v)


def via_local(x: int) -> int:
    f = lambda v: v + 1
    return f(x)


def indirect(f: Callable[[int], int]) -> int:
    return f(1)


def chosen(f: Callable[[int], int]) -> int:
    return f(1)  # vc: targets(pyfix.calls.leaf, pyfix.calls.twice)


def deco(f: Callable[[int], int]) -> Callable[[int], int]:
    return f


@deco
def wrapped(x: int) -> int:
    return x


def call_wrapped() -> int:
    return wrapped(1)


def untyped(a):
    return a.go()


def branches(x: int) -> int:
    if x > 0:
        return 1
    elif x < 0:
        t = 1
        t += 1
        return t
    else:
        return 0


def risky(x: int) -> int:
    try:
        y = x + 1
    except ValueError:
        y = 0
        y += 1
    except KeyError:
        y = 2
    else:
        y = 5
    finally:
        x = 0
    return y + x


def matcher(v: int) -> int:
    match v:
        case 0:
            return 1
        case n if n > 5:
            return 2 + 3
        case _:
            return 3


def call_any(f: Any) -> None:
    f()


class Scorer:
    def __call__(self, v: int) -> int:
        return -v


def rank(xs: Annotated[list[int], vc.Size("n")], s: Scorer) -> int:
    ys = sorted(xs, key=s)
    return s(ys[0])


@overload
def pick(x: int) -> int: ...
@overload
def pick(x: str) -> str: ...
def pick(x: int | str) -> int | str:
    return x


def use_pick() -> int:
    return pick(3)


@vc.size("kMax")
def produce() -> list[int]:
    return [0] * kMax


def use_produce() -> int:
    t = 0
    for x in produce():
        t += x
    return t


def outer(k: int) -> int:
    def inner(v: int) -> int:
        return v + k

    return inner(1) + inner(2)


@contextmanager
def opened(k: int) -> Iterator[int]:
    yield k


def use_opened() -> int:
    with opened(3) as v:
        return v


@functools.lru_cache(maxsize=None)
def cached(k: int) -> int:
    return k * 2


def use_cached() -> int:
    return cached(1) + cached(2)


class AIter:
    def __aiter__(self) -> "AIter":
        return self

    async def __anext__(self) -> int:
        raise StopAsyncIteration


class ACtx:
    async def __aenter__(self) -> "ACtx":
        return self

    async def __aexit__(self, *a: object) -> None:
        pass


async def fetch(k: int) -> int:
    return k


async def gather_all(it: AIter, c: ACtx) -> int:
    t = await fetch(1)
    async with c:
        # vc: bound(4)
        async for v in it:
            t += v
    return t


class Ord:
    def __gt__(self, o: int) -> bool:
        return True


def misc2(a: Any, xs: list[int], dd: dict[str, int], o: Ord, flag: bool) -> int:
    a += 1
    x = 3  # vc: cost(7)

    @functools.cache
    def memo(k: int) -> int:
        return k

    p, *q = xs
    del dd["a"], dd["b"]
    y = (lambda v: v + 1)(2)
    z = flag and not flag or flag
    w = 3 < o
    return memo(x)


def via_builtin(xs: list[int]) -> int:
    g = len
    return g(xs)


class Holder:
    def __init__(self, s: Scorer, f: Callable[[int], int]) -> None:
        self.s = s
        self.f = f


def held(h: Holder) -> int:
    return h.s(1) + h.f(2)


def partial_call() -> int:
    p = functools.partial(leaf, 1)
    return p()
