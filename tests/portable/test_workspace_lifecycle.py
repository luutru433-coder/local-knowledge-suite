# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

"""Acceptance tests for Windows lifecycle, manifests, registry, and migration."""

from __future__ import annotations

import json
import os
import re
import subprocess
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="runtime is intentionally Windows-only")


def _strings(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return [item for child in value.values() for item in _strings(child)]
    if isinstance(value, list):
        return [item for child in value for item in _strings(child)]
    return [value] if isinstance(value, str) else []


def _result_identity(runtime: Any, result: Mapping[str, Any], key: str) -> str:
    return str(runtime.value_for_key(result, key))


def test_runtime_artifact_is_self_contained_and_has_no_developer_path() -> None:
    repository = Path(__file__).resolve().parents[2]
    plugin = repository / "plugins" / "local-knowledge-suite"
    runtime = plugin / "runtime"

    assert (runtime / "pyproject.toml").is_file(), "portable runtime needs its own package metadata"
    assert (runtime / "uv.lock").is_file(), "portable runtime dependencies must be locked"
    assert (runtime / "src" / "local_knowledge" / "__init__.py").is_file()
    skill_root = plugin / "skills"
    assert {
        "manage-local-knowledge",
        "memorizer",
        "company-knowledge-base",
    }.issubset({path.parent.name for path in skill_root.glob("*/SKILL.md")})

    forbidden = (
        r"c:\users\alice\project",
        "c:/users/alice/project",
    )
    offenders: list[str] = []
    for path in plugin.rglob("*"):
        relative = path.relative_to(plugin)
        if any(part.casefold() in {".venv", "__pycache__", ".pytest_cache"} for part in relative.parts):
            continue
        if not path.is_file() or path.suffix.casefold() not in {
            ".json",
            ".md",
            ".py",
            ".toml",
            ".yaml",
            ".yml",
        }:
            continue
        text = path.read_text(encoding="utf-8", errors="replace").casefold()
        if any(item in text for item in forbidden):
            offenders.append(str(relative))
    assert offenders == [], f"developer-machine paths remain in portable artifact: {offenders}"


def test_company_and_project_init_write_portable_manifests_and_local_registry(
    portable_world: Mapping[str, Path | str], portable_runtime: Any
) -> None:
    company = Path(portable_world["company"])
    project = Path(portable_world["project_a"])
    localappdata = Path(portable_world["localappdata"])
    company_id = str(portable_world["company_id"])

    company_manifest_path = company / ".local-knowledge" / "company.toml"
    project_manifest_path = project / ".local-knowledge" / "project.toml"
    registry_path = localappdata / "LocalKnowledgeSuite" / "registry.json"
    assert company_manifest_path.is_file()
    assert project_manifest_path.is_file()
    assert registry_path.is_file()
    assert (company / ".git").is_dir()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=company,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()
    assert head
    assert subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=company,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout == ""

    company_manifest = portable_runtime.read_toml(company_manifest_path)
    project_manifest = portable_runtime.read_toml(project_manifest_path)
    assert int(portable_runtime.value_for_key(company_manifest, "schema_version")) >= 1
    assert portable_runtime.value_for_key(company_manifest, "company_id") == company_id
    assert not any(Path(item).is_absolute() for item in _strings(company_manifest))
    assert int(portable_runtime.value_for_key(project_manifest, "schema_version")) >= 1
    assert portable_runtime.value_for_key(project_manifest, "company_id") == company_id
    assert portable_runtime.value_for_key(project_manifest, "profile") == "combined"
    assert portable_runtime.value_for_key(project_manifest, "install_mode") == "global"
    assert str(portable_runtime.value_for_key(project_manifest, "project_id")).strip()

    memory_path = Path(str(portable_runtime.value_for_key(project_manifest, "memory_path")))
    assert not memory_path.is_absolute()
    assert ".memorizer" in memory_path.parts
    assert not any(str(company.resolve()).casefold() in item.casefold() for item in _strings(project_manifest))

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert company_id.casefold() in json.dumps(registry, ensure_ascii=False).casefold()
    registered_paths = [Path(item).resolve() for item in _strings(registry) if Path(item).is_absolute()]
    assert company.resolve() in registered_paths


def test_bootstrap_is_idempotent_and_preserves_unrelated_project_config(
    tmp_path: Path,
    isolated_localappdata: Path,
    portable_runtime: Any,
) -> None:
    company = tmp_path / "Bootstrap Company"
    project = tmp_path / "Bootstrap Project"
    company.mkdir()
    project.mkdir()
    portable_runtime.init_company(company, "bootstrap-company", "Bootstrap Company")
    portable_runtime.register_company(company)

    codex_config = project / ".codex" / "config.toml"
    codex_config.parent.mkdir()
    codex_config.write_text("[features]\nunrelated_setting = true\n", encoding="utf-8")
    first = portable_runtime.bootstrap(project, "bootstrap-company")
    manifest_path = project / ".local-knowledge" / "project.toml"
    first_manifest = manifest_path.read_bytes()
    first_config = codex_config.read_text(encoding="utf-8")

    sentinel = project / ".local-knowledge" / "user-note.txt"
    sentinel.write_text("preserve me", encoding="utf-8")
    second = portable_runtime.bootstrap(project, "bootstrap-company")

    assert manifest_path.read_bytes() == first_manifest
    assert sentinel.read_text(encoding="utf-8") == "preserve me"
    assert "unrelated_setting = true" in codex_config.read_text(encoding="utf-8")
    assert first_config in codex_config.read_text(encoding="utf-8")
    assert _result_identity(portable_runtime, first, "project_id") == _result_identity(
        portable_runtime, second, "project_id"
    )
    assert _result_identity(portable_runtime, first, "company_id") == "bootstrap-company"


def test_bootstrap_parameter_change_is_rejected_or_returns_existing_consistent_state(
    tmp_path: Path,
    isolated_localappdata: Path,
    portable_runtime: Any,
) -> None:
    company = tmp_path / "Immutable Bootstrap Company"
    project = tmp_path / "Immutable Bootstrap Project"
    company.mkdir()
    project.mkdir()
    portable_runtime.init_company(company, "immutable-company", "Immutable Company")
    portable_runtime.register_company(company)
    first = portable_runtime.bootstrap(
        project,
        "immutable-company",
        profile="combined",
        install_mode="global",
    )
    manifest_path = project / ".local-knowledge" / "project.toml"
    original = manifest_path.read_bytes()

    try:
        second = portable_runtime.bootstrap(
            project,
            "immutable-company",
            profile="memory-only",
            install_mode="vendored",
        )
    except Exception as exc:
        assert re.search(r"(?i)(profile|install.mode|already|immutable|different)", str(exc))
    else:
        assert second["project_id"] == first["project_id"]
        assert second["company_id"] == first["company_id"]
        assert second["profile"] == "combined"
        assert second["install_mode"] == "global"
        assert second.get("vendor_required") in {None, False}
        assert not second.get("warning")
    assert manifest_path.read_bytes() == original


def test_vendored_project_records_mode_and_reports_snapshot_requirement(
    tmp_path: Path,
    isolated_localappdata: Path,
    portable_runtime: Any,
) -> None:
    company = tmp_path / "Vendored Company"
    project = tmp_path / "Vendored Project"
    company.mkdir()
    project.mkdir()
    portable_runtime.init_company(company, "vendored-company", "Vendored Company")
    portable_runtime.register_company(company)

    result = portable_runtime.init_project(
        project,
        "vendored-company",
        install_mode="vendored",
    )
    manifest = portable_runtime.read_toml(
        project / ".local-knowledge" / "project.toml"
    )
    assert portable_runtime.value_for_key(manifest, "install_mode") == "vendored"
    snapshot = project / "tools" / "local-knowledge-suite"
    assert snapshot.is_dir() or result.get("vendor_required") is True


def test_status_and_doctor_report_compatibility_and_registered_company(
    portable_world: Mapping[str, Path | str], portable_runtime: Any
) -> None:
    project = Path(portable_world["project_a"])
    company_id = str(portable_world["company_id"])
    status = portable_runtime.status(project)

    assert str(portable_runtime.value_for_key(status, "runtime_version")).strip()
    assert int(portable_runtime.value_for_key(status, "workspace_schema_version")) >= 1
    assert portable_runtime.value_for_key(status, "compatible") is True
    assert portable_runtime.value_for_key(status, "migration_required") is False
    assert portable_runtime.value_for_key(status, "company_id") == company_id
    assert portable_runtime.value_for_key(status, "company_registered") is True
    assert int(status["skills"]["count"]) >= 3

    diagnosis = portable_runtime.doctor(project)
    healthy_fields = [
        value
        for path, value in portable_runtime.flatten_mapping(diagnosis).items()
        if path.rsplit(".", 1)[-1] in {"ok", "healthy", "valid", "compatible"}
        and isinstance(value, bool)
    ]
    assert healthy_fields and any(healthy_fields), diagnosis


def test_migration_dry_run_does_not_write_and_apply_upgrades_schema(
    portable_world: Mapping[str, Path | str], portable_runtime: Any
) -> None:
    project = Path(portable_world["project_a"])
    manifest_path = project / ".local-knowledge" / "project.toml"
    original = manifest_path.read_text(encoding="utf-8")
    legacy, replacements = re.subn(
        r"(?m)^(schema_version\s*=\s*)(?:\d+|\"\d+\")\s*$",
        r"\g<1>0",
        original,
        count=1,
    )
    assert replacements == 1, "project manifest must expose schema_version in TOML"
    manifest_path.write_text(legacy, encoding="utf-8")
    legacy_bytes = manifest_path.read_bytes()

    dry_run = portable_runtime.migrate(project, dry_run=True)
    assert manifest_path.read_bytes() == legacy_bytes
    assert json.dumps(dry_run, ensure_ascii=False), "dry-run must return a migration report"

    applied = portable_runtime.migrate(project, dry_run=False)
    migrated = portable_runtime.read_toml(manifest_path)
    assert int(portable_runtime.value_for_key(migrated, "schema_version")) >= 1
    assert json.dumps(applied, ensure_ascii=False), "apply must return a migration report"
    assert portable_runtime.value_for_key(portable_runtime.status(project), "compatible") is True


def test_target_project_uses_plugin_engine_without_runtime_copies(
    portable_world: Mapping[str, Path | str], portable_runtime: Any
) -> None:
    project = Path(portable_world["project_a"])
    assert not (project / "src" / "ckb").exists()
    assert not (project / "skills" / "memorizer" / "scripts").exists()

    result = portable_runtime.capture(
        project,
        kind="decision",
        title="Portable package manager",
        text="Project Alpha uses pnpm from the plugin runtime.",
        memory_key="portable:package-manager",
        event_id="evt_portable_engine_contract",
        tags=["portable"],
    )
    assert result.get("ok", result.get("accepted", True)) is True
    recalled = portable_runtime.recall(
        project,
        "plugin runtime package manager",
        include_skills=False,
        include_company=False,
    )
    assert "pnpm" in portable_runtime.section_text(recalled, "memory")


def test_importing_cli_from_clean_cwd_creates_no_workspace_state(tmp_path: Path) -> None:
    clean = tmp_path / "Clean CLI Import"
    clean.mkdir()
    runtime_src = (
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "local-knowledge-suite"
        / "runtime"
        / "src"
    )
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        item for item in (str(runtime_src), existing_pythonpath) if item
    )
    completed = subprocess.run(
        [sys.executable, "-c", "import local_knowledge.cli"],
        cwd=clean,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert not (clean / ".ckb").exists()
    assert not (clean / "knowledge").exists()
    assert not (clean / ".memorizer").exists()
    assert not (clean / ".local-knowledge").exists()
