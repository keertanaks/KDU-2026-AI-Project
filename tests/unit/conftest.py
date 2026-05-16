"""conftest.py — stub out heavy SDKs so unit tests run without them installed."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Stub anthropic before any agent module is imported.
# Unit tests mock the client explicitly; this just prevents ImportError.
if "anthropic" not in sys.modules:
    sys.modules["anthropic"] = MagicMock()

# Stub langgraph so graph/kitchen_graph.py can be imported without the package.
# Tests that need graph topology mock _build() directly.
for _mod in ("langgraph", "langgraph.graph"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# Stub colormath so mcp_server/color_resolver.py can be imported without the package.
# MagicMock used as the parent package so submodule lookups fall through correctly.
_colormath_pkg = MagicMock()
for _mod in (
    "colormath",
    "colormath.color_conversions",
    "colormath.color_diff",
    "colormath.color_objects",
):
    if _mod not in sys.modules:
        _mock = MagicMock()
        _mock.__spec__ = None
        sys.modules[_mod] = _mock
# Make parent package resolve submodule attribute access
sys.modules["colormath"] = _colormath_pkg
