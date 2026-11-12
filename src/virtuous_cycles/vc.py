"""Annotations read by ``vc-py-cost``; at runtime they do nothing.

See docs/py-cost.md: ``Annotated[T, vc.Size(expr)]``, ``Annotated[int,
vc.Symbol(name)]`` and the ``@vc.cost``/``@vc.recursion``/``@vc.size`` decorators.
"""

from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)


class Size:
    """Upper bound of a value (an integer) or length (a container)."""

    __slots__ = ("expr",)

    def __init__(self, expr: str | int) -> None:
        self.expr = expr


class Symbol:
    """The symbol a constant is reported as."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name


def _identity(fn: F) -> F:
    return fn


def cost(_expr: str | int) -> Callable[[F], F]:
    """The function's whole cost."""
    return _identity


def recursion(_expr: str | int) -> Callable[[F], F]:
    """Activations of the function's recursive cycle per call."""
    return _identity


def size(_expr: str | int) -> Callable[[F], F]:
    """Upper bound of what the function returns; for a generator, its items."""
    return _identity
