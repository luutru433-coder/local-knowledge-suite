# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Literal

from . import WORKSPACE_SCHEMA_VERSION, __version__
from .ckb.config import Settings
from .ckb.db import Database
from .ckb.gitops import (
    COMPANY_PRIVATE_TRACKED_PATHS,
    PROJECT_PRIVATE_TRACKED_PATHS,
    initialize_company_repository as initialize_company_git_repository,
    reject_tracked_private_paths,
    validate_company_repository,
)
from .ckb.okf import regenerate_indexes
from .ckb.pipeline import KnowledgeService
from .ckb.security import create_user
from .ckb.secrets_store import (
    MASTER_KEY_USERNAME,
    SecretStoreError,
    purge_company_master_key,
)
from .errors import CompatibilityError, RegistryError
from .manifests import (
    COMPANY_MANIFEST,
    CompanyManifest,
    InstallMode,
    Profile,
    ProjectManifest,
    new_project_manifest,
    validate_id,
    write_company_manifest,
    write_project_manifest,
)
from .memory_snapshot import memory_snapshot_status
from .providers import BundledCompanyProvider, BundledMemoryProvider, BundledSkillProvider
from .registry import CompanyRegistry
from .workspace import (
    WorkspaceContext,
    require_current_company_schema,
    require_current_workspace_schema,
    resolve_project_root,
)
from .winio import is_reparse_point, replace_file


MemoryKind = Literal[
    "correction",
    "preference",
    "habit",
    "decision",
    "commitment",
    "entity-fact",
    "project-knowledge",
]


def _bounded_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    return max(1, min(limit, 50))


def _assert_safe_gitignore(path: Path) -> None:
    if not path.exists():
        return
    if is_reparse_point(path):
        raise ValueError(
            f".gitignore cannot be a symlink, junction, or reparse point: {path}"
        )
    if not path.is_file():
        raise ValueError(f".gitignore must be a regular file: {path}")
    if path.stat(follow_symlinks=False).st_nlink != 1:
        raise ValueError(f".gitignore cannot be a hard-linked file: {path}")


def _merge_ignore(root: Path, entries: tuple[str, ...]) -> None:
    path = root / ".gitignore"
    _assert_safe_gitignore(path)
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    marker = "# Local Knowledge derived/private state"
    lines: list[str] = []
    marker_seen = False
    for line in current.splitlines():
        if line.strip() == marker:
            if marker_seen:
                continue
            marker_seen = True
        lines.append(line)
    existing = {line.strip().casefold() for line in lines}
    additions = [entry for entry in entries if entry.casefold() not in existing]
    normalized = "\n".join(lines).rstrip() + ("\n" if lines else "")
    if not additions and normalized == current:
        return
    if additions:
        if lines and lines[-1].strip():
            lines.append("")
        if not marker_seen:
            lines.append(marker)
        lines.extend(additions)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".gitignore.",
        suffix=".tmp",
        dir=root,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines).rstrip() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _assert_safe_gitignore(path)
        replace_file(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold().replace("\u0111", "d"))
    folded = "".join(character for character in normalized if not unicodedata.combining(character))
    slug = re.sub(r"[^a-z0-9]+", "-", folded).strip("-")
    return validate_id(slug or "company", "company_id")


def _register_stale_company_identity(
    registry: CompanyRegistry,
    company_root: Path,
    company_id: str,
) -> dict[str, Any]:
    normalized_root = os.path.normcase(str(company_root))
    for registered_id, entry in registry.list().items():
        if registered_id == company_id or not isinstance(entry, dict):
            continue
        raw_root = entry.get("root")
        if not isinstance(raw_root, str):
            continue
        candidate = Path(raw_root).expanduser()
        if not candidate.is_absolute():
            continue
        if os.path.normcase(str(candidate.resolve())) == normalized_root:
            raise RegistryError(
                "registry identity mismatch: "
                f"{company_root} is already registered as {registered_id}"
            )
    return registry.register(company_root)


def initialize_company_repository(
    root: str | Path,
    name: str,
    company_id: str | None = None,
    admin: str | None = None,
    password: str | None = None,
    registry: CompanyRegistry | None = None,
) -> dict[str, Any]:
    requested_root = Path(root).expanduser()
    if not requested_root.is_absolute():
        raise ValueError("company root must be an absolute Windows path")
    validate_id(company_id, "company_id") if company_id else _slug(name)
    if not name.strip():
        raise ValueError("company name must be non-empty")
    if requested_root.exists():
        checked_root = requested_root.resolve(strict=True)
        if not checked_root.is_dir():
            raise ValueError(f"company root is not a directory: {checked_root}")
        _assert_safe_gitignore(checked_root / ".gitignore")
        reject_tracked_private_paths(
            checked_root,
            COMPANY_PRIVATE_TRACKED_PATHS,
            label="company repository",
            require_own_repository=False,
        )
    active_registry = registry or CompanyRegistry()
    with active_registry.mutation_guard():
        return _initialize_company_repository_locked(
            root,
            name,
            company_id,
            admin,
            password,
            active_registry,
        )


