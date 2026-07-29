# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

"""Static and real FastMCP schema checks for the portable fast path."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="runtime is intentionally Windows-only")


PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "local-knowledge-suite"


def test_mcp_configuration_uses_plugin_runtime_without_workspace_allowlist() -> None:
    configuration = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = configuration["mcpServers"]["local-knowledge"]
    serialized = json.dumps(server, ensure_ascii=False).casefold()

    assert server["command"].casefold() == "cmd.exe"
    assert server.get("cwd") == ".", "the system launcher needs a trusted plugin cwd"
    assert server["args"][:3] == ["/d", "/s", "/c"]
    command_line = server["args"][3].casefold()
    assert "%systemroot%\\system32\\windowspowershell\\v1.0\\powershell.exe" in command_line
    assert ".\\scripts\\invoke-localknowledge.ps1" in command_line
    assert "-tool mcp" in command_line
    assert "c:\\users\\alice\\project" not in serialized
    assert "c:/users/alice/project" not in serialized
    assert "LOCAL_KNOWLEDGE_ALLOWED_ROOTS" not in server.get("env", {})


def _load_real_server() -> Any:
    pytest.importorskip(
        "mcp",
        reason=(
            "real schema check requires mcp; run with "
            "`uv run --no-project --with 'mcp>=1.27,<2' --with pytest python -m pytest "
            "tests/portable/test_mcp_schema.py`"
        ),
    )
    runtime_src = str(PLUGIN_ROOT / "runtime" / "src")
    if runtime_src not in sys.path:
        sys.path.insert(0, runtime_src)
    module = importlib.import_module("local_knowledge.mcp")
    server = getattr(module, "mcp", None) or getattr(module, "server", None)
    assert server is not None, "local_knowledge.mcp must export its FastMCP instance as `mcp`"
    return server


def _annotation(tool: Any, key: str) -> bool | None:
    annotations = getattr(tool, "annotations", None)
    if annotations is None:
        return None
    if hasattr(annotations, "model_dump"):
        return annotations.model_dump(by_alias=True).get(key)
    return getattr(annotations, key, None)


def test_real_mcp_server_exposes_only_portable_fast_path_with_stable_schemas() -> None:
    server = _load_real_server()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
    assert set(tools) == {
        "bootstrap_workspace",
        "knowledge_status",
        "recall_context",
        "capture_memory",
    }

    expected_required = {
        "bootstrap_workspace": {"root"},
        "knowledge_status": {"root"},
        "recall_context": {"query", "root"},
        "capture_memory": {"root", "kind", "title", "text", "memory_key"},
    }
    for name, required in expected_required.items():
        schema = tools[name].parameters
        assert schema.get("additionalProperties") in {None, False}
        assert required.issubset(set(schema.get("required", [])))
        assert required.issubset(set(schema.get("properties", {})))
        assert _annotation(tools[name], "openWorldHint") is False

    bootstrap_schema = tools["bootstrap_workspace"].parameters
    assert "company_id" in bootstrap_schema["properties"]
    assert "company_id" not in bootstrap_schema.get("required", [])
    assert bootstrap_schema["properties"]["profile"]["default"] == "memory-only"

    assert _annotation(tools["knowledge_status"], "readOnlyHint") is False
    assert _annotation(tools["recall_context"], "readOnlyHint") is False
    assert _annotation(tools["knowledge_status"], "idempotentHint") is True
    assert _annotation(tools["recall_context"], "idempotentHint") is True
    assert _annotation(tools["knowledge_status"], "destructiveHint") in {None, False}
    assert _annotation(tools["recall_context"], "destructiveHint") in {None, False}
    assert _annotation(tools["bootstrap_workspace"], "readOnlyHint") is False
    assert _annotation(tools["bootstrap_workspace"], "destructiveHint") is False
    assert _annotation(tools["bootstrap_workspace"], "idempotentHint") is True
    assert _annotation(tools["capture_memory"], "readOnlyHint") is False
    assert _annotation(tools["capture_memory"], "destructiveHint") is False
    assert _annotation(tools["capture_memory"], "idempotentHint") is False
