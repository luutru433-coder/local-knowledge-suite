# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Any

from .ckb import cli as ckb_cli
from .ckb.config import Settings
from .ckb.db import Database
from .ckb.security import create_user
from .doctor import doctor_workspace
from .errors import LocalKnowledgeError
from .migrations import migrate_workspace
from .memory_snapshot import export_memory_snapshot, import_memory_snapshot
from .registry import CompanyRegistry
from .services import (
    bootstrap_workspace,
    initialize_company_repository,
    knowledge_status,
    register_company,
    restore_workspace,
    unregister_company,
)
from .workspace import require_current_company_schema


CKB_OPERATIONS = {
    "user-add",
    "worker",
    "source-add",
    "ingest",
    "run-job",
    "search",
    "validate",
    "health",
    "git-status",
    "sync",
    "push",
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="local-knowledge", description="Manage portable local knowledge on Windows")
    groups = parser.add_subparsers(dest="group", required=True)

    company = groups.add_parser(
        "company",
        help="Create, register, unregister, serve, or operate a company knowledge repository",
    )
    companies = company.add_subparsers(dest="command", required=True)
    company_init = companies.add_parser("init", help="Initialize and register a company repository")
    company_init.add_argument("--root", required=True)
    company_init.add_argument("--name", required=True)
    company_init.add_argument("--id", dest="company_id")
    company_init.add_argument("--admin", default="admin")
    company_register = companies.add_parser("register", help="Register an existing company repository on this Windows user account")
    company_register.add_argument("--root", required=True)
    company_register.add_argument("--admin", help="Create this administrator interactively when the cloned repository has no users")
    company_unregister = companies.add_parser(
        "unregister",
        help="Remove one verified machine-local company mapping without deleting its repository",
    )
    company_unregister.add_argument(
        "--root",
        required=True,
        help="Absolute path to the existing company repository",
    )
    company_unregister.add_argument(
        "--purge-credential-key",
        action="store_true",
        help="Irreversibly delete only this company's OS-keyring master key",
    )
    company_unregister.add_argument(
        "--confirm-company",
        metavar="COMPANY_ID",
        help="Exact company ID required with --purge-credential-key",
    )
    companies.add_parser("list", help="List locally registered companies")
    company_serve = companies.add_parser("serve", help="Serve the CKB API and packaged portal")
    company_serve.add_argument("--company", required=True)
    company_serve.add_argument("--host", default="127.0.0.1")
    company_serve.add_argument("--port", type=int, default=8000)

    project = groups.add_parser("project", help="Initialize or inspect a code project")
    projects = project.add_subparsers(dest="command", required=True)
    project_init = projects.add_parser(
        "init",
        help="Initialize project memory or bind a project to registered company knowledge",
    )
    project_init.add_argument("--root", required=True)
    project_init.add_argument("--company")
    project_init.add_argument(
        "--profile",
        choices=("combined", "memory-only", "company-only"),
        default="memory-only",
    )
    project_init.add_argument("--install-mode", choices=("global", "vendored"), default="global")
    project_doctor = projects.add_parser("doctor", help="Run read-only project diagnostics")
    project_doctor.add_argument("--root", required=True)
    project_status = projects.add_parser("status", help="Show project knowledge status")
    project_status.add_argument("--root", required=True)
    project_restore = projects.add_parser("restore", help="Recreate ignored local state after cloning an initialized project")
    project_restore.add_argument("--root", required=True)

    memory = groups.add_parser(
        "memory",
        help="Export or import a deterministic text-only project-memory snapshot",
    )
    memories = memory.add_subparsers(dest="command", required=True)
    memory_export = memories.add_parser(
        "export",
        help="Export source notes with checksums; derived indexes are excluded",
    )
    memory_export.add_argument("--root", required=True)
    memory_export.add_argument("--output", required=True)
    memory_export.add_argument(
        "--git-visibility",
        choices=("private", "public"),
        default="private",
    )
    memory_export.add_argument("--include-sensitive", action="store_true")
    memory_export.add_argument("--acknowledge-sensitive", action="store_true")
    memory_export.add_argument("--allow-public", action="store_true")
    memory_import = memories.add_parser(
        "import",
        help="Import a matching snapshot into an empty vault",
    )
    memory_import.add_argument("--root", required=True)
    memory_import.add_argument("--input", required=True)
    memory_import.add_argument(
        "--replace",
        action="store_true",
        help="Back up and replace a non-empty local vault",
    )

    migrate = groups.add_parser("migrate", help="Plan or apply a safe project/company schema migration")
    migrate.add_argument("--root", required=True)
    mode = migrate.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Show actions without writing (default)")
    mode.add_argument("--apply", action="store_true", help="Back up and apply migrations")
    return parser


