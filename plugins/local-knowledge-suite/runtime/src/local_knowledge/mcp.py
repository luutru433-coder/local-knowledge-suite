# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .services import (
    bootstrap_workspace as bootstrap_workspace_core,
    capture_memory as capture_memory_core,
    knowledge_status as knowledge_status_core,
    recall_context as recall_context_core,
)


mcp = FastMCP(
    "Local Knowledge",
    instructions=(
        "Use an absolute initialized project root. Keep skill instructions, project memory, and "
        "citation-backed company claims separate. Company facts require verified source_uri, locator, "
        "and excerpt fields. Search before capture. Never store passwords, tokens, private keys, or "
        "authentication secrets. Memory-only workspaces need no company. Combined and company-only "
        "workspaces require an existing registered company repository."
    ),
    json_response=True,
)

DERIVED_STATE_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
IDEMPOTENT_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
ADDITIVE_WRITE = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)


@mcp.tool(
    title="Initialize local knowledge workspace",
    description=(
        "Idempotently initialize project memory by default, or bind the project to an "
        "existing registered company when combined/company-only is selected."
    ),
    annotations=IDEMPOTENT_WRITE,
    structured_output=True,
)
def bootstrap_workspace(
    root: str,
    company_id: str | None = None,
    profile: Literal["combined", "memory-only", "company-only"] = "memory-only",
    install_mode: Literal["global", "vendored"] = "global",
) -> dict[str, Any]:
    return bootstrap_workspace_core(root, company_id, profile, install_mode)


@mcp.tool(
    title="Knowledge status",
    description=(
        "Inspect runtime compatibility, project memory, and registered company knowledge; "
        "transient local lock state may be created and removed."
    ),
    annotations=DERIVED_STATE_WRITE,
    structured_output=True,
)
def knowledge_status(root: str) -> dict[str, Any]:
    return knowledge_status_core(root)


@mcp.tool(
    title="Recall local context",
    description=(
        "Search skill guidance, project memory, and cited company facts while preserving "
        "authority boundaries; already-captured pending Memory events may be distilled, "
        "and local derived indexes or caches may be rebuilt."
    ),
    annotations=DERIVED_STATE_WRITE,
    structured_output=True,
)
def recall_context(
    query: str,
    root: str,
    limit: int = 8,
    include_skills: bool = True,
    include_memory: bool = True,
    include_company: bool = True,
    include_sensitive_memory: bool = False,
) -> dict[str, Any]:
    return recall_context_core(
        query,
        root,
        limit,
        include_skills,
        include_memory,
        include_company,
        include_sensitive_memory,
    )


@mcp.tool(
    title="Capture durable project memory",
    description="Append, redact, distill, and verify one durable non-secret memory in the selected project only.",
    annotations=ADDITIVE_WRITE,
    structured_output=True,
)
def capture_memory(
    root: str,
    kind: Literal[
        "correction",
        "preference",
        "habit",
        "decision",
        "commitment",
        "entity-fact",
        "project-knowledge",
    ],
    title: str,
    text: str,
    memory_key: str,
    event_id: str | None = None,
    tags: list[str] | None = None,
    importance: float = 0.7,
    pinned: bool = False,
    supersedes: list[str] | None = None,
) -> dict[str, Any]:
    return capture_memory_core(
        root,
        kind,
        title,
        text,
        memory_key,
        event_id,
        tags,
        importance,
        pinned,
        supersedes,
    )


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
