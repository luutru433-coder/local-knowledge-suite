# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from local_knowledge import WORKSPACE_SCHEMA_VERSION
from local_knowledge import cli as local_cli
from local_knowledge.ckb import cli as ckb_cli
from local_knowledge.ckb.db import Database
from local_knowledge.errors import CompatibilityError, ManifestError, RegistryError
from local_knowledge.manifests import (
    CompanyManifest,
    write_company_manifest,
)
from local_knowledge.migrations import migrate_workspace
from local_knowledge.registry import CompanyRegistry
from local_knowledge.services import (
    bootstrap_workspace,
    initialize_company_repository,
    register_company,
)


def _tree(root: Path) -> tuple[tuple[str, ...], dict[str, bytes]]:
    directories = tuple(
        sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_dir()
        )
    )
    files = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }
    return directories, files


def _make_stale(manifest_path: Path) -> None:
    current = f"schema_version = {WORKSPACE_SCHEMA_VERSION}"
    text = manifest_path.read_text(encoding="utf-8")
    assert current in text
    manifest_path.write_text(
        text.replace(current, "schema_version = 1", 1),
        encoding="utf-8",
    )


def _write_registry(path: Path, companies: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "companies": companies,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _registry_entry(root: str | Path) -> dict[str, str]:
    return {
        "root": str(root),
        "registered_at": "2026-07-25T00:00:00+00:00",
    }


def test_stale_company_init_and_register_only_register_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "stale-company"
    initialize_company_repository(
        company,
        "Stale Company",
        "stale-company",
    )
    registry = CompanyRegistry()
    registry.unregister(company)
    manifest = company / ".local-knowledge" / "company.toml"
    _make_stale(manifest)
    before = _tree(company)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("stale company reached a repository mutation")

    monkeypatch.setattr(
        "local_knowledge.services.initialize_company_git_repository",
        forbidden,
    )
    monkeypatch.setattr(
        "local_knowledge.services.regenerate_indexes",
        forbidden,
    )
    monkeypatch.setattr(Database, "initialize", forbidden)

    with pytest.raises(CompatibilityError, match="migration"):
        initialize_company_repository(
            company,
            "Stale Company",
            "stale-company",
        )
    assert registry.resolve("stale-company") == company.resolve()
    assert _tree(company) == before

    with pytest.raises(CompatibilityError, match="migration"):
        register_company(company)
    assert registry.resolve("stale-company") == company.resolve()
    assert _tree(company) == before


@pytest.mark.parametrize(
    "entry",
    [
        ["not", "an", "object"],
        {},
        {"root": 42, "registered_at": "2026-07-25T00:00:00+00:00"},
        {"root": "relative-company", "registered_at": "2026-07-25T00:00:00+00:00"},
        {"root": "C:\\Company", "registered_at": 42},
        {"root": "C:\\Company", "registered_at": "not-a-timestamp"},
        {"root": "C:\\Company", "registered_at": "2026-07-25T00:00:00"},
    ],
)
def test_registry_corrupt_entries_fail_closed_without_write(
    entry: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    registry_path = tmp_path / "machine" / "registry.json"
    _write_registry(registry_path, {"company-a": entry})
    before = registry_path.read_bytes()
    cwd_before = _tree(tmp_path)

    with pytest.raises(RegistryError, match="invalid|absolute"):
        CompanyRegistry(registry_path).resolve("company-a")

    assert registry_path.read_bytes() == before
    assert _tree(tmp_path) == cwd_before


def test_registry_rejects_noncanonical_company_id_without_write(
    tmp_path: Path,
) -> None:
    company = tmp_path / "company"
    company.mkdir()
    write_company_manifest(
        company,
        CompanyManifest(
            WORKSPACE_SCHEMA_VERSION,
            "company-a",
            "Company A",
        ),
    )
    registry_path = tmp_path / "machine" / "registry.json"
    _write_registry(
        registry_path,
        {"Company-A": _registry_entry(company.resolve())},
    )
    before = registry_path.read_bytes()

    with pytest.raises(RegistryError, match="not canonical"):
        CompanyRegistry(registry_path).list()

    assert registry_path.read_bytes() == before


def test_registry_rejects_noncanonical_stored_root_without_write(
    tmp_path: Path,
) -> None:
    company = tmp_path / "company"
    company.mkdir()
    write_company_manifest(
        company,
        CompanyManifest(
            WORKSPACE_SCHEMA_VERSION,
            "company-a",
            "Company A",
        ),
    )
    noncanonical = company.parent / "unused" / ".." / company.name
    registry_path = tmp_path / "machine" / "registry.json"
    _write_registry(
        registry_path,
        {"company-a": _registry_entry(noncanonical)},
    )
    before = registry_path.read_bytes()

    with pytest.raises(RegistryError, match="non-canonical"):
        CompanyRegistry(registry_path).resolve("company-a")

    assert registry_path.read_bytes() == before


def test_registry_register_rejects_relative_root_without_cwd_fallback_or_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    company = tmp_path / "relative-company"
    company.mkdir()
    write_company_manifest(
        company,
        CompanyManifest(
            WORKSPACE_SCHEMA_VERSION,
            "relative-company",
            "Relative Company",
        ),
    )
    registry_path = tmp_path / "machine" / "registry.json"
    registry = CompanyRegistry(registry_path)
    monkeypatch.chdir(tmp_path)
    before = _tree(tmp_path)

    with pytest.raises(RegistryError, match="absolute canonical"):
        registry.register(Path("relative-company"))

    assert not registry_path.exists()
    assert _tree(tmp_path) == before


def test_registry_register_rejects_same_canonical_root_under_alias_without_write(
    tmp_path: Path,
) -> None:
    company = tmp_path / "company"
    company.mkdir()
    write_company_manifest(
        company,
        CompanyManifest(
            WORKSPACE_SCHEMA_VERSION,
            "current-company",
            "Current Company",
        ),
    )
    registry_path = tmp_path / "machine" / "registry.json"
    _write_registry(
        registry_path,
        {"old-company": _registry_entry(company.resolve())},
    )
    before = registry_path.read_bytes()

    with pytest.raises(RegistryError, match="already registered as old-company"):
        CompanyRegistry(registry_path).register(company.resolve())

    assert registry_path.read_bytes() == before


def test_company_initialize_registry_conflict_preflight_preserves_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    registered = tmp_path / "registered"
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    initialize_company_repository(
        registered,
        "Registered Company",
        "shared-company",
    )
    before = _tree(candidate)

    with pytest.raises(RegistryError, match="already registered"):
        initialize_company_repository(
            candidate,
            "Candidate Company",
            "shared-company",
        )

    assert _tree(candidate) == before
    assert not (candidate / ".local-knowledge").exists()
    assert not (candidate / ".ckb").exists()
    assert not (candidate / ".git").exists()
    assert not (candidate / "knowledge").exists()


def test_company_initialize_registry_conflict_does_not_create_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    registered = tmp_path / "registered"
    candidate = tmp_path / "candidate-that-must-not-be-created"
    initialize_company_repository(
        registered,
        "Registered Company",
        "shared-company",
    )

    with pytest.raises(RegistryError, match="already registered"):
        initialize_company_repository(
            candidate,
            "Candidate Company",
            "shared-company",
        )

    assert not candidate.exists()


def test_registry_guard_serializes_processes_and_releases_after_exit(
    tmp_path: Path,
) -> None:
    registry_path = tmp_path / "machine" / "registry.json"
    ready = tmp_path / "child-ready"
    release = tmp_path / "child-release"
    runtime_source = str(Path(sys.modules["local_knowledge"].__file__).resolve().parents[1])
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(
            None,
            (runtime_source, environment.get("PYTHONPATH", "")),
        )
    )
    child_code = "\n".join(
        (
            "import sys, time",
            "from pathlib import Path",
            "from local_knowledge.registry import CompanyRegistry",
            "registry_path, ready_path, release_path = map(Path, sys.argv[1:])",
            "with CompanyRegistry(registry_path).mutation_guard():",
            "    ready_path.write_text('ready', encoding='ascii')",
            "    deadline = time.monotonic() + 15",
            "    while not release_path.exists():",
            "        if time.monotonic() >= deadline:",
            "            raise RuntimeError('parent did not release child registry lock')",
            "        time.sleep(0.01)",
        )
    )
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            child_code,
            str(registry_path),
            str(ready),
            str(release),
        ],
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    acquired = threading.Event()

    def acquire_after_child() -> None:
        with CompanyRegistry(registry_path).mutation_guard():
            acquired.set()

    contender: threading.Thread | None = None
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and child.poll() is None:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.01)
        assert ready.is_file(), child.communicate(timeout=1)
        contender = threading.Thread(target=acquire_after_child, daemon=True)
        contender.start()
        assert not acquired.wait(timeout=0.2)
        release.write_text("release", encoding="ascii")
        contender.join(timeout=10)
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, (stdout, stderr)
        assert acquired.is_set()
    finally:
        release.write_text("release", encoding="ascii")
        if child.poll() is None:
            child.kill()
        child.communicate()
        if contender is not None:
            contender.join(timeout=1)


