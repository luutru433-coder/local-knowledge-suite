# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import WORKSPACE_SCHEMA_VERSION, __version__
from .ckb.db import Database
from .memory_snapshot import memory_snapshot_status
from .memorizer import core as memory_core
from .workspace import WorkspaceContext


def doctor_workspace(root: str) -> dict[str, Any]:
    """Perform read-only compatibility, isolation, and store-health checks."""

    checks: list[dict[str, Any]] = []
    try:
        context = WorkspaceContext.resolve(root)
    except Exception as exc:
        return {
            "ok": False,
            "runtime_version": __version__,
            "checks": [{"name": "workspace-context", "ok": False, "detail": str(exc)}],
        }
    checks.append({"name": "project-manifest", "ok": True, "detail": str(context.project_root)})
    checks.append({
        "name": "schema-compatibility",
        "ok": (
            context.project.schema_version == WORKSPACE_SCHEMA_VERSION
            and (
                context.company is None
                or context.company.schema_version == WORKSPACE_SCHEMA_VERSION
            )
        ),
        "detail": {
            "runtime": WORKSPACE_SCHEMA_VERSION,
            "project": context.project.schema_version,
            "company": (
                context.company.schema_version if context.company is not None else None
            ),
        },
    })
    checks.append(
        {
            "name": "company-registry",
            "ok": context.company is not None or not context.company_enabled,
            "detail": {
                "enabled": context.company_enabled,
                "company_id": context.project.company_id,
                "root": (
                    str(context.company_root)
                    if context.company_root is not None
                    else None
                ),
            },
        }
    )
    if context.memory_enabled:
        if context.memory_root.is_dir():
            try:
                validation = memory_core.validate_vault(context.project_root)
                checks.append({
                    "name": "memory-vault",
                    "ok": bool(validation.get("valid", False)),
                    "detail": validation,
                })
            except Exception as exc:
                checks.append({"name": "memory-vault", "ok": False, "detail": str(exc)})
        else:
            checks.append({"name": "memory-vault", "ok": False, "detail": "not initialized"})
        snapshot = memory_snapshot_status(context)
        checks.append(
            {
                "name": "memory-snapshot",
                "ok": (
                    not snapshot.get("present")
                    or (
                        bool(snapshot.get("valid"))
                        and bool(snapshot.get("project_id_matches"))
                    )
                ),
                "detail": snapshot,
            }
        )
    if context.company_enabled:
        assert context.company_database is not None
        assert context.company_bundle_dir is not None
        if context.company_database.is_file():
            try:
                with Database(context.company_database).connect() as connection:
                    connection.execute("SELECT 1").fetchone()
                checks.append({"name": "company-database", "ok": True, "detail": str(context.company_database)})
            except Exception as exc:
                checks.append({"name": "company-database", "ok": False, "detail": str(exc)})
        else:
            checks.append({"name": "company-database", "ok": False, "detail": "not initialized"})
        checks.append({
            "name": "company-bundle",
            "ok": context.company_bundle_dir.is_dir(),
            "detail": str(context.company_bundle_dir),
        })
    vendored = context.project.install_mode == "vendored"
    vendor_path = context.project_root / "tools" / "local-knowledge-suite"
    checks.append({
        "name": "runtime-installation",
        "ok": not vendored or vendor_path.is_dir(),
        "detail": "global" if not vendored else str(vendor_path),
    })
    return {
        "ok": all(bool(check["ok"]) for check in checks),
        "root": str(context.project_root),
        "project_id": context.project.project_id,
        "company_id": context.project.company_id,
        "runtime_version": __version__,
        "checks": checks,
    }
