# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import WORKSPACE_SCHEMA_VERSION
from .ckb.db import SCHEMA_VERSION as CKB_SCHEMA_VERSION
from .ckb.db import Database
from .manifests import (
    COMPANY_MANIFEST,
    PROJECT_MANIFEST,
    replace_company_manifest,
    replace_project_manifest,
)
from .winio import unlink_file
from .workspace import WorkspaceContext


def migrate_workspace(
    root: str,
    dry_run: bool = True,
    *,
    apply: bool | None = None,
) -> dict[str, Any]:
    """Plan or apply idempotent schema upgrades with on-disk backups."""

    # Migration is itself an explicit, approved lifecycle action. It must be
    # able to inspect a legacy clone before that clone is locally re-enrolled;
    # normal status/recall/capture paths keep the authorization gate enabled.
    context = WorkspaceContext.resolve(
        root,
        require_company_authorization=False,
    )
    should_apply = bool(apply) if apply is not None else not dry_run
    actions: list[dict[str, Any]] = []
    project_upgrade_required = (
        context.project.schema_version < WORKSPACE_SCHEMA_VERSION
    )
    company_upgrade_required = (
        context.company is not None
        and context.company.schema_version < WORKSPACE_SCHEMA_VERSION
    )
    database = (
        Database(context.company_database)
        if context.company_database is not None
        else None
    )
    database_upgrade_required = False
    database_version: int | None = None
    if (
        company_upgrade_required
        and database is not None
        and context.company_database is not None
        and context.company_database.is_file()
    ):
        database_version = database.assert_compatible()
        database_upgrade_required = database_version < CKB_SCHEMA_VERSION

    if project_upgrade_required:
        actions.append({
            "store": "project-manifest",
            "from": context.project.schema_version,
            "to": WORKSPACE_SCHEMA_VERSION,
        })
    if company_upgrade_required:
        assert context.company is not None
        actions.append({
            "store": "company-manifest",
            "from": context.company.schema_version,
            "to": WORKSPACE_SCHEMA_VERSION,
        })
    if database_upgrade_required:
        assert context.company_database is not None
        assert database_version is not None
        actions.append({
            "store": "company-database",
            "action": "upgrade",
            "path": str(context.company_database),
            "from": database_version,
            "to": CKB_SCHEMA_VERSION,
        })
    if not should_apply:
        return {
            "ok": True,
            "applied": False,
            "root": str(context.project_root),
            "company_id": context.project.company_id,
            "actions": actions,
        }
    if not actions:
        return {
            "ok": True,
            "applied": False,
            "noop": True,
            "root": str(context.project_root),
            "company_id": context.project.company_id,
            "actions": [],
            "backups": [],
        }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    project_backup_dir = context.project_root / ".local-knowledge" / "backups" / stamp
    company_backup_dir = (
        context.company_data_dir / "backups" / stamp
        if context.company_data_dir is not None
        else None
    )
    backups: list[str] = []
    database_backup: Path | None = None
    try:
        if project_upgrade_required:
            project_backup_dir.mkdir(parents=True, exist_ok=False)
            project_manifest_path = context.project_root / PROJECT_MANIFEST
            project_backup = project_backup_dir / "project.toml"
            shutil.copy2(project_manifest_path, project_backup)
            backups.append(str(project_backup))
        if company_upgrade_required or database_upgrade_required:
            assert company_backup_dir is not None
            company_backup_dir.mkdir(parents=True, exist_ok=False)
        if company_upgrade_required:
            assert context.company_root is not None
            assert company_backup_dir is not None
            company_manifest_path = context.company_root / COMPANY_MANIFEST
            company_manifest_backup = company_backup_dir / "company.toml"
            shutil.copy2(company_manifest_path, company_manifest_backup)
            backups.append(str(company_manifest_backup))
        if (
            database_upgrade_required
            and database is not None
            and context.company_database is not None
            and context.company_database.is_file()
            and company_backup_dir is not None
        ):
            database_backup = company_backup_dir / context.company_database.name
            database.backup_to(database_backup)
            backups.append(str(database_backup))
        if database_upgrade_required and database is not None:
            database.initialize()
        if project_upgrade_required:
            replace_project_manifest(
                context.project_root,
                replace(context.project, schema_version=WORKSPACE_SCHEMA_VERSION),
            )
        if company_upgrade_required:
            assert context.company is not None
            assert context.company_root is not None
            replace_company_manifest(
                context.company_root,
                replace(context.company, schema_version=WORKSPACE_SCHEMA_VERSION),
            )
    except Exception:
        project_backup = project_backup_dir / "project.toml"
        if project_upgrade_required and project_backup.is_file():
            shutil.copy2(project_backup, context.project_root / PROJECT_MANIFEST)
        company_manifest_backup = (
            company_backup_dir / "company.toml"
            if company_backup_dir is not None
            else None
        )
        if (
            company_upgrade_required
            and company_manifest_backup is not None
            and company_manifest_backup.is_file()
            and context.company_root is not None
        ):
            shutil.copy2(
                company_manifest_backup,
                context.company_root / COMPANY_MANIFEST,
            )
        if (
            database_upgrade_required
            and database is not None
            and database_backup is not None
            and database_backup.is_file()
        ):
            database.restore_from(database_backup)
        elif database_upgrade_required and context.company_database is not None:
            for suffix in ("", "-wal", "-shm"):
                unlink_file(
                    context.company_database.with_name(
                        context.company_database.name + suffix
                    )
                )
        raise
    return {
        "ok": True,
        "applied": True,
        "root": str(context.project_root),
        "company_id": context.project.company_id,
        "actions": actions,
        "backups": backups,
    }
