# pylint: skip-file
import functools
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Annotated, Callable, Iterator, Protocol, TypedDict, TypeVar, final

from pyfix.gens import odd_gen
from pyfix.loops import kMax
from virtuous_cycles import vc


class Shape:
    def area(self) -> int:
        return 0


class Square(Shape):
    def __init__(self, s: int) -> None:
        self.s = s

    def area(self) -> int:
        return self.s * self.s


class Big(Shape):
    def area(self) -> int:
        t = 0
        for i in range(kMax):
            t += i
        return t


class Sub(Square):
    def __init__(self) -> None:
        super().__init__(2)


def total(s: Shape) -> int:
    return s.area()


def exact(s: Square) -> int:
    return s.area()


def make_sub() -> int:
    s = Sub()
    return s.area()


class HasArea(Protocol):
    def area(self) -> int: ...


def proto(h: HasArea) -> int:
    return h.area()


class Abstract(ABC):
    @abstractmethod
    def run(self) -> int: ...


def none(a: Abstract) -> int:
    return a.run()


class Box:
    def __init__(self) -> None:
        self._v = 0

    @property
    def v(self) -> int:
        return self._v


def prop(b: Box) -> int:
    return b.v


@dataclass
class Point:
    x: int

    def __post_init__(self) -> None:
        self.x += 1


def point() -> int:
    p = Point(1)
    return p.x


class Ctx:
    def __enter__(self) -> "Ctx":
        return self

    def __exit__(self, *a: object) -> None:
        pass


def use_ctx() -> int:
    with Ctx():
        return 1


class Dyn:
    def __getattr__(self, name: str) -> Callable[[], int]:
        raise AttributeError(name)


def dyn(d: Dyn) -> int:
    return d.anything()


class Pool:
    def __init__(self, notes: Annotated[list[int], vc.Size("kNotes")]) -> None:
        self.notes: Annotated[list[int], vc.Size("kNotes")] = notes

    def tick(self) -> int:
        t = 0
        # vc: run_total(kNotes)
        for x in self.notes:
            t += x
        return t


def run(pools: Annotated[list[Pool], vc.Size("kChannels")]) -> int:
    t = 0
    for p in pools:
        t += p.tick()
    return t


class Vec:
    def __init__(self, x: int) -> None:
        self.x = x

    def __add__(self, o: "Vec") -> "Vec":
        return Vec(self.x + o.x)

    def __radd__(self, o: int) -> "Vec":
        return Vec(self.x + o)

    def __neg__(self) -> "Vec":
        return Vec(-self.x)

    def __contains__(self, v: int) -> bool:
        return v == self.x

    def __len__(self) -> int:
        return 1

    def __getitem__(self, i: int) -> int:
        return self.x

    def __setitem__(self, i: int, v: int) -> None:
        self.x = v


def vec_ops(a: Vec, b: Vec) -> int:
    c = a + b
    d = 1 + a
    e = -c
    f = 3 in a
    a[0] = len(b)
    return a[1] + e.x


class Acc:
    def __init__(self) -> None:
        self.n = 0

    def __iadd__(self, k: int) -> "Acc":
        self.n += k
        return self


class Plain:
    def __add__(self, k: int) -> "Plain":
        return self


def accumulate(a: Acc, p: Plain) -> None:
    a += 1
    p += 2


class Temp:
    def __init__(self) -> None:
        self._c = 0

    @property
    def c(self) -> int:
        return self._c

    @c.setter
    def c(self, v: int) -> None:
        self._c = v


def warm(t: Temp, d: dict[str, int], v: Vec) -> int:
    t.c = 5
    t.c += 1
    del d["k"]
    del v.x
    v[0] += 2
    return t.c


class Maker:
    def __init__(self, k: int) -> None:
        self.k = k

    @classmethod
    def make(cls, k: int) -> "Maker":
        return Maker(k)

    @classmethod
    def twice(cls) -> "Maker":
        cls.make(1)
        return cls.make(2)


def build_maker() -> int:
    m = Maker.twice()
    return m.k


class Cat:
    def speak(self) -> int:
        return 1


class Dog:
    def speak(self) -> int:
        x = 1
        return x


def speak(p: Cat | Dog, q: Cat | None) -> int:
    q.speak()  # type: ignore[union-attr]
    return p.speak()


class Base:
    @final
    def fixed(self) -> int:
        return 1

    def open(self) -> int:
        return 1


@final
class Leaf(Base):
    def open(self) -> int:
        y = 2
        return y


def finals(b: Base, l: Leaf) -> int:
    b.fixed()
    return b.open() + l.open()


class Ticker:
    def __init__(self, n: int) -> None:
        self.n = n

    def __next__(self) -> int:
        if self.n <= 0:
            raise StopIteration
        self.n -= 1
        return self.n


class Countdown:
    def __init__(self, n: int) -> None:
        self.n = n

    def __iter__(self) -> Ticker:
        return Ticker(self.n)


def drain(c: Countdown) -> int:
    t = 0
    # vc: bound(kMax)
    for v in c:
        t += v
    return t


class Lazy:
    @functools.cached_property
    def heavy(self) -> int:
        t = 0
        for i in range(kMax):
            t += i
        return t


def use_lazy(z: Lazy) -> int:
    return z.heavy


class Bag:
    def __init__(self, xs: Annotated[list[int], vc.Size("n")]) -> None:
        self.xs = xs

    def items(self) -> Iterator[int]:
        for x in self.xs:
            yield x


def use_bag(b: Bag) -> int:
    t = 0
    for v in b.items():
        t += v
    return t


def use_odd(xs: list[int]) -> int:
    return sum(odd_gen(xs))


class TD(TypedDict):
    a: int


T = TypeVar("T", bound=Shape)


def generic(s: T, td: TD) -> int:
    return s.area() + td.get("a", 0)