def _initialize_company_repository_locked(
    root: str | Path,
    name: str,
    company_id: str | None,
    admin: str | None,
    password: str | None,
    active_registry: CompanyRegistry,
) -> dict[str, Any]:
    company_root = Path(root).expanduser()
    if not company_root.is_absolute():
        raise ValueError("company root must be an absolute Windows path")
    identifier = validate_id(company_id, "company_id") if company_id else _slug(name)
    requested_name = name.strip()
    if not requested_name:
        raise ValueError("company name must be non-empty")
    company_root = active_registry.assert_can_initialize(company_root, identifier)
    if company_root.exists():
        company_root = company_root.resolve(strict=True)
        if not company_root.is_dir():
            raise ValueError(f"company root is not a directory: {company_root}")
        _assert_safe_gitignore(company_root / ".gitignore")
        reject_tracked_private_paths(
            company_root,
            COMPANY_PRIVATE_TRACKED_PATHS,
            label="company repository",
            require_own_repository=False,
        )
        if (company_root / COMPANY_MANIFEST).is_file():
            existing = CompanyManifest.load(company_root)
            if (
                existing.company_id != identifier
                or existing.name != requested_name
            ):
                raise ValueError(
                    "company manifest already exists with different identity"
                )
            if existing.schema_version != WORKSPACE_SCHEMA_VERSION:
                # A stale clone still needs a machine-local identity mapping so
                # a previously bound project can run the explicit migration.
                # Registration is the only permitted write on this path.
                _register_stale_company_identity(
                    active_registry,
                    company_root,
                    existing.company_id,
                )
                require_current_company_schema(
                    company_root,
                    "company initialization",
                )
    else:
        company_root.mkdir(parents=True, exist_ok=True)
        company_root = company_root.resolve(strict=True)
    active_registry.assert_can_register(company_root, identifier)
    manifest = CompanyManifest(WORKSPACE_SCHEMA_VERSION, identifier, name.strip())
    manifest_path, manifest_created = write_company_manifest(company_root, manifest)
    _merge_ignore(company_root, (".ckb/", ".local-sources/", "web/dist/"))
    settings = Settings.for_company(company_root, identifier)
    settings.ensure_directories()
    database = Database(settings.database)
    database.initialize()
    regenerate_indexes(settings.bundle_dir)
    settings.write_user_config()
    user: dict[str, Any] | None = None
    if admin is not None or password is not None:
        if not admin or not password:
            raise ValueError("admin and password must be supplied together")
        with database.connect() as connection:
            existing = connection.execute("SELECT id,username,role FROM users ORDER BY id LIMIT 1").fetchone()
        if existing is None:
            user_id = create_user(database, admin, password, "admin")
            user = {"id": user_id, "username": admin, "role": "admin", "created": True}
        else:
            user = {**dict(existing), "created": False}
    git_paths = [
        ".gitignore",
        ".local-knowledge/company.toml",
        *(path.relative_to(company_root).as_posix() for path in settings.bundle_dir.rglob("*.md")),
    ]
    git = initialize_company_git_repository(
        company_root,
        settings.canonical_branch,
        tuple(dict.fromkeys(git_paths)),
    )
    service = KnowledgeService(settings, db=database)
    imported = service.rebuild_from_bundle()
    registration = active_registry.register(company_root)
    return {
        "ok": True,
        "company_id": identifier,
        "name": manifest.name,
        "root": str(company_root),
        "manifest": str(manifest_path),
        "manifest_created": manifest_created,
        "database": str(settings.database),
        "bundle": str(settings.bundle_dir),
        "imported_concepts": imported,
        "git": git,
        "administrator": user,
        "registration": registration,
    }


def register_company(root: str | Path, registry: CompanyRegistry | None = None) -> dict[str, Any]:
    checked_root = Path(root).expanduser()
    if not checked_root.is_absolute():
        raise ValueError("company root must be an absolute Windows path")
    checked_root = checked_root.resolve(strict=True)
    reject_tracked_private_paths(
        checked_root,
        COMPANY_PRIVATE_TRACKED_PATHS,
        label="company repository",
        require_own_repository=True,
    )
    CompanyManifest.load(checked_root)
    active_registry = registry or CompanyRegistry()
    with active_registry.mutation_guard():
        return _register_company_locked(root, active_registry)