def _extract_company(rest: list[str]) -> tuple[str, list[str]]:
    try:
        index = rest.index("--company")
        identifier = rest[index + 1]
    except (ValueError, IndexError) as exc:
        raise ValueError("company operation requires --company COMPANY_ID") from exc
    return identifier, [*rest[:index], *rest[index + 2 :]]


def _delegate_company(argv: list[str]) -> int | None:
    if len(argv) < 2 or argv[0] != "company" or argv[1] not in CKB_OPERATIONS:
        return None
    identifier, rest = _extract_company(argv[2:])
    root = CompanyRegistry().resolve(identifier)
    return ckb_cli.main(["--root", str(root), argv[1], *rest])


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _create_interactive_administrator(result: dict[str, Any], username: str) -> dict[str, Any]:
    settings = Settings.for_company(result["root"], result["company_id"])
    database = Database(settings.database)
    with database.connect() as connection:
        existing = connection.execute("SELECT id,username,role FROM users ORDER BY id LIMIT 1").fetchone()
    if existing is not None:
        return {**dict(existing), "created": False}
    password = getpass.getpass("Administrator password (12+ characters): ")
    confirmation = getpass.getpass("Confirm administrator password: ")
    if password != confirmation:
        raise ValueError("password confirmation does not match")
    user_id = create_user(database, username, password, "admin")
    return {"id": user_id, "username": username, "role": "admin", "created": True}


def _run(args: argparse.Namespace) -> int:
    if args.group == "company" and args.command == "init":
        result = initialize_company_repository(args.root, args.name, args.company_id)
        result["administrator"] = _create_interactive_administrator(result, args.admin)
        _print(result)
        return 0
    if args.group == "company" and args.command == "register":
        result = register_company(args.root)
        if result["requires_administrator"] and args.admin:
            result["administrator"] = _create_interactive_administrator(
                {**result, "root": result["root"]},
                args.admin,
            )
            result["requires_administrator"] = False
            result["users"] = 1
        elif result["requires_administrator"]:
            result["warning"] = "no company user exists; rerun company register with --admin USERNAME"
        _print(result)
        return 0
    if args.group == "company" and args.command == "unregister":
        result = unregister_company(
            args.root,
            purge_credential_key=bool(args.purge_credential_key),
            confirm_company=args.confirm_company,
        )
        _print(result)
        return 0 if result["ok"] else 1
    if args.group == "company" and args.command == "list":
        _print({"companies": CompanyRegistry().list()})
        return 0
    if args.group == "company" and args.command == "serve":
        host = ckb_cli.canonicalize_loopback_host(args.host)
        import uvicorn
        from .ckb.api import create_app

        root = CompanyRegistry().resolve(args.company)
        require_current_company_schema(root, "company portal server")
        manifest_id = args.company.strip().lower()
        uvicorn.run(
            create_app(Settings.for_company(root, manifest_id)),
            host=host,
            port=args.port,
        )
        return 0
    if args.group == "project" and args.command == "init":
        _print(bootstrap_workspace(args.root, args.company, args.profile, args.install_mode))
        return 0
    if args.group == "project" and args.command == "doctor":
        result = doctor_workspace(args.root)
        _print(result)
        return 0 if result.get("ok") else 1
    if args.group == "project" and args.command == "status":
        _print(knowledge_status(args.root))
        return 0
    if args.group == "project" and args.command == "restore":
        _print(restore_workspace(args.root))
        return 0
    if args.group == "memory" and args.command == "export":
        _print(
            export_memory_snapshot(
                args.root,
                args.output,
                git_visibility=args.git_visibility,
                include_sensitive=bool(args.include_sensitive),
                acknowledge_sensitive=bool(args.acknowledge_sensitive),
                allow_public=bool(args.allow_public),
            )
        )
        return 0
    if args.group == "memory" and args.command == "import":
        _print(
            import_memory_snapshot(
                args.root,
                args.input,
                replace=bool(args.replace),
            )
        )
        return 0
    if args.group == "migrate":
        _print(migrate_workspace(args.root, apply=bool(args.apply)))
        return 0
    return 2


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        delegated = _delegate_company(arguments)
        if delegated is not None:
            return delegated
        return _run(_parser().parse_args(arguments))
    except (LocalKnowledgeError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
