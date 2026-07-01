"""Node-RED-like property paths for msg/flow/global context.

Supported examples:

    payload
    topic
    msg.payload
    msg.user.name
    msg.items[0].name
    flow.counter
    Global.settings.seed

This is intentionally small and predictable: dotted names plus integer or
quoted-string brackets.  ``set()`` creates intermediate dict/list containers so
paths like ``payload.items[0].name`` work from an empty message.
"""
from __future__ import annotations

import re
from typing import Any, Tuple


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

    def root_alias(alias: str, root: str):
        if p == alias:
            return root, ""
        if p.startswith(alias + "."):
            return root, p[len(alias) + 1:]
        if p.startswith(alias + "["):
            return root, p[len(alias):]
        return None

    # Accept UI/legacy spellings too: Global.test, Global["test"], G.test.
    for alias, root in (
        ("msg", "msg"), ("Msg", "msg"),
        ("flow", "flow"), ("Flow", "flow"),
        ("global", "global"), ("Global", "global"), ("G", "global"),
    ):
        hit = root_alias(alias, root)
        if hit is not None:
            return hit

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


def _list_index(seq: list, idx: int, *, create: bool = False) -> int:
    if not isinstance(idx, int):
        raise MsgPathError("list index must be an integer")
    if idx < 0:
        idx = len(seq) + idx
    if idx < 0:
        raise MsgPathError("list index out of range")
    if create:
        while len(seq) <= idx:
            seq.append(None)
    elif idx >= len(seq):
        raise IndexError(idx)
    return idx


def _new_container(next_token: Any):
    return [] if isinstance(next_token, int) else {}


def get(path: str, msg: dict, flow: dict | None = None, global_context: dict | None = None, default: Any = None) -> Any:
    root, toks = parse(path)
    cur = _container(root, msg, flow, global_context)
    if not toks:
        return cur
    try:
        for t in toks:
            if isinstance(cur, list):
                cur = cur[_list_index(cur, t)]
            else:
                cur = cur[t]
        return cur
    except Exception:
        return default


def set(path: str, value: Any, msg: dict, flow: dict | None = None, global_context: dict | None = None) -> Any:
    root, toks = parse(path)
    if not toks:
        raise MsgPathError("cannot replace root object")
    cur = _container(root, msg, flow, global_context)
    for i, t in enumerate(toks[:-1]):
        nxt = toks[i + 1]
        if isinstance(cur, list):
            idx = _list_index(cur, t, create=True)
            if cur[idx] is None:
                cur[idx] = _new_container(nxt)
            elif not isinstance(cur[idx], (dict, list)):
                raise MsgPathError(f"cannot descend into non-container at {t!r}")
            cur = cur[idx]
        elif isinstance(cur, dict):
            if t not in cur or cur[t] is None:
                cur[t] = _new_container(nxt)
            elif not isinstance(cur[t], (dict, list)):
                raise MsgPathError(f"cannot descend into non-container at {t!r}")
            cur = cur[t]
        else:
            raise MsgPathError(f"cannot descend into {type(cur).__name__}")

    last = toks[-1]
    if isinstance(cur, list):
        idx = _list_index(cur, last, create=True)
        cur[idx] = value
    elif isinstance(cur, dict):
        cur[last] = value
    else:
        raise MsgPathError(f"cannot set value on {type(cur).__name__}")
    return value


def delete(path: str, msg: dict, flow: dict | None = None, global_context: dict | None = None) -> None:
    root, toks = parse(path)
    if not toks:
        raise MsgPathError("cannot delete root object")
    cur = _container(root, msg, flow, global_context)
    try:
        for t in toks[:-1]:
            if isinstance(cur, list):
                cur = cur[_list_index(cur, t)]
            else:
                cur = cur[t]
        last = toks[-1]
        if isinstance(cur, list) and isinstance(last, int):
            cur.pop(_list_index(cur, last))
        elif isinstance(cur, dict):
            cur.pop(last, None)
    except Exception:
        return


def compact(value: Any, max_len: int = 80) -> str:
    text = repr(value)
    return text if len(text) <= max_len else text[:max_len - 1] + "…"
