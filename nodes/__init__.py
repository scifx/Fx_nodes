"""Automatic node-module loader for Fx Nodes.

Drop Python files anywhere under this ``nodes`` package (including
``nodes/custom``).  Any class decorated with ``@register_node`` is imported and
registered automatically.  Folder paths become add-menu paths, e.g.::

    nodes/property/set_property.py  ->  Property / Set Property
    nodes/custom/demo/echo.py       ->  Custom / Demo / Echo
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

_LOADED: set[str] = set()
_SKIP_MODULE_NAMES = {"provider"}


def _iter_modules():
    root = Path(__file__).resolve().parent
    prefix = __name__ + "."
    modules = []
    for info in pkgutil.walk_packages([str(root)], prefix):
        name = info.name.rsplit('.', 1)[-1]
        if name.startswith('_') or name in _SKIP_MODULE_NAMES:
            continue
        if info.ispkg:
            continue
        modules.append(info.name)
    return sorted(modules, key=_module_sort_key)


def _module_sort_key(module_name: str):
    # Keep the default top-level menu close to the UI order while still allowing
    # custom folders/files to sort naturally without touching UI code.
    order = {
        "trigger": 0, "property": 1, "logic": 2, "script": 3,
        "data": 4, "debug": 5, "ai": 6, "utility": 7, "custom": 50,
    }
    parts = module_name.split('.')
    try:
        i = parts.index('nodes')
        top = parts[i + 1]
    except Exception:
        top = ""
    return (order.get(top, 100), module_name)


def load_nodes(*, force_reload: bool = False) -> list[str]:
    """Import all node modules recursively and return imported module names."""
    imported: list[str] = []
    for mod_name in _iter_modules():
        if not force_reload and mod_name in _LOADED:
            continue
        mod = importlib.import_module(mod_name)
        if force_reload:
            mod = importlib.reload(mod)
        _LOADED.add(mod_name)
        imported.append(mod_name)
    return imported


# Import on package import so add-on registration and tests see the registry.
load_nodes()
