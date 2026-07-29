# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import argparse
import getpass
import ipaddress
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from ..errors import RegistryError
from ..registry import CompanyRegistry
from ..winio import unlink_file
from ..workspace import require_current_company_schema
from .config import Settings
from .db import Database
from .gitops import pull, push, status
from .okf import regenerate_indexes, validate_bundle
from .parsers import ocr_health
from .pipeline import KnowledgeService
from .search import search
from .security import create_user
from .secrets_store import SecretStore
from .worker import run_worker


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ckb", description="Operate the local Company Knowledge Base")
    parser.add_argument(
        "--root",
        required=True,
        help="Explicit absolute root of a current, machine-registered company repository",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Initialize database, bundle, and first administrator")
    init.add_argument("--admin", default="admin")
    init.add_argument("--reset-state", action="store_true", help="Back up and recreate operational state without touching knowledge/ or Git")
    user = commands.add_parser("user-add", help="Create a local user")
    user.add_argument("username")
    user.add_argument("--role", choices=["admin", "reviewer", "reader"], required=True)
    serve = commands.add_parser("serve", help="Run FastAPI and the built React portal")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", default=8000, type=int)
    worker = commands.add_parser("worker", help="Run the ingestion worker")
    worker.add_argument("--once", action="store_true")
    source = commands.add_parser("source-add", help="Register a file, folder, or website source")
    source.add_argument("kind", choices=["file", "folder", "website"])
    source.add_argument("uri")
    source.add_argument("--title")
    source.add_argument("--allow-domain", action="append", default=[])
    source.add_argument("--branch")
    ingest = commands.add_parser("ingest", help="Queue ingestion for a source")
    ingest.add_argument("source_id", type=int)
    run = commands.add_parser("run-job", help="Run one queued job immediately")
    run.add_argument("job_id", type=int)
    query = commands.add_parser("search", help="Search published knowledge")
    query.add_argument("query")
    query.add_argument("--limit", type=int, default=20)
    query.add_argument("--branch")
    commands.add_parser("validate", help="Validate the OKF bundle")
    commands.add_parser("health", help="Check database, LM Studio, OCR, and bundle health")
    commands.add_parser("git-status", help="Show knowledge repository status")
    commands.add_parser("sync", help="Pull the configured Git remote with rebase after safety checks")
    commands.add_parser("push", help="Push the current Git branch")
    return parser


def _password() -> str:
    return getpass.getpass("Password (12+ characters): ")


def canonicalize_loopback_host(raw_host: str) -> str:
    host = raw_host.strip().lower()
    if host == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError(
            "server host must be localhost or a numeric loopback address"
        ) from exc
    if not address.is_loopback:
        raise ValueError(
            "server host must be loopback-only; wildcard, LAN, and remote binds are blocked"
        )
    return address.compressed


def _reset_state(settings: Settings) -> str | None:
    if not settings.database.exists():
        return None
    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"{settings.database.stem}-v1-{stamp}{settings.database.suffix}"
    Database(settings.database).backup_to(backup)
    for suffix in ("", "-wal", "-shm"):
        unlink_file(settings.database.with_name(settings.database.name + suffix))
    return str(backup)


def _registered_company_root(raw_root: str, operation: str) -> tuple[Path, str]:
    candidate = Path(raw_root).expanduser()
    if not candidate.is_absolute():
        raise ValueError("company root must be an explicit absolute Windows path")
    root = candidate.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"company root is not a directory: {root}")
    company = require_current_company_schema(root, operation)
    registered_root = CompanyRegistry().resolve(company.company_id)
    if os.path.normcase(str(registered_root)) != os.path.normcase(str(root)):
        raise RegistryError(
            f"registry root mismatch for company {company.company_id}: "
            f"registered={registered_root}, requested={root}"
        )
    return root, company.company_id


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    serve_host = (
        canonicalize_loopback_host(args.host)
        if args.command == "serve"
        else None
    )
    root, company_id = _registered_company_root(
        args.root,
        f"ckb {args.command}",
    )
    settings = Settings.for_company(root, company_id)
    settings.ensure_directories()
    backup = _reset_state(settings) if args.command == "init" and args.reset_state else None
    db = Database(settings.database)
    db.initialize()
    service = KnowledgeService(settings, db=db)
    if args.command == "init":
        regenerate_indexes(settings.bundle_dir)
        settings.write_user_config()
        with db.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count:
            print("Database and OKF bundle initialized; users already exist.")
        else:
            user_id = create_user(db, args.admin, _password(), "admin")
            imported = service.rebuild_from_bundle()
            message = f"Initialized {settings.root} with administrator #{user_id} ({args.admin}); imported {imported} legacy concepts."
            if backup:
                message += f" Previous state backed up to {backup}."
            print(message)
        return 0
    if args.command == "user-add":
        user_id = create_user(db, args.username, _password(), args.role)
        print(json.dumps({"id": user_id, "username": args.username, "role": args.role}))
        return 0
    if args.command == "serve":
        import uvicorn
        from .api import create_app

        assert serve_host is not None
        uvicorn.run(create_app(settings), host=serve_host, port=args.port)
        return 0
    if args.command == "worker":
        print(json.dumps({"processed": run_worker(service, once=args.once)}))
        return 0
    if args.command == "source-add":
        source_id = service.add_source(args.kind, args.uri, args.title, args.allow_domain, None, args.branch)
        print(json.dumps({"id": source_id}))
        return 0
    if args.command == "ingest":
        print(json.dumps({"job_id": service.enqueue(args.source_id, None)}))
        return 0
    if args.command == "run-job":
        print(json.dumps(service.run_job(args.job_id), ensure_ascii=False, indent=2))
        return 0
    if args.command == "search":
        branch_id = service.branch_id(args.branch)
        print(json.dumps(search(db, args.query, args.limit, service.lm, branch_id=branch_id), ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate":
        failures = validate_bundle(settings.bundle_dir)
        print(json.dumps(failures, ensure_ascii=False, indent=2))
        return 1 if failures else 0
    if args.command == "health":
        with db.connect() as connection:
            database_ok = connection.execute("SELECT 1").fetchone()[0] == 1
        lm_health = service.lm.health()
        secret_health = SecretStore(db, settings.keyring_service).health()
        bundle_validation = validate_bundle(settings.bundle_dir)
        secrets_ready = bool(secret_health.get("available")) or not secret_health.get("configured")
        ready = database_ok and bool(lm_health.get("reachable")) and bool(lm_health.get("chat_endpoint")) and secrets_ready and not bundle_validation
        print(json.dumps({
            "status": "ok" if ready else "degraded",
            "database": database_ok,
            "lm_studio": lm_health,
            "ocr": ocr_health(),
            "secrets": secret_health,
            "okf": bundle_validation,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "git-status":
        print(json.dumps(status(settings.root), ensure_ascii=False, indent=2))
        return 0
    if args.command == "sync":
        result = pull(settings.root)
        result["rebuilt_concepts"] = service.rebuild_from_bundle()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "push":
        push(settings.root)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
