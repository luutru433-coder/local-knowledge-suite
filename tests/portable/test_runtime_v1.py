# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

"""Version 1 workspace, migration, and portable memory snapshot contracts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    os.name != "nt",
    reason="runtime is intentionally Windows-only",
)

RUNTIME_SRC = (
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "local-knowledge-suite"
    / "runtime"
    / "src"
)
if str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))

from local_knowledge import WORKSPACE_SCHEMA_VERSION, __version__  # noqa: E402
from local_knowledge.ckb.config import Settings  # noqa: E402
from local_knowledge.ckb.db import Database  # noqa: E402
from local_knowledge.ckb import cli as ckb_cli  # noqa: E402
from local_knowledge.ckb.gitops import GitOperationError  # noqa: E402
from local_knowledge.cli import main as local_knowledge_cli  # noqa: E402
from local_knowledge.doctor import doctor_workspace  # noqa: E402
from local_knowledge.errors import (  # noqa: E402
    CompatibilityError,
    ManifestError,
    RegistryError,
    SnapshotError,
)
from local_knowledge.manifests import ProjectManifest  # noqa: E402
from local_knowledge import memory_snapshot as memory_snapshot_module  # noqa: E402
from local_knowledge.memory_snapshot import (  # noqa: E402
    export_memory_snapshot,
    import_memory_snapshot,
    inspect_memory_snapshot,
)
from local_knowledge.memorizer import core as memory_core  # noqa: E402
from local_knowledge.migrations import migrate_workspace  # noqa: E402
from local_knowledge.registry import CompanyRegistry  # noqa: E402
from local_knowledge.services import (  # noqa: E402
    bootstrap_workspace,
    capture_memory,
    initialize_company_repository,
    knowledge_status,
    recall_context,
    register_company,
    restore_workspace,
)


def _memory_project(tmp_path: Path, name: str = "project") -> Path:
    project = tmp_path / name
    project.mkdir()
    bootstrap_workspace(str(project.resolve()))
    return project


def _capture(
    project: Path,
    *,
    event_id: str,
    title: str,
    text: str,
    privacy: str = "private",
) -> str:
    result = memory_core.capture(
        project,
        {
            "id": event_id,
            "kind": "decision",
            "title": title,
            "text": text,
            "memory_key": f"test:{event_id}",
            "privacy": privacy,
        },
        defer=False,
    )
    return str(result["memory_ids"][0])


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _write_snapshot_manifest(path: Path, manifest: dict[str, object]) -> None:
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _refresh_snapshot_fingerprint(manifest: dict[str, object]) -> None:
    unsigned = {
        key: value
        for key, value in manifest.items()
        if key != "content_fingerprint"
    }
    canonical = (
        json.dumps(unsigned, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    manifest["content_fingerprint"] = hashlib.sha256(canonical).hexdigest()


def test_runtime_v1_defaults_to_company_free_memory_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = _memory_project(tmp_path)
    manifest = ProjectManifest.load(project)
    assert __version__ == "1.0.0"
    assert WORKSPACE_SCHEMA_VERSION == 2
    assert manifest.schema_version == 2
    assert manifest.profile == "memory-only"
    assert manifest.company_id is None
    assert "company_id" not in (
        project / ".local-knowledge" / "project.toml"
    ).read_text(encoding="utf-8")
    status = knowledge_status(str(project.resolve()))
    assert status["company_id"] is None
    assert status["company_registered"] is False
    assert status["company"]["enabled"] is False
    assert status["memory"]["available"] is True
    assert Settings.load(project).crawler_user_agent == "LocalKnowledgeSuite/1.0"


@pytest.mark.parametrize("profile", ["combined", "company-only"])
def test_company_profiles_require_company_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: str,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = tmp_path / profile
    project.mkdir()
    with pytest.raises(ValueError, match="requires --company"):
        bootstrap_workspace(str(project.resolve()), profile=profile)
    assert not (project / ".local-knowledge" / "project.toml").exists()


def test_company_access_requires_explicit_machine_local_project_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "authorized-company"
    initialize_company_repository(
        company,
        "Authorized Company",
        "authorized-company",
    )
    forged = tmp_path / "forged-project"
    manifest_path = forged / ".local-knowledge" / "project.toml"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        "\n".join(
            (
                "schema_version = 2",
                'project_id = "project-forged-company-access"',
                'company_id = "authorized-company"',
                'profile = "combined"',
                'install_mode = "global"',
                'memory_path = ".memorizer"',
                "",
            )
        ),
        encoding="utf-8",
    )
    registry = CompanyRegistry()
    assert registry.list_projects() == {}

    guarded_calls = (
        lambda: knowledge_status(str(forged.resolve())),
        lambda: recall_context(
            "confidential company evidence",
            str(forged.resolve()),
            include_skills=False,
            include_memory=False,
            include_company=True,
        ),
        lambda: capture_memory(
            root=str(forged.resolve()),
            kind="decision",
            title="Unauthorized capture",
            text="This must not pass the company authorization boundary.",
            memory_key="authorization:blocked",
            event_id="evt_unauthorized_company_project",
        ),
    )
    for guarded_call in guarded_calls:
        with pytest.raises(RegistryError, match="not locally authorized"):
            guarded_call()
    assert registry.list_projects() == {}

    restored = restore_workspace(str(forged.resolve()))
    assert restored["company_id"] == "authorized-company"
    authorization = registry.list_projects()["project-forged-company-access"]
    assert Path(authorization["root"]) == forged.resolve()
    assert authorization["company_id"] == "authorized-company"
    assert knowledge_status(str(forged.resolve()))["company_registered"] is True


def test_moved_company_project_requires_restore_and_rebinds_exact_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "move-company"
    original = tmp_path / "original-project"
    moved = tmp_path / "moved-project"
    original.mkdir()
    initialize_company_repository(company, "Move Company", "move-company")
    initialized = bootstrap_workspace(
        str(original.resolve()),
        "move-company",
        profile="combined",
    )
    project_id = initialized["project_id"]
    shutil.copytree(original, moved)

    with pytest.raises(RegistryError, match="authorized at"):
        knowledge_status(str(moved.resolve()))
    with pytest.raises(RegistryError, match="run `local-knowledge restore"):
        bootstrap_workspace(
            str(moved.resolve()),
            "move-company",
            profile="combined",
        )

    restored = restore_workspace(str(moved.resolve()))
    assert restored["project_id"] == project_id
    assert knowledge_status(str(moved.resolve()))["company_registered"] is True
    with pytest.raises(RegistryError, match="authorized at"):
        knowledge_status(str(original.resolve()))
    authorization = CompanyRegistry().list_projects()[project_id]
    assert Path(authorization["root"]) == moved.resolve()
    assert authorization["company_id"] == "move-company"


def test_schema1_memory_only_migrates_without_company_registration_and_keeps_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = tmp_path / "legacy"
    manifest_path = project / ".local-knowledge" / "project.toml"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        "\n".join(
            (
                "schema_version = 1",
                'project_id = "project-legacy-memory"',
                'company_id = "legacy-company"',
                'profile = "memory-only"',
                'install_mode = "global"',
                'memory_path = ".memorizer"',
                "",
            )
        ),
        encoding="utf-8",
    )
    memory_core.init_vault(project)

    planned = migrate_workspace(str(project.resolve()), dry_run=True)
    assert planned["actions"] == [
        {"store": "project-manifest", "from": 1, "to": 2}
    ]
    applied = migrate_workspace(str(project.resolve()), dry_run=False)
    assert applied["applied"] is True
    migrated = ProjectManifest.load(project)
    assert migrated.schema_version == 2
    assert migrated.company_id == "legacy-company"
    assert any(
        Path(path).name == "project.toml" and Path(path).is_file()
        for path in applied["backups"]
    )
    noop = migrate_workspace(str(project.resolve()), dry_run=False)
    assert noop["applied"] is False
    assert noop["noop"] is True
    assert noop["actions"] == []
    assert noop["backups"] == []


def test_schema1_project_allows_reads_and_migration_but_blocks_normal_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = tmp_path / "legacy-write-guard"
    manifest_path = project / ".local-knowledge" / "project.toml"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        "\n".join(
            (
                "schema_version = 1",
                'project_id = "project-legacy-write-guard"',
                'company_id = "legacy-company"',
                'profile = "memory-only"',
                'install_mode = "global"',
                'memory_path = ".memorizer"',
                "",
            )
        ),
        encoding="utf-8",
    )
    memory_core.init_vault(project)
    deferred = memory_core.capture(
        project,
        {
            "id": "evt_blocked_legacy_recall",
            "kind": "decision",
            "title": "Deferred legacy recall",
            "text": "This event must remain pending until migration completes.",
            "memory_key": "migration:blocked-recall",
            "privacy": "private",
        },
        defer=True,
    )
    assert deferred["distilled"] is False
    assert knowledge_status(str(project.resolve()))["migration_required"] is True
    before = memory_core.status(project)
    assert before["pending"] == 1
    before_bytes = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }

    with pytest.raises(CompatibilityError, match="migration"):
        bootstrap_workspace(str(project.resolve()))
    with pytest.raises(CompatibilityError, match="migration"):
        restore_workspace(str(project.resolve()))
    with pytest.raises(CompatibilityError, match="migration"):
        capture_memory(
            root=str(project.resolve()),
            kind="decision",
            title="Blocked legacy write",
            text="This event must not be recorded before migration.",
            memory_key="migration:blocked-write",
            event_id="evt_blocked_legacy_write",
        )
    with pytest.raises(CompatibilityError, match="migration"):
        import_memory_snapshot(
            str(project.resolve()),
            str(project / "missing-snapshot"),
        )
    with pytest.raises(CompatibilityError, match="migration"):
        recall_context(
            "deferred legacy recall",
            str(project.resolve()),
            include_skills=False,
            include_memory=True,
            include_company=False,
        )
    assert memory_core.status(project) == before
    after_bytes = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    assert after_bytes == before_bytes
    assert "schema_version = 1" in manifest_path.read_text(encoding="utf-8")

    migrate_workspace(str(project.resolve()), dry_run=False)
    captured = capture_memory(
        root=str(project.resolve()),
        kind="decision",
        title="Allowed migrated write",
        text="This event is recorded after migration.",
        memory_key="migration:allowed-write",
        event_id="evt_allowed_migrated_write",
    )
    assert captured["accepted"] is True


def test_schema1_company_blocks_delegated_mutations_before_database_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "legacy-company"
    initialized = initialize_company_repository(
        company,
        "Legacy Guard Company",
        "legacy-guard-company",
    )
    manifest_path = company / ".local-knowledge" / "company.toml"
    manifest_path.write_text(
        manifest_path.read_text(encoding="utf-8").replace(
            "schema_version = 2",
            "schema_version = 1",
        ),
        encoding="utf-8",
    )
    database = Database(Path(initialized["database"]))
    with database.connect() as connection:
        before = int(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0])
    source = company / ".local-sources" / "blocked.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("This source must not be registered yet.", encoding="utf-8")

    result = local_knowledge_cli(
        [
            "company",
            "source-add",
            "--company",
            "legacy-guard-company",
            "file",
            str(source),
        ]
    )
    assert result == 2
    error = json.loads(capsys.readouterr().err)
    assert "migration" in error["error"].casefold()
    with database.connect() as connection:
        assert int(connection.execute("SELECT COUNT(*) FROM sources").fetchone()[0]) == before
    with pytest.raises(CompatibilityError, match="migration"):
        ckb_cli.main(
            [
                "--root",
                str(company),
                "source-add",
                "file",
                str(source),
            ]
        )


def test_tracked_project_memory_is_rejected_without_local_state_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = _memory_project(tmp_path, "tracked-memory-project")
    _capture(
        project,
        event_id="evt_tracked_memory",
        title="Trusted local memory",
        text="This memory must remain local and untracked.",
    )
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "add",
            "-f",
            "--",
            ".gitignore",
            ".local-knowledge/project.toml",
            ".memorizer",
        ],
        cwd=project,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Security Test",
            "-c",
            "user.email=security-test@localhost",
            "commit",
            "-m",
            "test: force-track project memory",
        ],
        cwd=project,
        check=True,
        capture_output=True,
    )
    before = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for controlled in (
            project / ".memorizer",
            project / ".local-knowledge",
        )
        for path in controlled.rglob("*")
        if path.is_file()
    }

    guarded_calls = (
        lambda: knowledge_status(str(project.resolve())),
        lambda: recall_context(
            "trusted local memory",
            str(project.resolve()),
            include_skills=False,
            include_company=False,
        ),
        lambda: capture_memory(
            root=str(project.resolve()),
            kind="decision",
            title="Rejected tracked memory",
            text="This write must be rejected.",
            memory_key="tracked-memory:rejected",
            event_id="evt_rejected_tracked_memory",
        ),
        lambda: bootstrap_workspace(str(project.resolve())),
    )
    for guarded_call in guarded_calls:
        with pytest.raises(GitOperationError, match=r"\.memorizer"):
            guarded_call()

    after = {
        path.relative_to(project).as_posix(): path.read_bytes()
        for controlled in (
            project / ".memorizer",
            project / ".local-knowledge",
        )
        for path in controlled.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_company_registration_rejects_tracked_database_before_settings_or_registry_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "tracked-company-state"
    initialize_company_repository(
        company,
        "Tracked Company State",
        "tracked-company-state",
    )
    attacker_state = company / ".ckb" / "attacker-state.sqlite3"
    attacker_state.write_bytes(b"attacker-controlled database")
    subprocess.run(
        ["git", "add", "-f", "--", ".ckb/attacker-state.sqlite3"],
        cwd=company,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Security Test",
            "-c",
            "user.email=security-test@localhost",
            "commit",
            "-m",
            "test: force-track company state",
        ],
        cwd=company,
        check=True,
        capture_output=True,
    )
    before = {
        path.relative_to(company).as_posix(): path.read_bytes()
        for path in (company / ".ckb").rglob("*")
        if path.is_file()
    }
    registry = CompanyRegistry(tmp_path / "fresh-machine" / "registry.json")

    def settings_must_not_load(*args: object, **kwargs: object) -> None:
        raise AssertionError("registration reached Settings before Git preflight")

    monkeypatch.setattr(Settings, "for_company", settings_must_not_load)
    with pytest.raises(GitOperationError, match=r"\.ckb/attacker-state"):
        register_company(company, registry=registry)

    after = {
        path.relative_to(company).as_posix(): path.read_bytes()
        for path in (company / ".ckb").rglob("*")
        if path.is_file()
    }
    assert after == before
    assert registry.list() == {}


@pytest.mark.parametrize("memory_path", ["", ".", "..", "memory"])
def test_project_manifest_rejects_unsafe_or_noncanonical_memory_path(
    tmp_path: Path,
    memory_path: str,
) -> None:
    project = tmp_path / memory_path.replace(".", "dot")
    manifest_path = project / ".local-knowledge" / "project.toml"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        "\n".join(
            (
                "schema_version = 2",
                'project_id = "project-invalid-memory-path"',
                'profile = "memory-only"',
                'install_mode = "global"',
                f'memory_path = {json.dumps(memory_path)}',
                "",
            )
        ),
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="exactly '.memorizer'"):
        ProjectManifest.load(project)


def test_snapshot_is_deterministic_text_only_and_sensitive_safe_by_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = _memory_project(tmp_path)
    _capture(
        project,
        event_id="evt_public_decision",
        title="Public package choice",
        text="Use pnpm for deterministic frontend installs.",
    )
    _capture(
        project,
        event_id="evt_sensitive_decision",
        title="Sensitive acquisition target",
        text="The confidential acquisition codename is Firefly.",
        privacy="sensitive",
    )

    first = project / ".local-knowledge" / "snapshot-one"
    second = project / ".local-knowledge" / "snapshot-two"
    first_result = export_memory_snapshot(
        str(project.resolve()),
        str(first),
    )
    second_result = export_memory_snapshot(
        str(project.resolve()),
        str(second),
    )
    assert first_result["content_fingerprint"] == second_result["content_fingerprint"]
    assert _tree_bytes(first) == _tree_bytes(second)
    exported_paths = set(_tree_bytes(first))
    assert "snapshot.json" in exported_paths
    assert "memory/config.json" in exported_paths
    assert any(path.startswith("memory/notes/") for path in exported_paths)
    assert not any(
        forbidden in path.casefold()
        for path in exported_paths
        for forbidden in ("index.sqlite", "memory.md", "entities/", "daily/", ".lock")
    )
    serialized = b"\n".join(_tree_bytes(first).values())
    assert b"Firefly" not in serialized
    inspected = inspect_memory_snapshot(
        first,
        expected_project_id=ProjectManifest.load(project).project_id,
    )
    assert inspected["valid"] is True
    assert inspected["item_count"] == 1
    assert inspected["includes_sensitive"] is False
    assert inspected["excluded_sensitive_count"] == 1


def test_snapshot_requires_explicit_sensitive_and_public_acknowledgements(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = _memory_project(tmp_path)
    _capture(
        project,
        event_id="evt_sensitive_export",
        title="Sensitive vendor",
        text="The private vendor codename is Aurora.",
        privacy="sensitive",
    )
    with pytest.raises(SnapshotError, match="acknowledge-sensitive"):
        export_memory_snapshot(
            str(project.resolve()),
            str(project / "sensitive-denied"),
            include_sensitive=True,
        )
    with pytest.raises(SnapshotError, match="allow-public"):
        export_memory_snapshot(
            str(project.resolve()),
            str(project / "public-denied"),
            git_visibility="public",
        )

    sensitive = project / "sensitive-approved"
    result = export_memory_snapshot(
        str(project.resolve()),
        str(sensitive),
        include_sensitive=True,
        acknowledge_sensitive=True,
    )
    assert result["includes_sensitive"] is True
    assert b"Aurora" in b"\n".join(_tree_bytes(sensitive).values())

    public = project / "public-approved"
    result = export_memory_snapshot(
        str(project.resolve()),
        str(public),
        git_visibility="public",
        allow_public=True,
    )
    assert result["git_visibility"] == "public"


@pytest.mark.parametrize(
    ("field", "tampered"),
    [
        ("project_id", "project-tampered-snapshot"),
        ("includes_sensitive", True),
        ("item_count", 2),
        ("excluded_sensitive_count", 9),
        ("source_updated_at", "2020-01-01T00:00:00Z"),
    ],
)
def test_snapshot_fingerprint_binds_identity_metadata_and_file_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    tampered: object,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = _memory_project(tmp_path)
    _capture(
        project,
        event_id="evt_bound_snapshot_manifest",
        title="Bound snapshot manifest",
        text="Every canonical snapshot manifest field is integrity-bound.",
    )
    snapshot = project / ".local-knowledge" / "bound-snapshot"
    export_memory_snapshot(str(project.resolve()), str(snapshot))
    manifest_path = snapshot / "snapshot.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = tampered
    _write_snapshot_manifest(manifest_path, manifest)

    inspected = inspect_memory_snapshot(
        snapshot,
        expected_project_id=ProjectManifest.load(project).project_id,
    )

    assert inspected["valid"] is False
    assert "fingerprint" in inspected["error"]


@pytest.mark.parametrize(
    ("field", "tampered", "message"),
    [
        ("includes_sensitive", 1, "boolean"),
        ("item_count", False, "non-negative integer"),
        ("item_count", -1, "non-negative integer"),
        ("excluded_sensitive_count", True, "non-negative integer"),
        ("excluded_sensitive_count", -1, "non-negative integer"),
        ("source_updated_at", 123, "ISO-8601 string or null"),
    ],
)
def test_snapshot_metadata_rejects_coercible_and_out_of_range_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    tampered: object,
    message: str,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = _memory_project(tmp_path)
    snapshot = project / ".local-knowledge" / "strict-metadata"
    export_memory_snapshot(str(project.resolve()), str(snapshot))
    manifest_path = snapshot / "snapshot.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[field] = tampered
    _refresh_snapshot_fingerprint(manifest)
    _write_snapshot_manifest(manifest_path, manifest)

    inspected = inspect_memory_snapshot(snapshot)

    assert inspected["valid"] is False
    assert message in inspected["error"]


def test_snapshot_fingerprint_binds_rehashed_file_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = _memory_project(tmp_path)
    _capture(
        project,
        event_id="evt_file_entry_fingerprint",
        title="File entry fingerprint",
        text="The canonical file entry is part of the manifest fingerprint.",
    )
    snapshot = project / ".local-knowledge" / "file-entry-fingerprint"
    export_memory_snapshot(str(project.resolve()), str(snapshot))
    note_path = next((snapshot / "memory" / "notes").glob("*.md"))
    note_path.write_text(
        note_path.read_text(encoding="utf-8")
        + "\nA modified but still parseable note body.\n",
        encoding="utf-8",
        newline="\n",
    )
    note_bytes = note_path.read_bytes()
    manifest_path = snapshot / "snapshot.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative = note_path.relative_to(snapshot).as_posix()
    entry = next(
        item
        for item in manifest["files"]
        if item["path"] == relative
    )
    entry["sha256"] = hashlib.sha256(note_bytes).hexdigest()
    entry["bytes"] = len(note_bytes)
    _write_snapshot_manifest(manifest_path, manifest)

    inspected = inspect_memory_snapshot(snapshot)

    assert inspected["valid"] is False
    assert "fingerprint" in inspected["error"]


def test_snapshot_rejects_hidden_sensitive_note_even_after_checksums_are_recomputed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = _memory_project(tmp_path)
    _capture(
        project,
        event_id="evt_private_snapshot_note",
        title="Private snapshot note",
        text="This note starts with private classification.",
    )
    snapshot = project / ".local-knowledge" / "sensitive-mismatch"
    export_memory_snapshot(str(project.resolve()), str(snapshot))
    note_path = next((snapshot / "memory" / "notes").glob("*.md"))
    note_text = note_path.read_text(encoding="utf-8")
    assert 'privacy: "private"' in note_text
    note_path.write_text(
        note_text.replace('privacy: "private"', 'privacy: "sensitive"', 1),
        encoding="utf-8",
        newline="\n",
    )
    manifest_path = snapshot / "snapshot.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative = note_path.relative_to(snapshot).as_posix()
    note_bytes = note_path.read_bytes()
    entry = next(
        item
        for item in manifest["files"]
        if item["path"] == relative
    )
    entry["sha256"] = hashlib.sha256(note_bytes).hexdigest()
    entry["bytes"] = len(note_bytes)
    _refresh_snapshot_fingerprint(manifest)
    _write_snapshot_manifest(manifest_path, manifest)

    inspected = inspect_memory_snapshot(snapshot)

    assert inspected["valid"] is False
    assert "includes_sensitive does not match its parsed notes" in inspected["error"]


def test_snapshot_import_guards_project_id_empty_vault_and_replace_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    source = _memory_project(tmp_path, "source")
    _capture(
        source,
        event_id="evt_snapshot_source",
        title="Snapshot source",
        text="The portable project uses deterministic snapshots.",
    )
    snapshot = source / ".local-knowledge" / "memory-snapshot"
    export_memory_snapshot(str(source.resolve()), str(snapshot))
    source_status = knowledge_status(str(source.resolve()))
    assert source_status["memory_snapshot"]["valid"] is True
    assert source_status["memory_snapshot"]["freshness"] == "current"
    source_doctor = doctor_workspace(str(source.resolve()))
    snapshot_check = next(
        check
        for check in source_doctor["checks"]
        if check["name"] == "memory-snapshot"
    )
    assert snapshot_check["ok"] is True

    target = tmp_path / "clone"
    (target / ".local-knowledge").mkdir(parents=True)
    shutil.copy2(
        source / ".local-knowledge" / "project.toml",
        target / ".local-knowledge" / "project.toml",
    )
    imported = import_memory_snapshot(
        str(target.resolve()),
        str(snapshot),
    )
    assert imported["imported"] == 1
    assert imported["backup"] is None
    assert memory_core.validate_vault(target)["valid"] is True
    assert memory_core.search(target, "deterministic snapshots")["results"]

    with pytest.raises(SnapshotError, match="not empty"):
        import_memory_snapshot(str(target.resolve()), str(snapshot))
    replaced = import_memory_snapshot(
        str(target.resolve()),
        str(snapshot),
        replace=True,
    )
    assert replaced["backup"] is not None
    assert Path(replaced["backup"]).is_dir()

    other = _memory_project(tmp_path, "other")
    with pytest.raises(SnapshotError, match="project_id"):
        import_memory_snapshot(str(other.resolve()), str(snapshot))


def test_snapshot_import_rejects_source_mutation_during_staging_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    source = _memory_project(tmp_path, "race-source")
    _capture(
        source,
        event_id="evt_snapshot_copy_race",
        title="Snapshot copy race",
        text="The import must bind the bytes copied into staging.",
    )
    snapshot = source / ".local-knowledge" / "race-snapshot"
    export_memory_snapshot(str(source.resolve()), str(snapshot))
    target = tmp_path / "race-target"
    (target / ".local-knowledge").mkdir(parents=True)
    shutil.copy2(
        source / ".local-knowledge" / "project.toml",
        target / ".local-knowledge" / "project.toml",
    )
    original_copy = memory_snapshot_module._copy_verified_snapshot

    def mutate_before_copy(
        snapshot_root: Path,
        project_root: Path,
        inspected: dict[str, object],
    ) -> tuple[Path, dict[str, object]]:
        note = next((snapshot_root / "memory" / "notes").glob("*.md"))
        note.write_bytes(note.read_bytes() + b"\nraced source bytes\n")
        return original_copy(snapshot_root, project_root, inspected)

    monkeypatch.setattr(
        memory_snapshot_module,
        "_copy_verified_snapshot",
        mutate_before_copy,
    )

    with pytest.raises(SnapshotError, match="changed while being imported"):
        import_memory_snapshot(str(target.resolve()), str(snapshot))

    assert not (target / ".memorizer").exists()
    assert not list((target / ".local-knowledge").glob(".snapshot-import.*"))
    assert not list((target / ".local-knowledge").glob(".memory-import.*"))


def test_snapshot_import_rechecks_controlled_staging_before_vault_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    source = _memory_project(tmp_path, "staged-race-source")
    _capture(
        source,
        event_id="evt_snapshot_staged_race",
        title="Snapshot staged race",
        text="The staged snapshot is verified again before vault replacement.",
    )
    snapshot = source / ".local-knowledge" / "staged-race-snapshot"
    export_memory_snapshot(str(source.resolve()), str(snapshot))
    target = tmp_path / "staged-race-target"
    (target / ".local-knowledge").mkdir(parents=True)
    shutil.copy2(
        source / ".local-knowledge" / "project.toml",
        target / ".local-knowledge" / "project.toml",
    )
    original_stage = memory_snapshot_module._stage_snapshot

    def mutate_staged_copy(
        staged_snapshot: Path,
        project_root: Path,
        files: list[dict[str, object]],
    ) -> Path:
        note = next((staged_snapshot / "memory" / "notes").glob("*.md"))
        note.write_bytes(note.read_bytes() + b"\nraced staged bytes\n")
        return original_stage(staged_snapshot, project_root, files)

    monkeypatch.setattr(
        memory_snapshot_module,
        "_stage_snapshot",
        mutate_staged_copy,
    )

    with pytest.raises(SnapshotError, match="changed while being imported"):
        import_memory_snapshot(str(target.resolve()), str(snapshot))

    assert not (target / ".memorizer").exists()
    assert not list((target / ".local-knowledge").glob(".snapshot-import.*"))
    assert not list((target / ".local-knowledge").glob(".memory-import.*"))


def test_snapshot_import_rejects_junction_input_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    source = _memory_project(tmp_path, "junction-source")
    snapshot = source / ".local-knowledge" / "junction-snapshot"
    export_memory_snapshot(str(source.resolve()), str(snapshot))
    target = tmp_path / "junction-target"
    (target / ".local-knowledge").mkdir(parents=True)
    shutil.copy2(
        source / ".local-knowledge" / "project.toml",
        target / ".local-knowledge" / "project.toml",
    )
    junction = tmp_path / "snapshot-junction"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(snapshot)],
        text=True,
        capture_output=True,
    )
    if result.returncode:
        pytest.skip(f"cannot create junction: {result.stderr or result.stdout}")
    try:
        with pytest.raises(SnapshotError, match="junction|reparse"):
            import_memory_snapshot(str(target.resolve()), str(junction))
        assert not (target / ".memorizer").exists()
    finally:
        os.rmdir(junction)


def test_status_reports_stale_and_corrupt_snapshot_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = _memory_project(tmp_path)
    _capture(
        project,
        event_id="evt_snapshot_initial",
        title="Initial snapshot",
        text="The first snapshot is current.",
    )
    snapshot = project / ".local-knowledge" / "memory-snapshot"
    export_memory_snapshot(str(project.resolve()), str(snapshot))
    _capture(
        project,
        event_id="evt_snapshot_newer",
        title="Newer memory",
        text="This memory makes the snapshot stale.",
    )
    assert knowledge_status(str(project.resolve()))["memory_snapshot"]["freshness"] == "stale"

    note_path = next((snapshot / "memory" / "notes").glob("*.md"))
    note_path.write_text(
        note_path.read_text(encoding="utf-8") + "\ncorrupt\n",
        encoding="utf-8",
    )
    inspected = inspect_memory_snapshot(
        snapshot,
        expected_project_id=ProjectManifest.load(project).project_id,
    )
    assert inspected["valid"] is False
    diagnosis = doctor_workspace(str(project.resolve()))
    check = next(
        item for item in diagnosis["checks"] if item["name"] == "memory-snapshot"
    )
    assert check["ok"] is False
    assert diagnosis["ok"] is False


def test_memory_snapshot_cli_exports_public_only_with_ack_and_imports_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    project = _memory_project(tmp_path, "cli-source")
    _capture(
        project,
        event_id="evt_cli_snapshot",
        title="CLI snapshot",
        text="The CLI snapshot can move to another Windows clone.",
    )
    snapshot = project / ".local-knowledge" / "cli-snapshot"
    denied = local_knowledge_cli(
        [
            "memory",
            "export",
            "--root",
            str(project.resolve()),
            "--output",
            str(snapshot),
            "--git-visibility",
            "public",
        ]
    )
    assert denied == 2
    assert json.loads(capsys.readouterr().err)["ok"] is False

    exported = local_knowledge_cli(
        [
            "memory",
            "export",
            "--root",
            str(project.resolve()),
            "--output",
            str(snapshot),
            "--git-visibility",
            "public",
            "--allow-public",
        ]
    )
    assert exported == 0
    assert json.loads(capsys.readouterr().out)["git_visibility"] == "public"

    clone = tmp_path / "cli-clone"
    (clone / ".local-knowledge").mkdir(parents=True)
    shutil.copy2(
        project / ".local-knowledge" / "project.toml",
        clone / ".local-knowledge" / "project.toml",
    )
    imported = local_knowledge_cli(
        [
            "memory",
            "import",
            "--root",
            str(clone.resolve()),
            "--input",
            str(snapshot),
        ]
    )
    assert imported == 0
    assert json.loads(capsys.readouterr().out)["imported"] == 1
