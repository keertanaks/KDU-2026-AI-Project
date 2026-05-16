"""conftest.py — stub out anthropic so unit tests run without the SDK installed."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Stub anthropic before any agent module is imported.
# Unit tests mock the client explicitly; this just prevents ImportError.
if "anthropic" not in sys.modules:
    sys.modules["anthropic"] = MagicMock()
