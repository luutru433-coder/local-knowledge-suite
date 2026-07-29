# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

"""Deprecated import bridge for pre-1.0 Local Knowledge Suite callers.

Run through the pinned runtime whenever possible. This bridge is kept for one
release so existing local imports resolve to the self-contained v1 engine; it
never imports code from the target project.
"""

from __future__ import annotations

import sys
from pathlib import Path


_RUNTIME_SOURCE = Path(__file__).resolve().parents[1] / "runtime" / "src"
if str(_RUNTIME_SOURCE) not in sys.path:
    sys.path.insert(0, str(_RUNTIME_SOURCE))

from local_knowledge.errors import LocalKnowledgeError as KnowledgeToolError  # noqa: E402
from local_knowledge.services import (  # noqa: E402
    bootstrap_workspace,
    capture_memory,
    initialize_company_repository,
    knowledge_status,
    recall_context,
    register_company,
    restore_workspace,
)


__all__ = [
    "KnowledgeToolError",
    "bootstrap_workspace",
    "capture_memory",
    "initialize_company_repository",
    "knowledge_status",
    "recall_context",
    "register_company",
    "restore_workspace",
]
