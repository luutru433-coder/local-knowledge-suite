# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import WORKSPACE_SCHEMA_VERSION
from .ckb.gitops import (
    COMPANY_PRIVATE_TRACKED_PATHS,
    PROJECT_PRIVATE_TRACKED_PATHS,
    reject_tracked_private_paths,
)
from .manifests import CompanyManifest, ProjectManifest
from .registry import CompanyRegistry
from .errors import CompatibilityError, LocalKnowledgeError
from .winio import reject_reparse_points


UNSAFE_PROCESS_STORAGE_OVERRIDES = (
    "CKB_ROOT",
    "CKB_DATA_DIR",
    "CKB_DATABASE",
    "CKB_BUNDLE_DIR",
)


def reject_process_storage_overrides() -> None:
    active = [name for name in UNSAFE_PROCESS_STORAGE_OVERRIDES if os.environ.get(name)]
    if active:
        joined = ", ".join(active)
        raise LocalKnowledgeError(
            f"project-scoped local knowledge refuses process-wide storage override(s): {joined}. "
            "Unset them and pass the absolute project root explicitly."
        )


def resolve_project_root(raw_root: str | Path) -> Path:
    reject_process_storage_overrides()
    candidate = Path(raw_root).expanduser()
    if not candidate.is_absolute():
        raise ValueError("root must be an absolute Windows path")
    return candidate.resolve(strict=True)


def _within(child: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((os.path.normcase(str(child)), os.path.normcase(str(parent)))) == os.path.normcase(str(parent))
    except ValueError:
        return False


def require_current_company_schema(
    root: str | Path,
    operation: str,
) -> CompanyManifest:
    company = CompanyManifest.load(root)
    if company.schema_version != WORKSPACE_SCHEMA_VERSION:
        raise CompatibilityError(
            f"{operation} is blocked because company {company.company_id} uses schema "
            f"{company.schema_version}; runtime requires {WORKSPACE_SCHEMA_VERSION}, "
            "so migration is required. "
            "Register the company if needed, then run `local-knowledge migrate --root "
            "PROJECT_ROOT --apply` from a bound project."
        )
    return company


def require_current_workspace_schema(
    context: "WorkspaceContext",
    operation: str,
) -> None:
    stale: list[str] = []
    if context.project.schema_version != WORKSPACE_SCHEMA_VERSION:
        stale.append(f"project={context.project.schema_version}")
    if (
        context.company is not None
        and context.company.schema_version != WORKSPACE_SCHEMA_VERSION
    ):
        stale.append(f"company={context.company.schema_version}")
    if stale:
        raise CompatibilityError(
            f"{operation} is blocked until migration completes "
            f"({', '.join(stale)}; runtime={WORKSPACE_SCHEMA_VERSION}). "
            "Run `local-knowledge migrate --root PROJECT_ROOT --apply`."
        )


@dataclass(frozen=True, slots=True)
class WorkspaceContext:
    project_root: Path
    project: ProjectManifest
    company_root: Path | None
    company: CompanyManifest | None
    memory_root: Path
    company_data_dir: Path | None
    company_database: Path | None
    company_bundle_dir: Path | None

    @property
    def memory_enabled(self) -> bool:
        return self.project.profile in {"combined", "memory-only"}

    @property
    def company_enabled(self) -> bool:
        return self.project.profile in {"combined", "company-only"}

    @classmethod
    def resolve(
        cls,
        root: str | Path,
        registry: CompanyRegistry | None = None,
        *,
        require_company_authorization: bool = True,
    ) -> "WorkspaceContext":
        project_root = resolve_project_root(root)
        reject_tracked_private_paths(
            project_root,
            PROJECT_PRIVATE_TRACKED_PATHS,
            label="project repository",
            require_own_repository=False,
        )
        reject_reparse_points(project_root / ".local-knowledge", "project .local-knowledge directory")
        project = ProjectManifest.load(project_root)
        reject_reparse_points(project_root / ".memorizer", "project memory store")
        memory_root = (project_root / project.memory_path).resolve()
        if not _within(memory_root, project_root):
            raise ValueError("resolved memory path escapes the project root")
        company_root: Path | None = None
        company: CompanyManifest | None = None
        company_data_dir: Path | None = None
        company_bundle_dir: Path | None = None
        company_database: Path | None = None
        if project.profile in {"combined", "company-only"}:
            if project.company_id is None:
                raise LocalKnowledgeError(
                    f"profile {project.profile} requires a registered company_id"
                )
            active_registry = registry or CompanyRegistry()
            # Keep authorization and company resolution in one registry
            # transaction so an unregister/re-register cannot switch the
            # repository between the two checks.
            with active_registry.mutation_guard():
                if require_company_authorization:
                    active_registry.assert_project_authorized(
                        project_root,
                        project.project_id,
                        project.company_id,
                    )
                company_root = active_registry.resolve(project.company_id)
            reject_tracked_private_paths(
                company_root,
                COMPANY_PRIVATE_TRACKED_PATHS,
                label="company repository",
                require_own_repository=True,
            )
            reject_reparse_points(
                company_root / ".local-knowledge",
                "company .local-knowledge directory",
            )
            reject_reparse_points(company_root / ".ckb", "company database store")
            reject_reparse_points(company_root / "knowledge", "company knowledge store")
            company = CompanyManifest.load(company_root)
            company_data_dir = (company_root / ".ckb").resolve()
            company_bundle_dir = (company_root / "knowledge").resolve()
            if not _within(company_data_dir, company_root) or not _within(
                company_bundle_dir, company_root
            ):
                raise ValueError(
                    "company storage paths must remain inside the registered company root"
                )
            company_database = company_data_dir / "ckb.sqlite3"
        return cls(
            project_root=project_root,
            project=project,
            company_root=company_root,
            company=company,
            memory_root=memory_root,
            company_data_dir=company_data_dir,
            company_database=company_database,
            company_bundle_dir=company_bundle_dir,
        )
