"""Safe expression sandbox.

Evaluates user-authored expressions used by Expression / AI nodes WITHOUT
exposing ``eval``/``exec``/imports/dunder access. Implemented as an AST
walker with a strict whitelist of node types, names and callables.

Pure Python, unit-testable. No bpy dependency.

Examples of allowed expressions:
    sin(time) * amplitude
    clamp(value, 0, 1)
    "on" if frame % 2 == 0 else "off"
    {"x": i, "y": i*2}
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
    # math
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "sqrt": math.sqrt, "pow": pow, "exp": math.exp, "log": math.log,
    "floor": math.floor, "ceil": math.ceil, "abs": abs, "round": round,
    "radians": math.radians, "degrees": math.degrees, "hypot": math.hypot,
    "min": min, "max": max, "sum": sum, "len": len,
    "int": int, "float": float, "str": str, "bool": bool,
    # vector-ish / utility
    "clamp": _clamp, "lerp": _lerp, "mix": _lerp, "map_range": _map_range,
    "noise": _noise,
    "rand": random.random, "randint": random.randint, "uniform": random.uniform,
    "range": lambda *a: list(range(*a)),
    "sign": lambda x: (x > 0) - (x < 0),
}

SAFE_CONSTS: Dict[str, Any] = {
    "pi": math.pi, "tau": math.tau, "e": math.e,
    "True": True, "False": False, "None": None,
}

# AST node types we permit. Anything else is rejected.
_ALLOWED_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
    ast.Call, ast.keyword,
    ast.List, ast.Tuple, ast.Dict, ast.Set,
    ast.Subscript, ast.Slice, ast.Index if hasattr(ast, "Index") else ast.Slice,
    ast.Attribute,
    # operators
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd, ast.Not,
    ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.BitAnd, ast.BitOr, ast.BitXor,
)

# attribute access only allowed on these object roots (e.g. vector .x)
_ALLOWED_ATTRS = {"x", "y", "z", "w", "r", "g", "b", "a", "real", "imag"}


class _Validator(ast.NodeVisitor):
    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, _ALLOWED_NODES):
            raise ExprError(f"不允许的语法: {type(node).__name__}")
        super().generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id.startswith("__"):
            raise ExprError("禁止访问 dunder 名称")
        # name resolution happens at eval time against provided env

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            raise ExprError("禁止访问 dunder 属性")
        if node.attr not in _ALLOWED_ATTRS:
            raise ExprError(f"不允许的属性访问: .{node.attr}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name):
            raise ExprError("只能调用白名单内的具名函数")
        if node.func.id not in SAFE_FUNCS:
            raise ExprError(f"未授权的函数: {node.func.id}")
        self.generic_visit(node)


_cache: Dict[str, ast.Expression] = {}


def compile_expr(src: str) -> ast.Expression:
    if src in _cache:
        return _cache[src]
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise ExprError(f"语法错误: {e.msg}") from e
    _Validator().visit(tree)
    code = compile(tree, "<fx-nodes-expr>", "eval")
    _cache[src] = code  # type: ignore[assignment]
    return code  # type: ignore[return-value]


def evaluate(src: str, variables: Mapping[str, Any] | None = None) -> Any:
    """Evaluate ``src`` with ``variables`` as the local namespace."""
    code = compile_expr(src)
    env: Dict[str, Any] = {"__builtins__": {}}
    env.update(SAFE_CONSTS)
    env.update(SAFE_FUNCS)
    if variables:
        env.update(variables)
    try:
        return eval(code, env, {})  # noqa: S307 - sandboxed: empty builtins + AST whitelist
    except ExprError:
        raise
    except Exception as e:  # surface runtime issues as ExprError
        raise ExprError(f"求值错误: {e}") from e
