# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def run_cli(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "local_knowledge.memorizer.cli",
            "--root",
            str(root),
            *arguments,
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )


def test_cli_capture_search_status_and_validate(tmp_path: Path) -> None:
    input_path = tmp_path / "capture.json"
    input_path.write_text(
        json.dumps(
            {
                "id": "evt_cli",
                "kind": "preference",
                "title": "Preferred test runner",
                "text": "The user prefers pytest for Python tests.",
                "memory_key": "testing:python-runner",
            }
        ),
        encoding="utf-8",
    )
    captured = run_cli(tmp_path, "capture", "--input", str(input_path))
    assert captured.returncode == 0, captured.stderr
    capture_payload = json.loads(captured.stdout)
    assert capture_payload["distilled"] is True
    assert capture_payload["memory_ids"]

    searched = run_cli(tmp_path, "search", "pytest")
    assert searched.returncode == 0, searched.stderr
    assert json.loads(searched.stdout)["results"][0]["id"] == capture_payload["memory_ids"][0]

    state = run_cli(tmp_path, "status")
    assert json.loads(state.stdout)["pending"] == 0
    validated = run_cli(tmp_path, "validate")
    assert validated.returncode == 0, validated.stderr
    assert json.loads(validated.stdout)["valid"] is True


def test_cli_stdin_capture_supports_workspace_paths_with_spaces(tmp_path: Path) -> None:
    root = tmp_path / "workspace with spaces"
    payload = {
        "id": "evt_cli_stdin",
        "kind": "decision",
        "title": "Workspace path support",
        "text": "The workspace supports paths with spaces.",
        "memory_key": "workspace:path-support",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "local_knowledge.memorizer.cli",
            "--root",
            str(root),
            "capture",
            "--input",
            "-",
        ],
        input=json.dumps(payload),
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    captured = json.loads(result.stdout)
    assert captured["distilled"] is True
    assert run_cli(root, "search", "paths spaces").returncode == 0


def test_cli_invalid_input_has_stable_error_without_traceback(tmp_path: Path) -> None:
    input_path = tmp_path / "invalid.json"
    input_path.write_text('{"kind":"unknown","text":"bad"}', encoding="utf-8")
    result = run_cli(tmp_path, "capture", "--input", str(input_path))
    assert result.returncode == 2
    payload = json.loads(result.stderr)
    assert payload["ok"] is False
    assert "Traceback" not in result.stderr


def test_cli_malformed_types_and_arguments_use_json_errors(tmp_path: Path) -> None:
    input_path = tmp_path / "malformed.json"
    input_path.write_text(
        json.dumps(
            {
                "id": "evt_cli_malformed",
                "kind": "preference",
                "title": "Malformed timestamp",
                "text": "This input must be rejected.",
                "memory_key": "test:malformed",
                "captured_at": 123,
            }
        ),
        encoding="utf-8",
    )
    for result in (
        run_cli(tmp_path, "capture", "--input", str(input_path)),
        run_cli(tmp_path, "search", "query", "--limit", "not-a-number"),
    ):
        assert result.returncode == 2
        payload = json.loads(result.stderr)
        assert payload["ok"] is False
        assert "Traceback" not in result.stderr


def test_cli_invalid_utf8_uses_json_error(tmp_path: Path) -> None:
    input_path = tmp_path / "invalid-utf8.json"
    input_path.write_bytes(b"\xff\xfe\x80")
    result = run_cli(tmp_path, "capture", "--input", str(input_path))
    assert result.returncode == 2
    assert json.loads(result.stderr)["ok"] is False
    assert "Traceback" not in result.stderr


def test_cli_escaped_surrogate_uses_json_error_without_partial_event(tmp_path: Path) -> None:
    input_path = tmp_path / "surrogate.json"
    input_path.write_text(
        '{"id":"evt_cli_surrogate","kind":"decision","title":"\\ud800",'
        '"text":"Reject invalid Unicode.","memory_key":"test:unicode"}',
        encoding="utf-8",
    )
    result = run_cli(tmp_path, "capture", "--input", str(input_path))
    assert result.returncode == 2
    assert json.loads(result.stderr)["ok"] is False
    assert "Traceback" not in result.stderr
    state = run_cli(tmp_path, "status")
    assert state.returncode == 0
    assert json.loads(state.stdout)["events"] == 0


@pytest.mark.skipif(sys.platform != "win32", reason="Windows denies index replacement while SQLite is open")
def test_cli_operational_index_failure_is_json_without_traceback(tmp_path: Path) -> None:
    initialized = run_cli(tmp_path, "init")
    assert initialized.returncode == 0, initialized.stderr
    index_path = tmp_path / ".memorizer" / "index.sqlite3"
    connection = sqlite3.connect(index_path)
    try:
        connection.execute("PRAGMA locking_mode=EXCLUSIVE")
        connection.execute("BEGIN EXCLUSIVE")
        connection.execute("SELECT name FROM sqlite_master").fetchone()
        result = run_cli(tmp_path, "rebuild")
    finally:
        connection.rollback()
        connection.close()
    assert result.returncode == 2
    payload = json.loads(result.stderr)
    assert payload["ok"] is False
    assert "Traceback" not in result.stderr
