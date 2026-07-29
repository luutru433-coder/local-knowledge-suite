# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

"""Deprecated stdio entry point forwarding to the self-contained v1 MCP."""

from __future__ import annotations

import sys
from pathlib import Path


_RUNTIME_SOURCE = Path(__file__).resolve().parents[1] / "runtime" / "src"
if str(_RUNTIME_SOURCE) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_SOURCE))

from local_knowledge.mcp import main, mcp  # noqa: E402


if __name__ == "__main__":
    main()
