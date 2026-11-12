# pylint: skip-file
import json
from typing import Annotated, Generator, Iterator

from virtuous_cycles import vc


def gen(xs: Annotated[list[int], vc.Size("n")]) -> Iterator[int]:
    for x in xs:
        yield x


def consume(xs: Annotated[list[int], vc.Size("n")]) -> int:
    t = 0
    for v in gen(xs):
        t += v
    return t


def chain(xs: Annotated[list[int], vc.Size("n")]) -> Iterator[int]:
    yield from gen(xs)
    yield 0


def consume_chain(xs: Annotated[list[int], vc.Size("n")]) -> int:
    return sum(chain(xs))


def lib(xs: Annotated[list[int], vc.Size("n")], ys: list[int]) -> int:
    a = 3 in xs
    b = xs[1:]
    xs.append(4)
    c = len(ys)
    return sum(ys)


def external(s: str) -> object:
    return json.loads(s)


@vc.size("k")
def capped_gen(xs: Annotated[list[int], vc.Size("n")]) -> Iterator[int]:
    for x in xs:
        yield x


def consume_capped(xs: Annotated[list[int], vc.Size("n")]) -> int:
    t = 0
    for v in capped_gen(xs):
        t += v
    return t


class Ctx2:
    def __enter__(self) -> "Ctx2":
        return self

    def __exit__(self, *a: object) -> None:
        pass


def shapes(xs: Annotated[list[int], vc.Size("n")], c: Ctx2, k: int) -> Iterator[int]:
    # vc: bound(3)
    while k > 0:
        yield k
        k -= 1
    if k:
        yield 1
        yield 2
    elif xs:
        yield 3
    try:
        yield 4
    except ValueError:
        yield 5
        yield 6
    finally:
        yield 7
    with c:
        yield 8
    match k:
        case 0:
            yield 9
        case _:
            pass
    yield from xs


def consume_shapes(xs: Annotated[list[int], vc.Size("n")], c: Ctx2) -> int:
    return sum(shapes(xs, c, 2))


def from_unsized(ys: list[int]) -> Iterator[int]:
    yield from ys


def consume_unsized(ys: list[int]) -> int:
    t = 0
    for v in from_unsized(ys):
        t += v
    return t


def walk_tree(n: int) -> Iterator[int]:
    yield n
    if n > 0:
        yield from walk_tree(n - 1)


def consume_walk() -> int:
    return sum(walk_tree(3))


def odd_gen(xs: Annotated[list[int], vc.Size("(")]) -> Iterator[int]:
    for x in xs:
        yield x


def tail(ys: list[int]) -> list[int]:
    return ys[1:]


def sub(ys: list[int]) -> Generator[int, None, int]:
    yield from ys
    return 0


def sparse(xs: Annotated[list[int], vc.Size("n")], ys: list[int]) -> Iterator[int]:
    def helper() -> int:
        return 1

    f = lambda v: v
    for x in xs:
        t = x
    yield f(helper())
    for y in xs:
        print((yield from sub(ys)))


def consume_sparse(xs: Annotated[list[int], vc.Size("n")], ys: list[int]) -> int:
    return sum(sparse(xs, ys))


def opaque(x: int) -> str:
    return json.dumps(x)


class Counter:
    def __init__(self) -> None:
        self.k = 0

    def __iter__(self) -> "Counter":
        return self

    def __next__(self) -> int:
        self.k += 1
        if self.k > 3:
            raise StopIteration
        return self.k


def gen_not_counter(xs: Annotated[list[int], vc.Size("n")]) -> int:
    t = 0
    for v in gen(xs):
        t += v
    return t


def offset(xs: Annotated[list[int], vc.Size("n")], k: int) -> int:
    t = 0
    for i in range(k % 3, len(xs)):
        t += i
    for j in range(len(xs) - k % 3):
        t += j
    for _ in range(k % 3, 10):
        t += 1
    return t
