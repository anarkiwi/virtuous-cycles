# pylint: skip-file
from typing import Annotated, Final, Literal, cast

from virtuous_cycles import vc

kMax: Final = 16
kPool: Final = 64


def linear(xs: Annotated[list[int], vc.Size("n")]) -> int:
    s = 0
    for x in xs:
        s += x
    return s


def nested(xs: Annotated[list[int], vc.Size("n")]) -> int:
    t = 0
    for i in range(len(xs)):
        for j in range(i):
            t += j
    return t


def constant() -> int:
    t = 0
    for i in range(2, 10, 3):
        t += i
    return t


def down(n: Annotated[int, vc.Size("m")]) -> int:
    t = 0
    for i in range(n, -1, -1):
        t += i
    return t


def capped() -> int:
    t = 0
    for _ in range(kMax):
        t += 1
    return t


def unbounded(k: int) -> int:
    while k > 0:
        k -= 1
    return k


def bounded(k: int) -> int:
    # vc: bound(kMax)
    while k > 0:
        k -= 1
    return k


def misplaced(k: int) -> int:
    k += 1  # vc: bound(3)
    return k


def grid(
    rows: Annotated[list[Annotated[list[int], vc.Size("m")]], vc.Size("n")],
) -> int:
    t = 0
    for row in rows:
        for x in row:
            t += x
    return t


def shared(
    rows: Annotated[list[Annotated[list[int], vc.Size("m")]], vc.Size("n")],
) -> int:
    t = 0
    for row in rows:
        # vc: total(kPool)
        for x in row:
            t += x
    return t


def local(xs: Annotated[list[int], vc.Size("n")]) -> int:
    ys = sorted(xs)
    half = len(ys) // 2
    t = 0
    for i in range(half):
        t += ys[i]
    return t


def mutated(xs: Annotated[list[int], vc.Size("n")]) -> int:
    ys = [1, 2]
    ys.append(3)
    t = 0
    for y in ys:
        t += y
    return t


def squares(xs: Annotated[list[int], vc.Size("n")]) -> list[int]:
    return [x * x for x in xs if x > 0]


def counted(xs: Annotated[list[int], vc.Size("n")]) -> int:
    t = 0
    for i, x in enumerate(xs):
        for _ in range(i):
            t += x
    return t


def bad_annotation(k: int) -> int:
    # vc: bound(3 +)
    while k > 0:
        k -= 1
    return k


def sizes(
    xs: Annotated[list[int], vc.Size("n")], k: Annotated[int, vc.Size("k")]
) -> int:
    t = 0
    for a, b in zip(xs, range(3)):
        t += a
    for c in map(abs, xs):
        t += c
    for d in filter(None, xs):
        t += d
    for e in range(min(k, 4)):
        t += e
    for f in range(max(k, 4)):
        t += f
    return t


def arith(n: Annotated[int, vc.Size("n")], flag: bool) -> int:
    t = 0
    for i in range(n // 2):
        t += i
    for i in range(10 >> 1):
        t += i
    for i in range(3 << 2):
        t += i
    for i in range(n % 4):
        t += i
    for i in range(n & 7):
        t += i
    for i in range(9 - 4):
        t += i
    for i in range(n - 1):
        t += i
    for i in range(5 if flag else n):
        t += i
    for i in range(20 // 6):
        t += i
    for i in range(max(-1, 2)):
        t += i
    return t


def displays(
    xs: Annotated[list[int], vc.Size("n")],
    d: Annotated[dict[str, int], vc.Size("m")],
    p: tuple[int, int, int],
    lit: Literal[4],
) -> int:
    t = 0
    for a in [1, *xs, 2]:
        t += a
    for k in {"a": 1, **d}:
        t += 1
    for ch in "abc":
        t += 1
    for by in b"xy":
        t += by
    for q in p:
        t += q
    for i in range(lit):
        t += i
    for z in xs + [0]:
        t += z
    for w in [0] * 3:
        t += w
    return t


def comps(xs: Annotated[list[int], vc.Size("n")], ys: list[int]) -> int:
    s = {x for x in xs}
    d = {x: x for x in xs if x}
    u = [y for y in ys]
    return len(s) + len(d) + len(u)


def pairs(ps: Annotated[list[tuple[int, int]], vc.Size("n")]) -> int:
    t = 0
    for i, (a, b) in enumerate(ps):
        t += a * b + i
    return t


def misc(xs: Annotated[list[int], vc.Size("n")], k: int) -> int:
    assert k >= 0, "neg"
    if (m := len(xs)) > 3:
        try:
            raise ValueError("x") from None
        except ValueError:
            pass
    # vc: bound(2)
    while k > 0:
        k -= 1
    else:
        k = 5
    for x in xs:
        t = x
    else:
        t = 0
    return m + k + t


def bounds_more(
    xs: Annotated[list[int], vc.Size("n")],
    grid: Annotated[list[Annotated[list[int], vc.Size("m")]], vc.Size("n")],
    d: Annotated[dict[str, int], vc.Size("n")],
    k: Annotated[int, vc.Size("k")],
    u: int,
) -> int:
    t = 0
    for a in cast(list[int], xs):
        t += a
    for b in [y * 2 for y in xs]:
        t += b
    for c in grid[0]:
        t += c
    for e in xs[1:]:
        t += e
    for f in d.keys():
        t += 1
    for g in range(k >> 1):
        t += g
    for h in range(u & 7):
        t += h
    for i in range(0, 5, 0):
        t += i
    for j in range(k, 0, -2):
        for _ in range(j):
            t += 1
    return t + sum(z for z in xs)


def plain() -> list[int]:
    return [1]


def unsized(ys: list[int], d: dict[str, int], s: int) -> int:
    t = 0
    for a in [*ys]:
        t += a
    for b in {**d}:
        t += 1
    for c in range(max(s, 3)):
        t += c
    for e in range(0, 9, s):
        t += e
    for f in range(max(ys)):
        t += f
    zs = [1]
    zs = [2, 3]
    for q in zs:
        t += q
    for w in "a,b".split(","):
        t += 1
    for p in plain():
        t += p
    return t


def made(k: int) -> Annotated[list[int], vc.Size("k")]:
    return []


def use_made() -> int:
    t = 0
    for x in made(3):
        t += x
    return t


def anything(k: int) -> int:
    # vc: bound(?)
    while k:
        k -= 1
    return k


class Cursor:
    def __init__(self, start: int = 0) -> None:
        self.pos = start

    def scan(self, xs: Annotated[list[int], vc.Size("n")]) -> int:
        for self.pos in xs:
            pass
        return self.pos