def _register_company_locked(
    root: str | Path,
    active_registry: CompanyRegistry,
) -> dict[str, Any]:
    company_root = Path(root).expanduser()
    if not company_root.is_absolute():
        raise ValueError("company root must be an absolute Windows path")
    company_root = company_root.resolve(strict=True)
    reject_tracked_private_paths(
        company_root,
        COMPANY_PRIVATE_TRACKED_PATHS,
        label="company repository",
        require_own_repository=True,
    )
    company = CompanyManifest.load(company_root)
    active_registry.assert_can_register(company_root, company.company_id)
    if company.schema_version != WORKSPACE_SCHEMA_VERSION:
        # Register only the verified identity. Repository setup, database
        # migration, index rebuild, Git validation, and user writes must wait
        # for an explicit workspace migration.
        _register_stale_company_identity(
            active_registry,
            company_root,
            company.company_id,
        )
        require_current_company_schema(company_root, "company registration")
    settings = Settings.for_company(company_root, company.company_id)
    required_paths = (
        ".gitignore",
        ".local-knowledge/company.toml",
        *(path.relative_to(company_root).as_posix() for path in settings.bundle_dir.rglob("*.md")),
    )
    git = validate_company_repository(
        company_root,
        settings.canonical_branch,
        tuple(dict.fromkeys(required_paths)),
    )
    settings.ensure_directories()
    database = Database(settings.database)
    database.initialize()
    imported = KnowledgeService(settings, db=database).rebuild_from_bundle()
    with database.connect() as connection:
        users = int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])
    registration = active_registry.register(company_root)
    return {
        **registration,
        "database": str(settings.database),
        "bundle": str(settings.bundle_dir),
        "rebuilt_concepts": imported,
        "users": users,
        "requires_administrator": users == 0,
        "git": git,
    }


def unregister_company(
    root: str | Path,
    *,
    purge_credential_key: bool = False,
    confirm_company: str | None = None,
    registry: CompanyRegistry | None = None,
) -> dict[str, Any]:
    company_root = Path(root).expanduser()
    if not company_root.is_absolute():
        raise ValueError("company root must be an absolute Windows path")
    company_root = company_root.resolve(strict=True)
    company = CompanyManifest.load(company_root)
    if purge_credential_key:
        if confirm_company is None:
            raise ValueError(
                "--purge-credential-key requires --confirm-company COMPANY_ID"
            )
        if confirm_company != company.company_id:
            raise ValueError(
                "--confirm-company must exactly match company ID "
                f"{company.company_id}"
            )
    elif confirm_company is not None:
        raise ValueError(
            "--confirm-company is only valid with --purge-credential-key"
        )

    registration = (registry or CompanyRegistry()).unregister(company_root)
    credential_key: dict[str, object] = {
        "requested": purge_credential_key,
        "service": f"local-knowledge-suite/{company.company_id}",
        "username": MASTER_KEY_USERNAME,
        "deleted": False,
        "missing": False,
    }
    ok = True
    if purge_credential_key:
        try:
            credential_key.update(purge_company_master_key(company.company_id))
        except SecretStoreError as exc:
            ok = False
            credential_key["error"] = str(exc)

    return {
        "ok": ok,
        **registration,
        "credential_key": credential_key,
        "preserved": {
            "repository": str(company_root),
            "manifest": str(company_root / ".local-knowledge" / "company.toml"),
            "database_state": str(company_root / ".ckb"),
            "local_sources": str(company_root / ".local-sources"),
            "knowledge": str(company_root / "knowledge"),
        },
    }


