"""Safe resolver for Blender "Copy Full Data Path" strings.

Blender's RMB menu can copy Python-ish paths such as::

    bpy.data.objects["Cube"].location[0]
    bpy.context.scene.render.fps

Fx Nodes stores those paths in Property Get/Set nodes.  We intentionally do
not run arbitrary Python: the AST validator only permits walking from the
``bpy`` root through attributes and constant subscripts.  No calls, imports,
operators, comprehensions, dunder names, etc.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any


class PathError(Exception):
    """Raised when a copied Blender data path is invalid or unsafe."""


_ALLOWED_NODES = (
    ast.Expression, ast.Name, ast.Load, ast.Attribute, ast.Subscript,
    ast.Constant, ast.Slice, ast.Tuple,
)


class _PathValidator(ast.NodeVisitor):
    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, _ALLOWED_NODES):
            raise PathError(f"不允许的路径语法: {type(node).__name__}")
        super().generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id != "bpy":
            raise PathError("完整路径必须从 bpy 开始")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("__"):
            raise PathError("禁止访问 dunder 属性")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not isinstance(node.value, (str, int, type(None))):
            raise PathError("下标只允许字符串、整数或 None")


def _parse(path: str) -> ast.Expression:
    src = (path or "").strip()
    if src.startswith("Python: "):
        src = src[len("Python: "):].strip()
    if not src:
        raise PathError("路径为空：请先在 Blender 属性上执行 Copy Full Data Path")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise PathError(f"路径语法错误: {e.msg}") from e
    _PathValidator().visit(tree)
    return tree


def validate_path(path: str) -> bool:
    _parse(path)
    return True


def _eval_ast(node: ast.AST) -> Any:
    try:
        import bpy  # type: ignore
    except Exception as e:  # pragma: no cover - Blender only
        raise PathError("当前环境没有 bpy，无法解析 Blender 数据路径") from e
    expr = ast.Expression(body=node)
    ast.fix_missing_locations(expr)
    code = compile(expr, "<fx-nodes-data-path>", "eval")
    try:
        return eval(code, {"__builtins__": {}, "bpy": bpy}, {})  # noqa: S307 - AST-whitelisted
    except Exception as e:
        raise PathError(f"路径解析失败: {e}") from e


def resolve_path(path: str) -> Any:
    """Return the current value at a safe Blender full data path."""
    return _eval_ast(_parse(path).body)


@dataclass(frozen=True)
class PathTarget:
    parent: Any
    kind: str          # "attr" or "item"
    key: Any

    def get(self) -> Any:
        return getattr(self.parent, self.key) if self.kind == "attr" else self.parent[self.key]

    def set(self, value: Any) -> None:
        if self.kind == "attr":
            setattr(self.parent, self.key, value)
        else:
            self.parent[self.key] = value


def _slice_value(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(_slice_value(e) for e in node.elts)
    if isinstance(node, ast.Slice):
        lower = _slice_value(node.lower) if node.lower else None
        upper = _slice_value(node.upper) if node.upper else None
        step = _slice_value(node.step) if node.step else None
        return slice(lower, upper, step)
    raise PathError(f"不支持的下标类型: {type(node).__name__}")


def resolve_target(path: str) -> PathTarget:
    """Resolve a path to its assignable parent + attribute/item key."""
    body = _parse(path).body
    if isinstance(body, ast.Attribute):
        parent = _eval_ast(body.value)
        return PathTarget(parent=parent, kind="attr", key=body.attr)
    if isinstance(body, ast.Subscript):
        parent = _eval_ast(body.value)
        return PathTarget(parent=parent, kind="item", key=_slice_value(body.slice))
    raise PathError("路径不是可设置目标：末尾必须是 .属性 或 [下标]")


def get_path(path: str) -> Any:
    return resolve_path(path)


def set_path(path: str, value: Any) -> Any:
    target = resolve_target(path)
    target.set(value)
    return value


def compact_path_label(path: str, max_len: int = 42) -> str:
    """Short label suitable for nodes and reports."""
    text = (path or "").strip()
    if len(text) <= max_len:
        return text
    return "…" + text[-(max_len - 1):]
