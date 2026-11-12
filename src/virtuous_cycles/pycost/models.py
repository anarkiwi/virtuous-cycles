"""Costs of calls into code that is not analysed, and operation weights."""

import json
from dataclasses import dataclass, field

from virtuous_cycles.cost.program import glob

KINDS = ("const", "linear", "nlogn", "log", "indirect", "opaque", "transparent")
CONST_MODULES = (
    "{builtins,_operator,operator,math,cmath,typing,typing_extensions,abc,enum,"
    "dataclasses,functools,itertools,collections,collections.abc,_collections_abc,"
    "random,time,struct,numbers,types,contextlib,warnings,logging,io,_io,sys,"
    "os,os.path,posixpath,_typeshed,string,decimal,fractions,datetime,"
    "virtuous_cycles.vc}.*"
)
LIST_READS = "{index,count,copy,__contains__,__eq__,__ne__,__lt__,__le__,__gt__,__ge__}"
BUILTIN = [
    ("indirect", 0, "functools.partial.__call__"),
    ("nlogn", 0, "builtins.sorted"),
    ("nlogn", 1, "heapq.{nlargest,nsmallest}"),
    ("nlogn", -1, "builtins.list.sort"),
    (
        "log",
        0,
        "bisect.{bisect,bisect_left,bisect_right,insort,insort_left,insort_right}",
    ),
    ("log", 0, "heapq.{heappush,heappop,heappushpop,heapreplace}"),
    ("linear", 0, "heapq.heapify"),
    ("linear", 0, "builtins.{min,max}", 1, 1),
    (
        "linear",
        0,
        "builtins.{sum,any,all,list,tuple,set,frozenset,dict,bytes,bytearray}",
        1,
    ),
    ("linear", 0, "builtins.{str.join,dict.fromkeys,list.extend,list.__iadd__}"),
    ("linear", 0, "builtins.{set,dict}.{update,__ior__,__or__,union}"),
    ("linear", 0, "builtins.list.__mul__"),
    ("linear", 0, "collections.{deque,Counter,OrderedDict,defaultdict}", 1),
    ("linear", 0, "collections.deque.extend{,left}"),
    ("linear", 0, "{copy.copy,copy.deepcopy}"),
    ("linear", 1, "functools.reduce"),
    ("linear", -1, "builtins.{list,tuple}." + LIST_READS),
    ("linear", -1, "builtins.list.{remove,insert,reverse,__delitem__}"),
    ("linear", -1, "builtins.list.pop", 1),
    ("linear", -1, "builtins.{set,frozenset,dict}.{copy,__eq__,__ne__}"),
    ("linear", -1, "builtins.{set,frozenset}.{issubset,issuperset,__le__,__ge__}"),
    (
        "linear",
        -1,
        "collections.deque.{__contains__,remove,index,count,insert,rotate,reverse,copy}",
    ),
    ("nlogn", 0, "numpy.{sort,argsort,unique,median,percentile,quantile}"),
    ("nlogn", -1, "numpy.ndarray.{sort,argsort}"),
    (
        "linear",
        0,
        "numpy.{sum,mean,std,var,max,min,amax,amin,argmax,argmin,cumsum,cumprod,prod,"
        "any,all,abs,absolute,sqrt,exp,log,log2,log10,sin,cos,tan,copy,array,asarray,"
        "ascontiguousarray,concatenate,stack,where,clip,zeros_like,ones_like,"
        "empty_like,full_like,nonzero,count_nonzero,diff,round,floor,ceil,isnan,"
        "isfinite,maximum,minimum,add,subtract,multiply,divide,dot,vdot,"
        "zeros,ones,empty,full,arange}",
    ),
    ("linear", -1, "numpy.ndarray.*"),
    ("opaque", 0, "numpy.*"),
    ("transparent", 0, "builtins.{staticmethod,classmethod,property}"),
    ("transparent", 0, "abc.abstractmethod"),
    ("transparent", 0, "typing{,_extensions}.{final,overload,override,no_type_check}"),
    ("transparent", 0, "functools.{cache,lru_cache,wraps,cached_property}"),
    ("transparent", 0, "contextlib.{contextmanager,asynccontextmanager}"),
    ("transparent", 0, "numba.{njit,jit}"),
    ("transparent", 0, "*vc.{cost,recursion,size}"),
    ("const", 0, CONST_MODULES),
]


@dataclass(frozen=True)
class Model:
    """How a call to a function matching ``pattern`` is costed.

    ``arg`` is the argument whose size ``n`` is (-1: the object); the model
    applies to calls with ``min_args`` to ``max_args`` positional arguments.
    """

    kind: str
    pattern: str
    arg: int = 0
    min_args: int = 0
    max_args: int | None = None
    match: object = field(default=None, compare=False, repr=False)

    @classmethod
    def create(cls, kind, pattern, arg=0, min_args=0, max_args=None):
        """A model, its glob compiled."""
        return cls(kind, pattern, arg, min_args, max_args, glob(pattern))

    def applies(self, name, nargs):
        """True if this model costs a call to ``name`` with ``nargs`` arguments."""
        return (
            nargs >= self.min_args
            and (self.max_args is None or nargs <= self.max_args)
            and self.match(name)
        )


def builtin_models():
    """The standard library's and numpy's models, then constant catch-alls."""
    return [Model.create(k, p, a, *rest) for k, a, p, *rest in BUILTIN]


def parse_models(text):
    """``[{"match": GLOB, "cost": KIND, "arg": N, "min_args": N, "max_args": N}]``."""
    entries = json.loads(text)
    if not isinstance(entries, list):
        raise ValueError("models: expected a JSON array")
    out = []
    for e in entries:
        if not isinstance(e, dict) or e.get("cost") not in KINDS or "match" not in e:
            raise ValueError(
                'models: each entry needs "match" and a "cost" of ' + ", ".join(KINDS)
            )
        out.append(
            Model.create(
                e["cost"],
                e["match"],
                int(e.get("arg", 0)),
                int(e.get("min_args", 0)),
                e.get("max_args"),
            )
        )
    return out


@dataclass(frozen=True)
class Weights:
    """What one operation of each kind costs."""

    statement: float = 1.0
    condition: float = 1.0
    call: float = 1.0


def parse_weights(text):
    """``{"statement": X, "condition": Y, "call": Z}``, any subset."""
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("weights: expected a JSON object")
    for k, v in obj.items():
        if (
            k not in ("statement", "condition", "call")
            or isinstance(v, bool)
            or not isinstance(v, (int, float))
            or v < 0
        ):
            raise ValueError(
                f'weights: "{k}" is not statement, condition or call, or its value'
                " is not a non-negative number"
            )
    return Weights(**{k: float(v) for k, v in obj.items()})
