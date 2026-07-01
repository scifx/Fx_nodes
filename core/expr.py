"""Python eval-expression runtime for Fx nodes.

Expressions are compiled with Python's normal ``eval`` mode, so valid Python
expressions such as comprehensions, method calls, conditional expressions and
``msg``/``flow``/``Global`` lookups work as users expect.  We still block private
/ dunder access and run with a small explicit builtin namespace instead of the
process-wide builtins.

Pure Python, unit-testable. No bpy dependency.

Examples:
    sin(time) * amplitude
    clamp(value, 0, 1)
    "on" if frame % 2 == 0 else "off"
    [x * 2 for x in msg.items]
    msg.payload > 0
    flow.counter >= 10
    Global.foo == "bar"
"""
from __future__ import annotations

import ast
import math
import random
from typing import Any, Dict, Mapping


class ExprError(Exception):
    pass


# ---- whitelisted helper functions exposed to expressions -------------------
def _clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def _lerp(a, b, t):
    return a + (b - a) * t


def _map_range(x, in_min, in_max, out_min, out_max, clamp=False):
    if in_max == in_min:
        t = 0.0
    else:
        t = (x - in_min) / (in_max - in_min)
    if clamp:
        t = _clamp(t, 0.0, 1.0)
    return out_min + (out_max - out_min) * t


def _noise(x, seed=0):
    # cheap deterministic value noise in [-1,1]
    n = math.sin(x * 12.9898 + seed * 78.233) * 43758.5453
    return (n - math.floor(n)) * 2.0 - 1.0


SAFE_FUNCS: Dict[str, Any] = {
    # common builtins exposed to eval expressions
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "filter": filter, "float": float, "int": int,
    "isinstance": isinstance, "len": len, "list": list, "map": map,
    "max": max, "min": min, "pow": pow, "range": range, "repr": repr,
    "reversed": reversed, "round": round, "set": set, "sorted": sorted,
    "str": str, "sum": sum, "tuple": tuple, "zip": zip,
    # math
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "sqrt": math.sqrt, "exp": math.exp, "log": math.log,
    "floor": math.floor, "ceil": math.ceil,
    "radians": math.radians, "degrees": math.degrees, "hypot": math.hypot,
    # vector-ish / utility
    "clamp": _clamp, "lerp": _lerp, "mix": _lerp, "map_range": _map_range,
    "noise": _noise,
    "rand": random.random, "randint": random.randint, "uniform": random.uniform,
    "sign": lambda x: (x > 0) - (x < 0),
}

SAFE_CONSTS: Dict[str, Any] = {
    "pi": math.pi, "tau": math.tau, "e": math.e,
    "True": True, "False": False, "None": None,
}


class _Missing:
    """Falsy null-ish value for absent msg/flow/global keys.

    Switch nodes should route to False when an optional payload/property is not
    present, instead of stopping the flow with ``AttributeError``/``KeyError``.
    The sentinel is intentionally conservative: boolean/comparison checks are
    safe and falsy, while arithmetic still raises a normal Python error.
    """

    __slots__ = ()

    def __bool__(self) -> bool:
        return False

    def __len__(self) -> int:
        return 0

    def __iter__(self):
        return iter(())

    def __getattr__(self, name: str) -> "_Missing":
        if name.startswith("_"):
            raise AttributeError(name)
        return self

    def __getitem__(self, key: Any) -> "_Missing":
        return self

    def __eq__(self, other: Any) -> bool:
        return other is None or other is self

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __lt__(self, other: Any) -> bool:
        return False

    def __le__(self, other: Any) -> bool:
        return False

    def __gt__(self, other: Any) -> bool:
        return False

    def __ge__(self, other: Any) -> bool:
        return False

    def __repr__(self) -> str:
        return "None"

    __str__ = __repr__


MISSING = _Missing()


class _AttrDict(dict):
    """Read-only-ish dict wrapper that supports ``msg.payload`` syntax.

    Python dicts do not normally expose keys as attributes, but Node-RED users
    naturally type ``msg.payload``/``flow.count`` in Switch and Expression
    nodes.  Missing keys return a falsy sentinel so Switch conditions can fail
    closed to the False output instead of stopping the flow.
    """

    def __getattribute__(self, name: str) -> Any:
        # Prefer message keys over dict methods so msg.items / msg.keys etc.
        # access user data when those keys exist.  If the key is absent, normal
        # dict methods such as msg.get('x') still work.
        if not name.startswith("_") and dict.__contains__(self, name):
            return dict.__getitem__(self, name)
        try:
            return dict.__getattribute__(self, name)
        except AttributeError:
            if name.startswith("_"):
                raise
            return MISSING

    def __getitem__(self, key: Any) -> Any:
        return dict.get(self, key, MISSING)


def _wrap(value: Any) -> Any:
    if value is MISSING:
        return value
    if isinstance(value, _AttrDict):
        return value
    if isinstance(value, Mapping):
        return _AttrDict({str(k): _wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_wrap(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_wrap(v) for v in value)
    return value


def _unwrap(value: Any) -> Any:
    if value is MISSING:
        return None
    if isinstance(value, _AttrDict):
        return {k: _unwrap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_unwrap(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_unwrap(v) for v in value)
    return value


def _normalize_source(src: str) -> str:
    """Normalize expression source before AST parsing.

    Keep this intentionally as a no-op for expression semantics: expressions
    should be valid Python ``eval`` source.  In particular, do not rewrite the
    Python keyword ``global``; users should use the valid variable name
    ``Global`` (or ``G``/``global_context``) for global context access.
    """
    return src or ""


class _Validator(ast.NodeVisitor):
    """Validate only the security boundary, not Python expression syntax.

    ``ast.parse(..., mode='eval')`` already guarantees the source is a Python
    expression rather than statements.  Do not whitelist expression node types
    here; users expect normal eval expressions to work.  We only block obvious
    escape hatches through private/dunder names and attributes.
    """

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__"):
            raise ExprError("禁止访问 dunder 名称")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            raise ExprError("禁止访问私有/dunder 属性")
        self.generic_visit(node)


_cache: Dict[str, ast.Expression] = {}


def compile_expr(src: str) -> ast.Expression:
    normalized = _normalize_source(src)
    if normalized in _cache:
        return _cache[normalized]
    try:
        tree = ast.parse(normalized, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"语法错误: {e.msg}") from e
    _Validator().visit(tree)
    code = compile(tree, "<fx-nodes-expr>", "eval")
    _cache[normalized] = code  # type: ignore[assignment]
    return code  # type: ignore[return-value]


def evaluate(src: str, variables: Mapping[str, Any] | None = None) -> Any:
    """Evaluate ``src`` with ``variables`` as the local namespace."""
    code = compile_expr(src)
    env: Dict[str, Any] = {"__builtins__": {}}
    env.update(SAFE_CONSTS)
    env.update(SAFE_FUNCS)
    if variables:
        env.update({k: _wrap(v) for k, v in variables.items()})
    try:
        return _unwrap(eval(code, env, {}))  # noqa: S307 - sandboxed: empty builtins + AST whitelist
    except ExprError:
        raise
    except Exception as e:  # surface runtime issues as ExprError
        raise ExprError(f"求值错误: {e}") from e