def bootstrap_workspace(
    root: str,
    company_id: str | None = None,
    profile: Profile = "memory-only",
    install_mode: InstallMode = "global",
    registry: CompanyRegistry | None = None,
    *,
    allow_project_rebind: bool = False,
) -> dict[str, Any]:
    project_root = resolve_project_root(root)
    _assert_safe_gitignore(project_root / ".gitignore")
    reject_tracked_private_paths(
        project_root,
        PROJECT_PRIVATE_TRACKED_PATHS,
        label="project repository",
        require_own_repository=False,
    )
    if profile not in {"combined", "memory-only", "company-only"}:
        raise ValueError(f"unsupported profile: {profile}")
    if install_mode not in {"global", "vendored"}:
        raise ValueError(f"unsupported install mode: {install_mode}")
    if profile in {"combined", "company-only"} and company_id is None:
        raise ValueError(f"profile {profile} requires --company COMPANY_ID")
    normalized_company_id = (
        validate_id(company_id, "company_id") if company_id is not None else None
    )
    active_registry = registry or CompanyRegistry()
    company: CompanyManifest | None = None
    if profile in {"combined", "company-only"}:
        assert normalized_company_id is not None
        company_root = active_registry.resolve(normalized_company_id)
        company = require_current_company_schema(company_root, "workspace bootstrap")
    manifest_path = project_root / ".local-knowledge" / "project.toml"
    if manifest_path.is_file():
        manifest = ProjectManifest.load(project_root)
        if manifest.schema_version != WORKSPACE_SCHEMA_VERSION:
            raise CompatibilityError(
                "workspace bootstrap is blocked until migration completes "
                f"(project={manifest.schema_version}; runtime={WORKSPACE_SCHEMA_VERSION}). "
                "Run `local-knowledge migrate --root PROJECT_ROOT --apply`."
            )
        if manifest.company_id != normalized_company_id:
            raise ValueError(
                "project company binding is immutable: "
                f"existing={manifest.company_id!r}, requested={normalized_company_id!r}"
            )
        if manifest.profile != profile or manifest.install_mode != install_mode:
            raise ValueError(
                "project bootstrap settings are immutable: existing "
                f"profile={manifest.profile}, install_mode={manifest.install_mode}; requested "
                f"profile={profile}, install_mode={install_mode}"
            )
        created = False
    else:
        manifest = new_project_manifest(normalized_company_id, profile, install_mode)
        _, created = write_project_manifest(project_root, manifest)
    if manifest.profile in {"combined", "company-only"}:
        assert manifest.company_id is not None
        active_registry.authorize_project(
            project_root,
            manifest.project_id,
            manifest.company_id,
            allow_rebind=allow_project_rebind,
        )
    context = WorkspaceContext.resolve(project_root, active_registry)
    require_current_workspace_schema(context, "workspace bootstrap")
    memory_result: dict[str, Any] = {"enabled": context.memory_enabled}
    if context.memory_enabled:
        memory_result.update(BundledMemoryProvider().initialize(context))
    company_result: dict[str, Any] = {"enabled": context.company_enabled}
    if context.company_enabled:
        company_result.update(BundledCompanyProvider().initialize(context))
    ignore_entries = [".memorizer/", ".local-knowledge/backups/"]
    if context.project.install_mode == "vendored":
        ignore_entries.extend(
            [
                "tools/local-knowledge-suite/runtime/.venv/",
                "tools/local-knowledge-suite/runtime/.uv-cache/",
                "tools/local-knowledge-suite/runtime/**/__pycache__/",
            ]
        )
    _merge_ignore(project_root, tuple(ignore_entries))
    vendor_root = project_root / "tools" / "local-knowledge-suite"
    vendor_required = context.project.install_mode == "vendored" and not vendor_root.is_dir()
    return {
        "ok": True,
        "created": created,
        "root": str(project_root),
        "project_id": context.project.project_id,
        "company_id": context.project.company_id,
        "profile": context.project.profile,
        "install_mode": context.project.install_mode,
        "memory": memory_result,
        "company": company_result,
        "runtime_version": __version__,
        "workspace_schema_version": context.project.schema_version,
        "vendor_required": vendor_required,
        "warning": (
            "run the plugin vendor installer to populate tools/local-knowledge-suite"
            if vendor_required
            else None
        ),
    }


def restore_workspace(
    root: str,
    registry: CompanyRegistry | None = None,
) -> dict[str, Any]:
    """Recreate ignored local state for an already initialized cloned project."""

    project_root = resolve_project_root(root)
    manifest = ProjectManifest.load(project_root)
    return bootstrap_workspace(
        str(project_root),
        manifest.company_id,
        manifest.profile,
        manifest.install_mode,
        registry,
        allow_project_rebind=True,
    )


