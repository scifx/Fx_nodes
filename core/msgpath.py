"""Node-RED-like property paths for msg/flow/global context.

Supported examples:

    payload
    topic
    msg.payload
    msg.user.name
    msg.items[0].name
    flow.counter
    global.settings.seed

This is intentionally small and predictable: dotted names plus integer or
quoted-string brackets.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Tuple


class MsgPathError(Exception):
    pass

_TOKEN_RE = re.compile(r"""
    (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | \[(?P<int>-?\d+)\]
  | \[['\"](?P<str>[^'\"]+)['\"]\]
""", re.VERBOSE)


def _split_root(path: str) -> Tuple[str, str]:
    p = (path or "").strip()
    if not p:
        raise MsgPathError("path is empty")
    if p.startswith("msg."):
        return "msg", p[4:]
    if p.startswith("msg["):
        return "msg", p[3:]
    if p == "msg":
        return "msg", ""
    if p.startswith("flow."):
        return "flow", p[5:]
    if p.startswith("flow["):
        return "flow", p[4:]
    if p == "flow":
        return "flow", ""
    if p.startswith("global."):
        return "global", p[7:]
    if p.startswith("global["):
        return "global", p[6:]
    if p == "global":
        return "global", ""
    # Node-RED's UI often lets users say just payload/topic for msg paths.
    return "msg", p


def _tokens(rest: str) -> list[Any]:
    if not rest:
        return []
    out: list[Any] = []
    i = 0
    n = len(rest)
    while i < n:
        if rest[i] == ".":
            i += 1
            continue
        m = _TOKEN_RE.match(rest, i)
        if not m:
            raise MsgPathError(f"invalid path near: {rest[i:]}")
        if m.group("name") is not None:
            out.append(m.group("name"))
        elif m.group("int") is not None:
            out.append(int(m.group("int")))
        else:
            out.append(m.group("str"))
        i = m.end()
    return out


def parse(path: str) -> tuple[str, list[Any]]:
    root, rest = _split_root(path)
    return root, _tokens(rest)


def _container(root: str, msg: dict, flow: dict | None = None, global_context: dict | None = None):
    if root == "msg":
        return msg
    if root == "flow":
        return flow if flow is not None else {}
    if root == "global":
        return global_context if global_context is not None else {}
    raise MsgPathError(f"unknown root: {root}")


def get(path: str, msg: dict, flow: dict | None = None, global_context: dict | None = None, default: Any = None) -> Any:
    root, toks = parse(path)
    cur = _container(root, msg, flow, global_context)
    if not toks:
        return cur
    try:
        for t in toks:
            cur = cur[t]
        return cur
    except Exception:
        return default


def set(path: str, value: Any, msg: dict, flow: dict | None = None, global_context: dict | None = None) -> Any:
    root, toks = parse(path)
    if not toks:
        raise MsgPathError("cannot replace root object")
    cur = _container(root, msg, flow, global_context)
    for t, nxt in zip(toks[:-1], toks[1:]):
        if isinstance(cur, list):
            cur = cur[t]
            continue
        if t not in cur or cur[t] is None:
            cur[t] = [] if isinstance(nxt, int) else {}
        cur = cur[t]
    last = toks[-1]
    cur[last] = value
    return value


def delete(path: str, msg: dict, flow: dict | None = None, global_context: dict | None = None) -> None:
    root, toks = parse(path)
    if not toks:
        raise MsgPathError("cannot delete root object")
    cur = _container(root, msg, flow, global_context)
    try:
        for t in toks[:-1]:
            cur = cur[t]
        if isinstance(cur, list) and isinstance(toks[-1], int):
            cur.pop(toks[-1])
        else:
            cur.pop(toks[-1], None)
    except Exception:
        return


def compact(value: Any, max_len: int = 80) -> str:
    text = repr(value)
    return text if len(text) <= max_len else text[:max_len - 1] + "…"