def test_registry_guard_is_reentrant_and_releases_after_exception(
    tmp_path: Path,
) -> None:
    registry = CompanyRegistry(tmp_path / "machine" / "registry.json")

    with pytest.raises(RuntimeError, match="injected guarded failure"):
        with registry.mutation_guard():
            with CompanyRegistry(registry.path).mutation_guard():
                raise RuntimeError("injected guarded failure")

    with CompanyRegistry(registry.path).mutation_guard():
        pass


def test_company_register_registry_conflict_preflight_preserves_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    registered = tmp_path / "registered"
    candidate = tmp_path / "candidate"
    initialize_company_repository(
        registered,
        "Registered Company",
        "shared-company",
    )
    alternate_registry = CompanyRegistry(tmp_path / "alternate" / "registry.json")
    initialize_company_repository(
        candidate,
        "Candidate Company",
        "shared-company",
        registry=alternate_registry,
    )
    before = _tree(candidate)

    with pytest.raises(RegistryError, match="already registered"):
        register_company(candidate)

    assert _tree(candidate) == before


def test_project_bootstrap_rejects_hard_linked_gitignore_without_write(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.gitignore"
    outside.write_text("keep-me\n", encoding="utf-8")
    os.link(outside, project / ".gitignore")
    before = _tree(project)
    outside_before = outside.read_bytes()

    with pytest.raises(ValueError, match="hard-linked"):
        bootstrap_workspace(str(project.resolve()))

    assert _tree(project) == before
    assert outside.read_bytes() == outside_before
    assert not (project / ".local-knowledge").exists()
    assert not (project / ".memorizer").exists()


def test_company_initialize_rejects_hard_linked_gitignore_without_write(
    tmp_path: Path,
) -> None:
    company = tmp_path / "company"
    company.mkdir()
    outside = tmp_path / "outside.gitignore"
    outside.write_text("keep-me\n", encoding="utf-8")
    os.link(outside, company / ".gitignore")
    before = _tree(company)
    outside_before = outside.read_bytes()

    with pytest.raises(ValueError, match="hard-linked"):
        initialize_company_repository(
            company,
            "Hard Link Company",
            "hard-link-company",
        )

    assert _tree(company) == before
    assert outside.read_bytes() == outside_before
    assert not (company / ".local-knowledge").exists()
    assert not (company / ".ckb").exists()
    assert not (company / ".git").exists()


def test_registry_resolve_rejects_stale_path_identity_without_write(
    tmp_path: Path,
) -> None:
    company = tmp_path / "company"
    company.mkdir()
    write_company_manifest(
        company,
        CompanyManifest(
            WORKSPACE_SCHEMA_VERSION,
            "different-company",
            "Different Company",
        ),
    )
    registry_path = tmp_path / "machine" / "registry.json"
    _write_registry(
        registry_path,
        {"expected-company": _registry_entry(company.resolve())},
    )
    before = registry_path.read_bytes()

    with pytest.raises(RegistryError, match="identity mismatch"):
        CompanyRegistry(registry_path).resolve("expected-company")

    assert registry_path.read_bytes() == before


def test_current_combined_workspace_migration_is_true_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "current-company"
    project = tmp_path / "current-project"
    project.mkdir()
    initialize_company_repository(
        company,
        "Current Company",
        "current-company",
    )
    bootstrap_workspace(
        str(project.resolve()),
        "current-company",
        profile="combined",
    )
    company_before = _tree(company)
    project_before = _tree(project)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no-op migration performed a database action")

    monkeypatch.setattr(Database, "initialize", forbidden)
    monkeypatch.setattr(Database, "backup_to", forbidden)
    result = migrate_workspace(str(project.resolve()), dry_run=False)

    assert result["applied"] is False
    assert result["noop"] is True
    assert result["actions"] == []
    assert result["backups"] == []
    assert _tree(company) == company_before
    assert _tree(project) == project_before


def test_ckb_requires_explicit_root_and_ignores_cwd_and_ckb_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    implicit = tmp_path / "implicit-company"
    implicit.mkdir()
    monkeypatch.chdir(implicit)
    monkeypatch.setenv("CKB_ROOT", str(implicit))
    before = _tree(implicit)

    with pytest.raises(SystemExit):
        ckb_cli.main(["validate"])

    assert _tree(implicit) == before
    assert not (implicit / ".ckb").exists()
    assert not (implicit / "knowledge").exists()


@pytest.mark.parametrize("command", ["init", "validate"])
def test_ckb_rejects_missing_manifest_before_write(
    command: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    root = tmp_path / f"missing-manifest-{command}"
    root.mkdir()
    before = _tree(root)

    with pytest.raises(ManifestError, match="missing manifest"):
        ckb_cli.main(["--root", str(root.resolve()), command])

    assert _tree(root) == before


def test_ckb_rejects_missing_registry_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    root = tmp_path / "unregistered-company"
    root.mkdir()
    write_company_manifest(
        root,
        CompanyManifest(
            WORKSPACE_SCHEMA_VERSION,
            "unregistered-company",
            "Unregistered Company",
        ),
    )
    before = _tree(root)

    with pytest.raises(RegistryError, match="not registered"):
        ckb_cli.main(["--root", str(root.resolve()), "validate"])

    assert _tree(root) == before


def test_ckb_rejects_registry_root_mismatch_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    registered = tmp_path / "registered-company"
    requested = tmp_path / "requested-company"
    requested.mkdir()
    initialize_company_repository(
        registered,
        "Shared Identity",
        "shared-identity",
    )
    write_company_manifest(
        requested,
        CompanyManifest(
            WORKSPACE_SCHEMA_VERSION,
            "shared-identity",
            "Shared Identity",
        ),
    )
    before = _tree(requested)

    with pytest.raises(RegistryError, match="root mismatch"):
        ckb_cli.main(["--root", str(requested.resolve()), "validate"])

    assert _tree(requested) == before


def test_ckb_rejects_stale_schema_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    root = tmp_path / "stale-cli-company"
    initialize_company_repository(
        root,
        "Stale CLI Company",
        "stale-cli-company",
    )
    _make_stale(root / ".local-knowledge" / "company.toml")
    before = _tree(root)

    with pytest.raises(CompatibilityError, match="migration"):
        ckb_cli.main(["--root", str(root.resolve()), "init", "--reset-state"])

    assert _tree(root) == before


def test_ckb_rejects_relative_root_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    relative = Path("relative-company")
    relative.mkdir()
    before = _tree(relative)

    with pytest.raises(ValueError, match="absolute"):
        ckb_cli.main(["--root", str(relative), "validate"])

    assert _tree(relative) == before


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "192.168.1.20", "8.8.8.8", "company.internal"],
)
def test_direct_ckb_serve_rejects_non_loopback_before_uvicorn(
    host: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def forbidden(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("uvicorn must not be reached")

    monkeypatch.setattr("uvicorn.run", forbidden)
    with pytest.raises(ValueError, match="loopback|localhost"):
        ckb_cli.main(
            [
                "--root",
                str(tmp_path.resolve()),
                "serve",
                "--host",
                host,
            ]
        )
    assert called is False


@pytest.mark.parametrize("host", ["0.0.0.0", "10.20.30.40", "example.com"])
def test_company_serve_rejects_non_loopback_before_uvicorn(
    host: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    called = False

    def forbidden(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True
        raise AssertionError("uvicorn must not be reached")

    monkeypatch.setattr("uvicorn.run", forbidden)
    result = local_cli.main(
        [
            "company",
            "serve",
            "--company",
            "missing-company",
            "--host",
            host,
        ]
    )
    assert result == 2
    error = capsys.readouterr().err.casefold()
    assert "loopback" in error or "localhost" in error
    assert called is False


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("localhost", "127.0.0.1"),
        ("127.0.0.1", "127.0.0.1"),
        ("127.42.0.9", "127.42.0.9"),
        ("::1", "::1"),
    ],
)
def test_loopback_host_canonicalization(host: str, expected: str) -> None:
    assert ckb_cli.canonicalize_loopback_host(host) == expected