def knowledge_status(root: str) -> dict[str, Any]:
    context = WorkspaceContext.resolve(root)
    warnings: list[str] = []
    skill_provider = BundledSkillProvider()
    memory_provider = BundledMemoryProvider()
    company_provider = BundledCompanyProvider()
    skills = skill_provider.status(context)
    if context.memory_enabled:
        try:
            memory = memory_provider.status(context)
            if memory.get("warning"):
                warnings.append(f"memory: {memory['warning']}")
        except Exception as exc:
            memory = {"available": False, "pending": 0, "warning": str(exc)}
            warnings.append(f"memory: {exc}")
    else:
        memory = {"available": False, "enabled": False, "pending": 0}
    if context.company_enabled:
        try:
            company = company_provider.status(context)
            if company.get("warning"):
                warnings.append(f"company: {company['warning']}")
        except Exception as exc:
            company = {"available": False, "warning": str(exc)}
            warnings.append(f"company: {exc}")
    else:
        company = {"available": False, "enabled": False}
    snapshot = memory_snapshot_status(context) if context.memory_enabled else {
        "present": False,
        "valid": False,
        "freshness": "unknown",
        "enabled": False,
    }
    migration_required = (
        context.project.schema_version < WORKSPACE_SCHEMA_VERSION
        or (
            context.company is not None
            and context.company.schema_version < WORKSPACE_SCHEMA_VERSION
        )
    )
    return {
        "root": str(context.project_root),
        "project_id": context.project.project_id,
        "company_id": context.project.company_id,
        "company_root": (
            str(context.company_root) if context.company_root is not None else None
        ),
        "profile": context.project.profile,
        "runtime_version": __version__,
        "workspace_schema_version": context.project.schema_version,
        "compatible": not migration_required,
        "migration_required": migration_required,
        "company_registered": context.company is not None,
        "skills": skills,
        "memory": memory,
        "memory_snapshot": snapshot,
        "company": company,
        "warnings": warnings,
    }


def recall_context(
    query: str,
    root: str,
    limit: int = 8,
    include_skills: bool = True,
    include_memory: bool = True,
    include_company: bool = True,
    include_sensitive_memory: bool = False,
) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    context = WorkspaceContext.resolve(root)
    require_current_workspace_schema(context, "context recall")
    bounded = _bounded_limit(limit)
    warnings: list[str] = []
    skills: dict[str, Any] = {"included": include_skills, "available": False, "results": []}
    memory: dict[str, Any] = {"included": include_memory, "available": False, "results": []}
    company: dict[str, Any] = {
        "included": include_company,
        "available": False,
        "evidence_sufficient": False,
        "insufficient_evidence": bool(include_company),
        "results": [],
    }
    if include_skills:
        try:
            skills.update(BundledSkillProvider().search(context, query.strip(), bounded))
        except Exception as exc:
            warnings.append(f"skills: {exc}")
    if include_memory and context.memory_enabled:
        try:
            memory.update(BundledMemoryProvider().search(context, query.strip(), bounded, include_sensitive_memory))
        except Exception as exc:
            warnings.append(f"memory: {exc}")
    if include_company and context.company_enabled:
        try:
            company.update(BundledCompanyProvider().search(context, query.strip(), bounded))
            if company.get("warning"):
                warnings.append(f"company: {company['warning']}")
        except Exception as exc:
            warnings.append(f"company: {exc}")
    return {
        "query": query.strip(),
        "root": str(context.project_root),
        "project_id": context.project.project_id,
        "company_id": context.project.company_id,
        "skills": skills,
        "memory": memory,
        "company": company,
        "evidence_sufficient": bool(company.get("evidence_sufficient")),
        "insufficient_evidence": bool(include_company and context.company_enabled and not company.get("evidence_sufficient")),
        "warnings": warnings,
    }


def capture_memory(
    root: str,
    kind: MemoryKind,
    title: str,
    text: str,
    memory_key: str,
    event_id: str | None = None,
    tags: list[str] | None = None,
    importance: float = 0.7,
    pinned: bool = False,
    supersedes: list[str] | None = None,
) -> dict[str, Any]:
    context = WorkspaceContext.resolve(root)
    require_current_workspace_schema(context, "memory capture")
    if not context.memory_enabled:
        raise ValueError("memory is disabled by this project's profile")
    payload: dict[str, Any] = {
        "kind": kind,
        "title": title,
        "text": text,
        "memory_key": memory_key,
        "tags": tags or [],
        "importance": importance,
        "pinned": pinned,
        "supersedes": supersedes or [],
        "source": "mcp:local-knowledge",
    }
    if event_id is not None:
        payload["id"] = event_id
    result = BundledMemoryProvider().capture(context, payload)
    return {
        **result,
        "project_id": context.project.project_id,
        "company_id": context.project.company_id,
    }


def doctor_workspace(root: str) -> dict[str, Any]:
    from .doctor import doctor_workspace as run_doctor

    return run_doctor(root)


def migrate_workspace(root: str, dry_run: bool = True) -> dict[str, Any]:
    from .migrations import migrate_workspace as run_migration

    return run_migration(root, dry_run=dry_run)
