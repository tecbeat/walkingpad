"""Shared test fixtures.

Loads the ``walkingpad`` connection layer without going through the
``custom_components.walkingpad`` package (which would drag in Home Assistant
core imports). This lets us run the connection tests as plain pytest without
a full HA test harness.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_COMPONENT_DIR = (
    Path(__file__).resolve().parents[1] / "custom_components" / "walkingpad"
)


def _load(module_name: str, filename: str) -> object:
    spec = importlib.util.spec_from_file_location(
        module_name, _COMPONENT_DIR / filename
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Load protocol first because walkingpad.py imports from it as a relative
# import. Rewriting that import to point at our detached protocol module is
# handled by stubbing sys.modules before executing walkingpad.py.
_protocol = _load("walkingpad_protocol", "protocol.py")

# Create a synthetic package so ``from .protocol import ...`` inside
# walkingpad.py resolves to our loaded protocol module.
import types  # noqa: E402

_pkg = types.ModuleType("wp_pkg")
_pkg.__path__ = [str(_COMPONENT_DIR)]  # type: ignore[attr-defined]
sys.modules["wp_pkg"] = _pkg
sys.modules["wp_pkg.protocol"] = _protocol
sys.modules["wp_pkg.const"] = _load("wp_pkg.const", "const.py")


def _load_walkingpad_module() -> object:
    """Load walkingpad.py as ``wp_pkg.walkingpad`` so relative imports resolve."""
    spec = importlib.util.spec_from_file_location(
        "wp_pkg.walkingpad", _COMPONENT_DIR / "walkingpad.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["wp_pkg.walkingpad"] = module
    spec.loader.exec_module(module)
    return module


_walkingpad = _load_walkingpad_module()
