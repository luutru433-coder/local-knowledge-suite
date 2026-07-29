# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import traceback
import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from .config import Settings
from .db import Database
from .gitops import GitOperationError, checkout_canonical, find_publication_commit, merge_candidate, publish_candidate, publish_markdown
from .lmstudio import LMStudioClient
from .models import CitationLocator, ClaimDraft, ParsedSection, SourceDocument
from .okf import (
    concept_integrity_valid,
    parse_frontmatter,
    quality_report,
    quality_to_json,
    render_concept,
    slugify,
    validate_concept_text,
)
from .parsers import (
    chunk_sections,
    crawl_public,
    iter_supported_files,
    normalize_crawl_domains,
    parse_path,
)
from .search import fold_vietnamese, index_concept, recompute_value_graph
from .secrets_store import SecretStore, SecretStoreError
from ..manifests import CompanyManifest
from ..registry import CompanyRegistry
from ..winio import reject_reparse_points, reject_reparse_traversal
from .executables import ExecutableResolutionError, resolve_trusted_executable


MEDIA_TYPES = {
    "application/pdf": "Reference",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Spreadsheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "Presentation",
    "message/rfc822": "Email",
    "text/html": "Web Page",
    "text/markdown": "Reference",
    "text/plain": "Reference",
}

PRIVATE_LOCAL_SOURCE_PARTS = {
    ".ckb",
    ".git",
    ".local-knowledge",
    ".memorizer",
    "knowledge",
}


def _clean_tracked_head(repo: Path, concept_path: Path) -> bool:
    try:
        relative = concept_path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return False
    try:
        git_executable = resolve_trusted_executable(
            "git",
            untrusted_roots=(repo, Path.cwd()),
        )
    except ExecutableResolutionError:
        return False
    commands = (
        ("rev-parse", "--verify", "HEAD"),
        ("ls-files", "--error-unmatch", "--", relative),
        ("status", "--porcelain=v1", "--untracked-files=all"),
    )
    for args in commands:
        result = subprocess.run(
            [str(git_executable), *args],
            cwd=repo,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
        )
        if result.returncode or (args[0] == "status" and result.stdout.strip()):
            return False
    return True


class JobCancelled(RuntimeError):
    pass


class LeaseLost(RuntimeError):
    pass


class KnowledgeService:
    def __init__(self, settings: Settings, db: Database | None = None, lm_client: LMStudioClient | None = None):
        self.settings = settings
        self.settings.ensure_directories()
        self.db = db or Database(settings.database)
        self.db.initialize()
        self.lm = lm_client or LMStudioClient(settings.lm_studio_url, settings.chat_model, settings.embedding_model)
        self.secrets = SecretStore(self.db, settings.keyring_service)
        self._ensure_canonical_branch()
        self.recover_publications()

    def _ensure_canonical_branch(self) -> int:
        with self.db.transaction(immediate=True) as connection:
            connection.execute("UPDATE branches SET is_canonical=0 WHERE name<>?", (self.settings.canonical_branch,))
            connection.execute(
                "INSERT INTO branches(name,is_canonical,protected) VALUES(?,1,1) "
                "ON CONFLICT(name) DO UPDATE SET is_canonical=1,protected=1",
                (self.settings.canonical_branch,),
            )
            return int(connection.execute("SELECT id FROM branches WHERE name=?", (self.settings.canonical_branch,)).fetchone()["id"])

    def branch_id(self, name: str | None = None) -> int:
        branch = name or self.settings.canonical_branch
        with self.db.connect() as connection:
            row = connection.execute("SELECT id FROM branches WHERE name=?", (branch,)).fetchone()
        if row is None:
            raise ValueError("branch not found")
        return int(row["id"])

    def create_branch(self, name: str, user_id: int | None) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,120}", name) or name.startswith(("/", "-")) or ".." in name:
            raise ValueError("invalid branch name")
        with self.db.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "INSERT INTO branches(name,is_canonical,protected,created_by) VALUES(?,0,1,?)",
                (name, user_id),
            )
            branch_id = int(cursor.lastrowid)
            if user_id is not None:
                connection.execute("INSERT INTO branch_members(branch_id,user_id,role) VALUES(?,?,'admin')", (branch_id, user_id))
        self.audit(user_id, branch_id, "branch.create", "branch", str(branch_id), "succeeded", {"name": name})
        return {"id": branch_id, "name": name, "is_canonical": False, "protected": True}

    def set_branch_member(self, branch_id: int, user_id: int, role: str, actor_id: int | None) -> None:
        if role not in {"admin", "reviewer", "reader"}:
            raise ValueError("invalid branch role")
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO branch_members(branch_id,user_id,role) VALUES(?,?,?) "
                "ON CONFLICT(branch_id,user_id) DO UPDATE SET role=excluded.role",
                (branch_id, user_id, role),
            )
        self.audit(actor_id, branch_id, "branch.member.set", "user", str(user_id), "succeeded", {"role": role})

    def branch_role(self, user: dict[str, Any], branch_id: int) -> str | None:
        if user["role"] == "admin":
            return "admin"
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT role FROM branch_members WHERE branch_id=? AND user_id=?",
                (branch_id, user["id"]),
            ).fetchone()
        return str(row["role"]) if row else None

    def audit(
        self,
        user_id: int | None,
        branch_id: int | None,
        action: str,
        target_type: str | None,
        target_id: str | None,
        outcome: str,
        details: dict[str, Any] | None = None,
        publication_id: str | None = None,
        commit_hash: str | None = None,
    ) -> None:
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO audits(user_id,branch_id,action,target_type,target_id,publication_id,commit_hash,outcome,details_json) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (user_id, branch_id, action, target_type, target_id, publication_id, commit_hash, outcome, json.dumps(details or {}, ensure_ascii=False)),
            )

    def add_source(
        self,
        kind: str,
        uri: str,
        title: str | None,
        allowed_domains: list[str],
        user_id: int | None,
        branch: str | None = None,
    ) -> int:
        if kind not in {"file", "folder", "website"}:
            raise ValueError("invalid source kind")
        if kind in {"file", "folder"}:
            candidate = self._validate_local_source(kind, uri)
            uri = str(candidate)
        else:
            allowed_domains = sorted(normalize_crawl_domains(allowed_domains))
        branch_id = self.branch_id(branch)
        with self.db.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "INSERT INTO sources(kind,uri,title,allowed_domains,created_by,branch_id) VALUES(?,?,?,?,?,?)",
                (kind, uri, title, json.dumps(allowed_domains), user_id, branch_id),
            )
            return int(cursor.lastrowid)

    @staticmethod
    def _is_within(candidate: Path, parent: Path) -> bool:
        try:
            return os.path.commonpath(
                (os.path.normcase(str(candidate)), os.path.normcase(str(parent)))
            ) == os.path.normcase(str(parent))
        except ValueError:
            return False

    def _validate_local_source(self, kind: str, uri: str | Path) -> Path:
        candidate_input = Path(uri).expanduser()
        if not candidate_input.is_absolute():
            raise ValueError("local file and folder sources must use an absolute path")

        source_root_input = self.settings.root / ".local-sources"
        source_root_input.mkdir(parents=True, exist_ok=True)
        source_root_lexical = Path(os.path.abspath(source_root_input))
        candidate_lexical = Path(os.path.abspath(candidate_input))
        if not self._is_within(candidate_lexical, source_root_lexical):
            raise ValueError(
                f"local sources must stay inside the company allowlist root: {source_root_lexical}"
            )

        # Check only the selected lexical traversal here. Folder sources receive
        # one complete descendant scan below; individual files remain O(depth).
        reject_reparse_traversal(
            source_root_lexical,
            candidate_lexical,
            "company local source allowlist",
        )
        source_root = source_root_lexical.resolve(strict=True)
        candidate = candidate_input.resolve(strict=True)
        if not self._is_within(candidate, source_root):
            raise ValueError("local source escaped the company allowlist through a reparse point")
        if kind == "file" and not candidate.is_file():
            raise ValueError(f"file source does not exist or is not a file: {candidate}")
        if kind == "folder" and not candidate.is_dir():
            raise ValueError(f"folder source does not exist or is not a directory: {candidate}")

        current_root = self.settings.root.resolve()
        for company_id, entry in CompanyRegistry().list().items():
            registered = entry.get("root") if isinstance(entry, dict) else None
            if not isinstance(registered, str):
                continue
            other_root = Path(registered).resolve()
            if os.path.normcase(str(other_root)) == os.path.normcase(str(current_root)):
                continue
            if self._is_within(candidate, other_root) or (
                candidate.is_dir() and self._is_within(other_root, candidate)
            ):
                raise ValueError(
                    f"local source intersects registered company {company_id}; cross-company ingestion is forbidden"
                )

        relative_parts = candidate.relative_to(source_root).parts
        if any(part.casefold() in PRIVATE_LOCAL_SOURCE_PARTS for part in relative_parts):
            raise ValueError("local sources cannot read private, Git, or canonical knowledge stores")
        if candidate.is_dir():
            reject_reparse_points(candidate, "company local source folder")
            for current, directories, files in os.walk(candidate, followlinks=False):
                for name in [*directories, *files]:
                    nested = Path(current) / name
                    relative = nested.relative_to(source_root)
                    if any(part.casefold() in PRIVATE_LOCAL_SOURCE_PARTS for part in relative.parts):
                        raise ValueError(
                            f"local source folder contains a private or canonical store: {nested}"
                        )
        return candidate

    def _company_source_uri(self, path: Path) -> str:
        source_root = (self.settings.root / ".local-sources").resolve(strict=True)
        relative = path.resolve(strict=True).relative_to(source_root)
        encoded_path = "/".join(quote(part, safe="") for part in relative.parts)
        company_id = CompanyManifest.load(self.settings.root).company_id
        return f"company-source://{company_id}/{encoded_path}"

    def enqueue(self, source_id: int, user_id: int | None) -> int:
        with self.db.transaction(immediate=True) as connection:
            if connection.execute("SELECT 1 FROM sources WHERE id=? AND enabled=1", (source_id,)).fetchone() is None:
                raise ValueError("source not found or disabled")
            cursor = connection.execute("INSERT INTO jobs(source_id,created_by) VALUES(?,?)", (source_id, user_id))
            return int(cursor.lastrowid)

    def cancel_job(self, job_id: int) -> bool:
        now = datetime.now(UTC).isoformat()
        with self.db.transaction(immediate=True) as connection:
            queued = connection.execute(
                "UPDATE jobs SET status='cancelled',lease_until=NULL,updated_at=? WHERE id=? AND status='queued'",
                (now, job_id),
            )
            if queued.rowcount:
                return True
            running = connection.execute(
                "UPDATE jobs SET cancel_requested_at=COALESCE(cancel_requested_at,?),updated_at=? "
                "WHERE id=? AND status='running' AND cancel_requested_at IS NULL",
                (now, now, job_id),
            )
            return running.rowcount == 1

    def retry_job(self, job_id: int) -> bool:
        with self.db.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status='queued',error=NULL,result_json=NULL,worker_id=NULL,lease_token=NULL,"
                "lease_until=NULL,heartbeat_at=NULL,cancel_requested_at=NULL,updated_at=? "
                "WHERE id=? AND status IN ('failed','cancelled')",
                (datetime.now(UTC).isoformat(), job_id),
            )
            return cursor.rowcount == 1

    def lease_job(self, worker_id: str | None = None, job_id: int | None = None) -> dict[str, Any] | None:
        now = datetime.now(UTC)
        worker = worker_id or f"worker-{uuid.uuid4().hex[:12]}"
        token = secrets.token_urlsafe(32)
        with self.db.transaction(immediate=True) as connection:
            where_id = "AND id=?" if job_id is not None else ""
            params: list[object] = [now.isoformat()]
            if job_id is not None:
                params.append(job_id)
            row = connection.execute(
                f"SELECT * FROM jobs WHERE cancel_requested_at IS NULL AND "
                f"(status='queued' OR (status='running' AND lease_until < ?)) {where_id} ORDER BY created_at LIMIT 1",
                params,
            ).fetchone()
            if row is None:
                return None
            lease_until = (now + timedelta(seconds=self.settings.lease_seconds)).isoformat()
            cursor = connection.execute(
                "UPDATE jobs SET status='running',attempts=attempts+1,worker_id=?,lease_token=?,lease_until=?,heartbeat_at=?,updated_at=? "
                "WHERE id=? AND cancel_requested_at IS NULL AND (status='queued' OR lease_until < ?)",
                (worker, token, lease_until, now.isoformat(), now.isoformat(), row["id"], now.isoformat()),
            )
            if cursor.rowcount != 1:
                return None
            leased = connection.execute("SELECT * FROM jobs WHERE id=?", (row["id"],)).fetchone()
            return dict(leased)

    def heartbeat_job(self, job_id: int, lease_token: str) -> bool:
        now = datetime.now(UTC)
        with self.db.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE jobs SET heartbeat_at=?,lease_until=?,updated_at=? "
                "WHERE id=? AND status='running' AND lease_token=? AND cancel_requested_at IS NULL",
                (now.isoformat(), (now + timedelta(seconds=self.settings.lease_seconds)).isoformat(), now.isoformat(), job_id, lease_token),
            )
            return cursor.rowcount == 1

    def _checkpoint(self, job_id: int, lease_token: str) -> None:
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT status,lease_token,cancel_requested_at FROM jobs WHERE id=?",
                (job_id,),
            ).fetchone()
        if row is None or row["status"] != "running" or row["lease_token"] != lease_token:
            raise LeaseLost("job lease is no longer owned by this worker")
        if row["cancel_requested_at"]:
            with self.db.transaction(immediate=True) as connection:
                connection.execute(
                    "UPDATE jobs SET status='cancelled',worker_id=NULL,lease_token=NULL,lease_until=NULL,updated_at=? "
                    "WHERE id=? AND status='running' AND lease_token=?",
                    (datetime.now(UTC).isoformat(), job_id, lease_token),
                )
            raise JobCancelled("job cancellation requested")
        if not self.heartbeat_job(job_id, lease_token):
            raise LeaseLost("job heartbeat was rejected")

    def run_job(self, job_id: int, lease_token: str | None = None, worker_id: str | None = None) -> dict[str, Any]:
        if lease_token is None:
            leased = self.lease_job(worker_id=worker_id or "direct", job_id=job_id)
            if leased is None:
                with self.db.connect() as connection:
                    row = connection.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
                if row is None:
                    raise ValueError("job not found")
                raise ValueError(f"job cannot run from status {row['status']}")
            lease_token = str(leased["lease_token"])
        with self.db.connect() as connection:
            row = connection.execute(
                "SELECT j.*,s.kind,s.uri,s.title,s.allowed_domains,s.branch_id FROM jobs j "
                "JOIN sources s ON s.id=j.source_id WHERE j.id=?",
                (job_id,),
            ).fetchone()
            actor = connection.execute("SELECT id,username,role FROM users WHERE id=?", (row["created_by"],)).fetchone() if row and row["created_by"] else None
        if row is None:
            raise ValueError("job not found")
        actor_data = dict(actor) if actor else {"id": None, "username": "system", "role": "admin"}
        try:
            self._checkpoint(job_id, lease_token)
            documents = self._load_documents(dict(row), lambda: self._checkpoint(job_id, lease_token))
            results: list[dict[str, Any]] = []
            for document in documents:
                self._checkpoint(job_id, lease_token)
                results.append(
                    self.process_document(
                        int(row["source_id"]),
                        document,
                        branch_id=int(row["branch_id"]),
                        actor=actor_data,
                        checkpoint=lambda: self._checkpoint(job_id, lease_token),
                    )
                )
            self._checkpoint(job_id, lease_token)
            payload = {"documents": len(documents), "concepts": results}
            with self.db.transaction(immediate=True) as connection:
                cursor = connection.execute(
                    "UPDATE jobs SET status='succeeded',result_json=?,error=NULL,worker_id=NULL,lease_token=NULL,lease_until=NULL,updated_at=? "
                    "WHERE id=? AND status='running' AND lease_token=? AND cancel_requested_at IS NULL",
                    (json.dumps(payload, ensure_ascii=False), datetime.now(UTC).isoformat(), job_id, lease_token),
                )
                if cursor.rowcount != 1:
                    raise LeaseLost("job could not be finalized by the current worker")
            return payload
        except JobCancelled:
            raise
        except Exception as exc:
            with self.db.transaction(immediate=True) as connection:
                connection.execute(
                    "UPDATE jobs SET status='failed',error=?,worker_id=NULL,lease_token=NULL,lease_until=NULL,updated_at=? "
                    "WHERE id=? AND status='running' AND lease_token=? AND cancel_requested_at IS NULL",
                    (f"{exc}\n{traceback.format_exc(limit=5)}", datetime.now(UTC).isoformat(), job_id, lease_token),
                )
            raise

    def _load_documents(self, source: dict[str, Any], checkpoint: Callable[[], None] | None = None) -> list[SourceDocument]:
        check = checkpoint or (lambda: None)
        if source["kind"] == "file":
            check()
            source_path = self._validate_local_source("file", source["uri"])
            document = parse_path(source_path)
            document.source_uri = self._company_source_uri(source_path)
            check()
            return [document]
        if source["kind"] == "folder":
            source_path = self._validate_local_source("folder", source["uri"])
            documents: list[SourceDocument] = []
            for path in iter_supported_files(source_path):
                check()
                document_path = self._validate_local_source("file", path)
                document = parse_path(document_path)
                document.source_uri = self._company_source_uri(document_path)
                documents.append(document)
                check()
            return documents
        return crawl_public(
            [source["uri"]],
            set(json.loads(source["allowed_domains"])),
            user_agent=self.settings.crawler_user_agent,
            max_depth=self.settings.crawler_max_depth,
            max_pages=self.settings.crawler_max_pages,
            delay_seconds=self.settings.crawler_delay_seconds,
            max_bytes=self.settings.crawler_max_bytes,
            checkpoint=check,
        )

    def _extract_claims_batched(
        self,
        document: SourceDocument,
        checkpoint: Callable[[], None],
    ) -> list[dict[str, Any]]:
        items: list[tuple[int, ParsedSection]] = []
        max_chars = max(1000, self.settings.claim_batch_chars)
        for global_index, section in enumerate(document.sections):
            text = section.text
            for start in range(0, max(len(text), 1), max_chars):
                piece = text[start:start + max_chars]
                locator = section.locator if len(text) <= max_chars else f"{section.locator}, extract part {start // max_chars + 1}"
                items.append((global_index, ParsedSection(locator, section.title, piece)))
        batches: list[list[tuple[int, ParsedSection]]] = []
        current: list[tuple[int, ParsedSection]] = []
        current_chars = 0
        for item in items:
            length = len(item[1].text)
            if current and (len(current) >= self.settings.claim_batch_sections or current_chars + length > max_chars):
                batches.append(current)
                current = []
                current_chars = 0
            current.append(item)
            current_chars += length
        if current:
            batches.append(current)
        extracted: list[dict[str, Any]] = []
        seen: set[tuple[str, int, str]] = set()
        for batch in batches:
            checkpoint()
            raw_rows = self.lm.extract_claims(document.title, document.language, [item[1] for item in batch])
            checkpoint()
            for raw in raw_rows:
                try:
                    local_index = int(raw.get("section_index", -1))
                except (TypeError, ValueError):
                    continue
                if local_index < 0 or local_index >= len(batch):
                    continue
                remapped = dict(raw)
                remapped["section_index"] = batch[local_index][0]
                key = (str(remapped.get("text", "")).strip().casefold(), int(remapped["section_index"]), str(remapped.get("excerpt", "")).strip())
                if key not in seen:
                    seen.add(key)
                    extracted.append(remapped)
        return extracted

    def process_document(
        self,
        source_id: int,
        document: SourceDocument,
        *,
        branch_id: int = 1,
        actor: dict[str, Any] | None = None,
        checkpoint: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        check = checkpoint or (lambda: None)
        actor_data = actor or {"id": None, "username": "system", "role": "admin"}
        normalized = json.dumps(
            {"sections": [{"locator": s.locator, "title": s.title, "text": s.text} for s in document.sections]},
            ensure_ascii=False,
        )
        with self.db.transaction(immediate=True) as connection:
            branch = connection.execute("SELECT name FROM branches WHERE id=?", (branch_id,)).fetchone()
            if branch is None:
                raise ValueError("branch not found")
            branch_name = str(branch["name"])
            existing = connection.execute(
                "SELECT d.id,EXISTS(SELECT 1 FROM concepts c WHERE c.document_id=d.id) AS has_concept "
                "FROM documents d WHERE d.source_id=? AND d.source_uri=? AND d.checksum=?",
                (source_id, document.source_uri, document.checksum),
            ).fetchone()
            if existing and existing["has_concept"]:
                return {"document_id": existing["id"], "status": "unchanged"}
            if existing:
                document_id = int(existing["id"])
            else:
                cursor = connection.execute(
                    "INSERT INTO documents(source_id,branch_id,source_uri,title,media_type,checksum,language,normalized_json) VALUES(?,?,?,?,?,?,?,?)",
                    (source_id, branch_id, document.source_uri, document.title, document.media_type, document.checksum, document.language, normalized),
                )
                document_id = int(cursor.lastrowid)
        check()
        raw_claims = self._extract_claims_batched(document, check)
        claims = self._verify_claims(document, raw_claims)
        chunks = chunk_sections(document.sections)
        check()
        with self.db.transaction(immediate=True) as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO chunks(document_id,locator,title,text,checksum) VALUES(?,?,?,?,?)",
                [(document_id, chunk.locator, chunk.title, chunk.text, hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()) for chunk in chunks],
            )
        concept_type = MEDIA_TYPES.get(document.media_type, "Reference")
        description = claims[0].text[:200] if claims else f"Knowledge extracted from {document.title}."
        identity_scope = f"{branch_name}\0{document.source_uri}"
        scoped_base_concept_id = f"{slugify(document.title)}-{hashlib.sha1(identity_scope.encode('utf-8')).hexdigest()[:8]}"
        legacy_base_concept_id = f"{slugify(document.title)}-{hashlib.sha1(document.source_uri.encode('utf-8')).hexdigest()[:8]}"
        tags = [document.language, concept_type.lower().replace(" ", "-")]
        markdown = render_concept(concept_type=concept_type, title=document.title, description=description, tags=tags, resource=document.source_uri, claims=claims)
        report = quality_report(
            claims,
            not validate_concept_text(markdown),
            self.settings.coverage_threshold,
            self.settings.minimum_claim_confidence,
            self.settings.average_claim_confidence,
        )
        with self.db.connect() as connection:
            legacy_concept = connection.execute(
                "SELECT branch_id FROM concepts WHERE id=?", (legacy_base_concept_id,)
            ).fetchone()
            base_concept_id = (
                legacy_base_concept_id
                if legacy_concept is not None and int(legacy_concept["branch_id"]) == branch_id
                else scoped_base_concept_id
            )
            existing_concept = connection.execute("SELECT id,status,body FROM concepts WHERE id=?", (base_concept_id,)).fetchone()
        has_conflict = bool(existing_concept and existing_concept["status"] == "published" and existing_concept["body"] != markdown)
        if has_conflict:
            report.publishable = False
            report.reasons.append("a published version already exists; review the update before replacing canonical knowledge")
        concept_id = f"{base_concept_id}-update-{document.checksum[:8]}" if has_conflict else base_concept_id
        relative_path = f"{slugify(concept_type)}/{base_concept_id}.md"
        maturity = self._maturity(report)
        check()
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO concepts(id,document_id,branch_id,type,title,description,body,tags_json,status,quality_json,path,maturity,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET document_id=excluded.document_id,branch_id=excluded.branch_id,"
                "type=excluded.type,title=excluded.title,description=excluded.description,body=excluded.body,tags_json=excluded.tags_json,"
                "status=excluded.status,quality_json=excluded.quality_json,path=excluded.path,maturity=excluded.maturity,updated_at=excluded.updated_at",
                (concept_id, document_id, branch_id, concept_type, document.title, description, markdown, json.dumps(tags), "review", quality_to_json(report), relative_path, maturity, datetime.now(UTC).isoformat()),
            )
            connection.execute("DELETE FROM claims WHERE concept_id=?", (concept_id,))
            connection.executemany(
                "INSERT INTO claims(concept_id,text,confidence,document_checksum,source_uri,locator,excerpt,citations_json,verified) VALUES(?,?,?,?,?,?,?,?,?)",
                [
                    (
                        concept_id,
                        claim.text,
                        claim.confidence,
                        claim.citations[0].checksum if claim.citations else None,
                        claim.citations[0].source_uri if claim.citations else None,
                        claim.citations[0].locator if claim.citations else None,
                        claim.citations[0].excerpt if claim.citations else None,
                        json.dumps([asdict(citation) for citation in claim.citations], ensure_ascii=False),
                        int(bool(claim.citations)),
                    )
                    for claim in claims
                ],
            )
            connection.execute("UPDATE chunks SET concept_id=? WHERE document_id=?", (concept_id, document_id))
            connection.execute("DELETE FROM concept_entities WHERE concept_id=?", (concept_id,))
            for entity_name in sorted({entity.strip() for claim in claims for entity in claim.entities if entity.strip()}):
                normalized_name = fold_vietnamese(entity_name)
                entity_row = connection.execute("SELECT id,name,aliases_json FROM entities WHERE normalized_name=?", (normalized_name,)).fetchone()
                if entity_row is None:
                    cursor = connection.execute(
                        "INSERT INTO entities(name,slug,normalized_name) VALUES(?,?,?)",
                        (entity_name, slugify(entity_name), normalized_name),
                    )
                    entity_id = cursor.lastrowid
                else:
                    entity_id = entity_row["id"]
                    aliases = set(json.loads(entity_row["aliases_json"]))
                    if entity_name != entity_row["name"]:
                        aliases.add(entity_name)
                        connection.execute("UPDATE entities SET aliases_json=? WHERE id=?", (json.dumps(sorted(aliases), ensure_ascii=False), entity_id))
                connection.execute("INSERT OR IGNORE INTO concept_entities(concept_id,entity_id) VALUES(?,?)", (concept_id, entity_id))
        embedding_error = self._embed_document(document_id, concept_id, document.title, description, markdown, check)
        commit = None
        publication_id = None
        status = "review"
        if self.settings.auto_publish and report.publishable:
            publication = self.publish_concept(concept_id, actor_data, direct=actor_data.get("role") == "admin")
            commit = publication.get("commit")
            publication_id = publication.get("publication_id")
            status = str(publication.get("status", "review"))
            if publication.get("error"):
                report.publishable = False
                report.reasons.append(f"publication failed: {publication['error']}")
                with self.db.transaction(immediate=True) as connection:
                    connection.execute("UPDATE concepts SET quality_json=? WHERE id=?", (quality_to_json(report), concept_id))
        return {
            "document_id": document_id,
            "concept_id": concept_id,
            "status": status,
            "quality": json.loads(quality_to_json(report)),
            "commit": commit,
            "publication_id": publication_id,
            "embedding_error": embedding_error,
        }

    def _embed_document(
        self,
        document_id: int,
        concept_id: str,
        title: str,
        description: str,
        markdown: str,
        checkpoint: Callable[[], None],
    ) -> str | None:
        try:
            with self.db.connect() as connection:
                chunk_rows = connection.execute("SELECT id,text FROM chunks WHERE document_id=? ORDER BY id", (document_id,)).fetchall()
            inputs = [f"{title}\n{description}\n{markdown}", *[row["text"] for row in chunk_rows]]
            vectors: list[list[float]] = []
            for start in range(0, len(inputs), 64):
                checkpoint()
                vectors.extend(self.lm.embed(inputs[start:start + 64]))
                checkpoint()
            with self.db.transaction(immediate=True) as connection:
                connection.execute(
                    "INSERT INTO embeddings(concept_id,model,vector_json) VALUES(?,?,?) "
                    "ON CONFLICT(concept_id) DO UPDATE SET model=excluded.model,vector_json=excluded.vector_json,updated_at=CURRENT_TIMESTAMP",
                    (concept_id, self.settings.embedding_model, json.dumps(vectors[0])),
                )
                connection.executemany(
                    "INSERT INTO chunk_embeddings(chunk_id,model,vector_json) VALUES(?,?,?) "
                    "ON CONFLICT(chunk_id) DO UPDATE SET model=excluded.model,vector_json=excluded.vector_json,updated_at=CURRENT_TIMESTAMP",
                    [(row["id"], self.settings.embedding_model, json.dumps(vector)) for row, vector in zip(chunk_rows, vectors[1:], strict=True)],
                )
            return None
        except (JobCancelled, LeaseLost):
            raise
        except Exception as exc:
            return str(exc)

    @staticmethod
    def _maturity(report: Any) -> float:
        if report.claim_count == 0:
            return 0.5
        value = (report.coverage + report.minimum_confidence + report.average_confidence) / 3
        return max(0.1, min(1.0, value))

    @staticmethod
    def _verify_claims(document: SourceDocument, raw_claims: list[dict[str, Any]]) -> list[ClaimDraft]:
        claims: list[ClaimDraft] = []
        for raw in raw_claims:
            text = str(raw.get("text", "")).strip()
            excerpt = str(raw.get("excerpt", "")).strip()
            try:
                confidence = max(0.0, min(1.0, float(raw.get("confidence", 0))))
                index = int(raw.get("section_index", -1))
            except (TypeError, ValueError):
                continue
            if not text or index < 0 or index >= len(document.sections):
                continue
            section = document.sections[index]
            citations: list[CitationLocator] = []
            if excerpt and excerpt in section.text:
                citations.append(CitationLocator(document.source_uri, section.locator, excerpt, document.checksum))
            entities = [str(value).strip() for value in raw.get("entities", []) if str(value).strip()] if isinstance(raw.get("entities", []), list) else []
            claims.append(ClaimDraft(text, confidence, citations, entities))
        return claims

    def _claim_drafts(self, concept_id: str) -> list[ClaimDraft]:
        with self.db.connect() as connection:
            rows = connection.execute("SELECT text,confidence,citations_json FROM claims WHERE concept_id=? ORDER BY id", (concept_id,)).fetchall()
        drafts: list[ClaimDraft] = []
        for row in rows:
            citations = [CitationLocator(**item) for item in json.loads(row["citations_json"])]
            drafts.append(ClaimDraft(row["text"], float(row["confidence"]), citations))
        return drafts

    def _render_stored_concept(self, row: Any, title: str | None = None) -> str:
        metadata, _ = parse_frontmatter(row["body"])
        claims = self._claim_drafts(row["id"])
        return render_concept(
            concept_type=row["type"],
            title=title or row["title"],
            description=row["description"] or "",
            tags=json.loads(row["tags_json"]),
            resource=str(metadata.get("resource") or (claims[0].citations[0].source_uri if claims and claims[0].citations else "")),
            claims=claims,
        )

    def review(
        self,
        concept_id: str,
        decision: str,
        title: str | None = None,
        body: str | None = None,
        actor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM concepts WHERE id=?", (concept_id,)).fetchone()
            stats = connection.execute(
                "SELECT COUNT(*) AS total,SUM(CASE WHEN verified=1 THEN 1 ELSE 0 END) AS verified FROM claims WHERE concept_id=?",
                (concept_id,),
            ).fetchone()
        if row is None:
            raise ValueError("concept not found")
        actor_data = actor or {"id": None, "username": "system", "role": "admin"}
        if decision == "reject":
            with self.db.transaction(immediate=True) as connection:
                connection.execute("UPDATE concepts SET status='rejected',updated_at=? WHERE id=?", (datetime.now(UTC).isoformat(), concept_id))
            self.audit(actor_data.get("id"), row["branch_id"], "concept.reject", "concept", concept_id, "succeeded")
            return {"id": concept_id, "status": "rejected"}
        total = int(stats["total"] or 0)
        verified = int(stats["verified"] or 0)
        if total == 0 or verified != total:
            raise ValueError("all factual claims must have verified citations before publication")
        canonical = self._render_stored_concept(row, title)
        if body is not None and body.strip() != row["body"].strip() and body.strip() != canonical.strip():
            raise ValueError("factual claims and citations must be revised through the structured claim endpoint")
        errors = validate_concept_text(canonical)
        if errors:
            raise ValueError(f"generated concept is not OKF conformant: {errors}")
        current_claims = self._claim_drafts(concept_id)
        report = quality_report(
            current_claims,
            not errors,
            self.settings.coverage_threshold,
            self.settings.minimum_claim_confidence,
            self.settings.average_claim_confidence,
        )
        if not report.publishable:
            raise ValueError(f"concept does not pass publication quality gates: {report.reasons}")
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE concepts SET title=?,body=?,status='review',quality_json=?,maturity=?,updated_at=? WHERE id=?",
                (title or row["title"], canonical, quality_to_json(report), self._maturity(report), datetime.now(UTC).isoformat(), concept_id),
            )
        return self.publish_concept(concept_id, actor_data, direct=actor_data.get("role") == "admin")

    def revise_claim(self, concept_id: str, claim_id: int, text: str, locator: str, excerpt: str, actor: dict[str, Any]) -> dict[str, Any]:
        with self.db.connect() as connection:
            concept = connection.execute(
                "SELECT c.*,d.checksum,d.source_uri,d.normalized_json FROM concepts c LEFT JOIN documents d ON d.id=c.document_id WHERE c.id=?",
                (concept_id,),
            ).fetchone()
            claim = connection.execute("SELECT * FROM claims WHERE id=? AND concept_id=?", (claim_id, concept_id)).fetchone()
        if concept is None or claim is None:
            raise ValueError("concept or claim not found")
        if concept["legacy"] or not concept["normalized_json"]:
            raise ValueError("legacy concepts must be re-ingested before factual claims can be revised")
        sections = json.loads(concept["normalized_json"])["sections"]
        section = next((item for item in sections if item["locator"] == locator), None)
        if section is None or not excerpt.strip() or excerpt not in section["text"]:
            raise ValueError("citation excerpt must occur exactly in the selected immutable source section")
        citation = CitationLocator(concept["source_uri"], locator, excerpt, concept["checksum"])
        claim_tokens = set(re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE))
        excerpt_tokens = set(re.findall(r"[^\W_]+", excerpt.casefold(), flags=re.UNICODE))
        overlap = len(claim_tokens & excerpt_tokens) / len(claim_tokens) if claim_tokens else 0.0
        confidence = 0.5 + 0.5 * overlap
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE claims SET text=?,confidence=?,document_checksum=?,source_uri=?,locator=?,excerpt=?,citations_json=?,verified=1 WHERE id=?",
                (text.strip(), confidence, citation.checksum, citation.source_uri, citation.locator, citation.excerpt, json.dumps([asdict(citation)], ensure_ascii=False), claim_id),
            )
            connection.execute("UPDATE concepts SET status='review',canonical_commit=NULL,updated_at=? WHERE id=?", (datetime.now(UTC).isoformat(), concept_id))
        with self.db.connect() as connection:
            refreshed = connection.execute("SELECT * FROM concepts WHERE id=?", (concept_id,)).fetchone()
        markdown = self._render_stored_concept(refreshed)
        claims = self._claim_drafts(concept_id)
        report = quality_report(claims, not validate_concept_text(markdown), self.settings.coverage_threshold, self.settings.minimum_claim_confidence, self.settings.average_claim_confidence)
        with self.db.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE concepts SET body=?,quality_json=?,maturity=?,updated_at=? WHERE id=?",
                (markdown, quality_to_json(report), self._maturity(report), datetime.now(UTC).isoformat(), concept_id),
            )
        self.audit(actor.get("id"), concept["branch_id"], "claim.revise", "claim", str(claim_id), "succeeded", {"concept_id": concept_id, "locator": locator})
        return {"id": claim_id, "concept_id": concept_id, "verified": True, "quality": json.loads(quality_to_json(report))}

    def publish_concept(self, concept_id: str, actor: dict[str, Any], *, direct: bool) -> dict[str, Any]:
        with self.db.connect() as connection:
            row = connection.execute("SELECT * FROM concepts WHERE id=?", (concept_id,)).fetchone()
            branch = connection.execute("SELECT * FROM branches WHERE id=?", (row["branch_id"],)).fetchone() if row else None
        if row is None or branch is None:
            raise ValueError("concept or branch not found")
        publication_id = str(uuid.uuid4())
        candidate_branch = branch["name"] if direct else f"ckb/{slugify(str(actor.get('username') or 'reviewer'))}/{publication_id[:12]}"
        idempotency_key = hashlib.sha256(f"{concept_id}:{row['body']}:{candidate_branch}".encode("utf-8")).hexdigest()
        with self.db.transaction(immediate=True) as connection:
            existing = connection.execute("SELECT * FROM publications WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                if existing["state"] != "abandoned":
                    return {"id": concept_id, "status": "published" if row["status"] == "published" else "review", "publication_id": existing["id"], "commit": existing["commit_hash"]}
                publication_id = existing["id"]
                candidate_branch = existing["candidate_branch"]
                connection.execute(
                    "UPDATE publications SET state='pending',commit_hash=NULL,error=NULL,updated_at=? "
                    "WHERE id=? AND state='abandoned'",
                    (datetime.now(UTC).isoformat(), publication_id),
                )
            else:
                connection.execute(
                    "INSERT INTO publications(id,concept_id,branch_id,candidate_branch,state,idempotency_key,created_by) VALUES(?,?,?,?,?,?,?)",
                    (publication_id, concept_id, row["branch_id"], candidate_branch, "pending", idempotency_key, actor.get("id")),
                )
        actor_name = str(actor.get("username") or "Company Knowledge Base")
        actor_email = f"{slugify(actor_name)}@localhost"
        try:
            credentials = self.secrets.get_json("git_https_credentials", int(actor["id"])) if actor.get("id") else None
        except SecretStoreError:
            credentials = None
        try:
            if direct:
                checkout_canonical(self.settings.root, self.settings.canonical_branch)
                commit = publish_markdown(
                    self.settings.root,
                    self.settings.bundle_dir,
                    row["path"],
                    row["body"],
                    row["title"],
                    actor_name=actor_name,
                    actor_email=actor_email,
                    publication_id=publication_id,
                    credentials=credentials,
                )
            else:
                commit = publish_candidate(
                    self.settings.root,
                    self.settings.bundle_dir,
                    candidate_branch,
                    row["path"],
                    row["body"],
                    row["title"],
                    actor_name=actor_name,
                    actor_email=actor_email,
                    publication_id=publication_id,
                    credentials=credentials,
                )
            with self.db.transaction(immediate=True) as connection:
                connection.execute("UPDATE publications SET state='committed',commit_hash=?,updated_at=? WHERE id=?", (commit, datetime.now(UTC).isoformat(), publication_id))
            if direct:
                self._apply_publication(publication_id, commit)
                status = "published"
            else:
                status = "review"
            self.audit(actor.get("id"), row["branch_id"], "publication.commit", "concept", concept_id, "succeeded", {"candidate_branch": candidate_branch}, publication_id, commit)
            return {"id": concept_id, "status": status, "publication_id": publication_id, "commit": commit, "candidate_branch": candidate_branch}
        except Exception as exc:
            recovered_commit = find_publication_commit(self.settings.root, publication_id)
            with self.db.transaction(immediate=True) as connection:
                if recovered_commit:
                    connection.execute(
                        "UPDATE publications SET state=CASE WHEN state='pending' THEN 'committed' ELSE state END,"
                        "commit_hash=COALESCE(commit_hash,?),error=?,updated_at=? WHERE id=?",
                        (recovered_commit, str(exc), datetime.now(UTC).isoformat(), publication_id),
                    )
                else:
                    connection.execute(
                        "UPDATE publications SET state=CASE WHEN state='pending' THEN 'abandoned' ELSE state END,error=?,updated_at=? WHERE id=?",
                        (str(exc), datetime.now(UTC).isoformat(), publication_id),
                    )
            self.audit(actor.get("id"), row["branch_id"], "publication.commit", "concept", concept_id, "failed", {"error": str(exc)}, publication_id)
            if isinstance(exc, GitOperationError):
                return {"id": concept_id, "status": "review", "publication_id": publication_id, "commit": None, "error": str(exc)}
            raise

    def _apply_publication(self, publication_id: str, commit: str) -> None:
        with self.db.connect() as connection:
            publication = connection.execute("SELECT * FROM publications WHERE id=?", (publication_id,)).fetchone()
            concept = connection.execute("SELECT * FROM concepts WHERE id=?", (publication["concept_id"],)).fetchone() if publication else None
        if publication is None or concept is None:
            raise ValueError("publication not found")
        index_concept(self.db, concept["id"], concept["title"], concept["body"])
        with self.db.transaction(immediate=True) as connection:
            replaced = connection.execute(
                "SELECT id FROM concepts WHERE branch_id=? AND path=? AND status='published' AND id<>?",
                (concept["branch_id"], concept["path"], concept["id"]),
            ).fetchall()
            for old in replaced:
                connection.execute("DELETE FROM search_fts WHERE concept_id=?", (old["id"],))
                connection.execute("DELETE FROM concepts WHERE id=?", (old["id"],))
            connection.execute(
                "UPDATE concepts SET status='published',canonical_commit=?,updated_at=? WHERE id=?",
                (commit, datetime.now(UTC).isoformat(), concept["id"]),
            )
            connection.execute("UPDATE publications SET state='applied',commit_hash=?,updated_at=? WHERE id=?", (commit, datetime.now(UTC).isoformat(), publication_id))
        recompute_value_graph(self.db)

    def merge_publication(self, publication_id: str, actor: dict[str, Any]) -> dict[str, Any]:
        with self.db.connect() as connection:
            publication = connection.execute("SELECT p.*,b.name AS branch_name FROM publications p JOIN branches b ON b.id=p.branch_id WHERE p.id=?", (publication_id,)).fetchone()
        if publication is None or publication["state"] not in {"committed", "pushed"}:
            raise ValueError("publication is not ready to merge")
        commit = merge_candidate(
            self.settings.root,
            self.settings.canonical_branch,
            publication["candidate_branch"],
            actor_name=str(actor["username"]),
            actor_email=f"{slugify(str(actor['username']))}@localhost",
            publication_id=publication_id,
            credentials=self.secrets.get_json("git_https_credentials", int(actor["id"])) if actor.get("id") else None,
        )
        self._apply_publication(publication_id, commit)
        self.audit(actor.get("id"), publication["branch_id"], "publication.merge", "publication", publication_id, "succeeded", None, publication_id, commit)
        return {"id": publication_id, "state": "applied", "commit": commit}

    def recover_publications(self) -> int:
        with self.db.connect() as connection:
            pending = connection.execute(
                "SELECT p.id,p.candidate_branch,p.updated_at,b.name AS branch_name FROM publications p JOIN branches b ON b.id=p.branch_id WHERE p.state='pending'"
            ).fetchall()
            rows = connection.execute(
                "SELECT p.id,p.commit_hash,p.candidate_branch,b.name AS branch_name FROM publications p JOIN branches b ON b.id=p.branch_id "
                "WHERE p.state='committed' AND p.commit_hash IS NOT NULL"
            ).fetchall()
        recovered = 0
        cutoff = datetime.now(UTC) - timedelta(minutes=10)
        for row in pending:
            commit = find_publication_commit(self.settings.root, row["id"])
            if commit:
                with self.db.transaction(immediate=True) as connection:
                    connection.execute(
                        "UPDATE publications SET state='committed',commit_hash=?,error=NULL,updated_at=? WHERE id=? AND state='pending'",
                        (commit, datetime.now(UTC).isoformat(), row["id"]),
                    )
                if row["candidate_branch"] == row["branch_name"]:
                    self._apply_publication(row["id"], commit)
                recovered += 1
            elif datetime.fromisoformat(row["updated_at"]).replace(tzinfo=UTC) < cutoff:
                with self.db.transaction(immediate=True) as connection:
                    connection.execute(
                        "UPDATE publications SET state='abandoned',error='no Git commit found during recovery',updated_at=? WHERE id=? AND state='pending'",
                        (datetime.now(UTC).isoformat(), row["id"]),
                    )
        for row in rows:
            if row["candidate_branch"] == row["branch_name"]:
                self._apply_publication(row["id"], row["commit_hash"])
                recovered += 1
        return recovered

    def rebuild_from_bundle(self) -> int:
        branch_id = self.branch_id(self.settings.canonical_branch)
        imported = 0
        seen_ids: set[str] = set()
        concept_paths = sorted(
            path
            for path in self.settings.bundle_dir.rglob("*.md")
            if path.name not in {"index.md", "log.md"}
        )
        paths_by_id: dict[str, list[Path]] = {}
        for path in concept_paths:
            paths_by_id.setdefault(path.stem, []).append(path)
        duplicates = {
            concept_id: paths
            for concept_id, paths in paths_by_id.items()
            if len(paths) > 1
        }
        if duplicates:
            details = "; ".join(
                f"{concept_id}: {', '.join(path.relative_to(self.settings.bundle_dir).as_posix() for path in paths)}"
                for concept_id, paths in sorted(duplicates.items())
            )
            raise ValueError(f"duplicate canonical concept IDs detected; rebuild refused: {details}")

        for path in concept_paths:
            text = path.read_text(encoding="utf-8")
            try:
                metadata, body = parse_frontmatter(text)
            except Exception:
                continue
            concept_id = path.stem
            seen_ids.add(concept_id)
            with self.db.connect() as connection:
                existing = connection.execute(
                    "SELECT body,document_id,status FROM concepts WHERE id=?",
                    (concept_id,),
                ).fetchone()
            if (
                existing is not None
                and existing["body"] == text
                and existing["document_id"] is not None
                and existing["status"] == "published"
                and concept_integrity_valid(metadata, body)
                and _clean_tracked_head(self.settings.root, path)
            ):
                # Idempotent register/sync preserves a locally verified concept
                # only while its exact canonical Markdown remains unchanged.
                imported += 1
                continue
            title = str(metadata.get("title") or path.stem)
            description = str(metadata.get("description") or "Imported legacy knowledge")
            concept_type = str(metadata.get("type") or "Reference")
            tags = metadata.get("tags") if isinstance(metadata.get("tags"), list) else []
            raw_claims = metadata.get("claims")
            structured = bool(
                isinstance(raw_claims, list)
                and concept_integrity_valid(metadata, body)
                and _clean_tracked_head(self.settings.root, path)
            )
            claim_records: list[tuple[ClaimDraft, list[CitationLocator], bool]] = []
            if structured:
                for raw_claim in raw_claims:
                    if not isinstance(raw_claim, dict):
                        structured = False
                        break
                    try:
                        claim_text = str(raw_claim["text"]).strip()
                        confidence = float(raw_claim["confidence"])
                    except (KeyError, TypeError, ValueError):
                        structured = False
                        break
                    if not claim_text or not 0.0 <= confidence <= 1.0:
                        structured = False
                        break
                    raw_citations = raw_claim.get("citations", [])
                    if not isinstance(raw_citations, list):
                        structured = False
                        break
                    citations: list[CitationLocator] = []
                    for raw_citation in raw_citations:
                        if not isinstance(raw_citation, dict):
                            structured = False
                            break
                        fields = {
                            key: str(raw_citation.get(key, "")).strip()
                            for key in ("source_uri", "locator", "excerpt", "checksum")
                        }
                        if not all(fields.values()):
                            structured = False
                            break
                        citations.append(CitationLocator(**fields))
                    if not structured:
                        break
                    # Git Markdown is canonical history, not independently verified
                    # source evidence. Rebuild preserves claims and citation metadata
                    # for review but always fails closed until sources are re-ingested.
                    verified = False
                    entities = raw_claim.get("entities", [])
                    if not isinstance(entities, list):
                        structured = False
                        break
                    claim_records.append(
                        (
                            ClaimDraft(
                                claim_text,
                                confidence,
                                citations if verified else [],
                                [str(entity).strip() for entity in entities if str(entity).strip()],
                            ),
                            citations,
                            verified,
                        )
                    )
            if not structured:
                claim_records = []
            if structured:
                claims = [record[0] for record in claim_records]
                report = quality_report(
                    claims,
                    not validate_concept_text(text),
                    self.settings.coverage_threshold,
                    self.settings.minimum_claim_confidence,
                    self.settings.average_claim_confidence,
                )
                quality = json.loads(quality_to_json(report))
                maturity = self._maturity(report)
                legacy = 0
            else:
                quality = {
                    "claim_count": 0,
                    "cited_claim_count": 0,
                    "coverage": 0.0,
                    "minimum_confidence": 0.0,
                    "average_confidence": 0.0,
                    "okf_valid": not validate_concept_text(text),
                    "publishable": False,
                    "reasons": ["legacy import requires re-ingestion before factual editing"],
                }
                maturity = 0.6
                legacy = 1
            with self.db.transaction(immediate=True) as connection:
                connection.execute(
                    "INSERT INTO concepts(id,branch_id,type,title,description,body,tags_json,status,quality_json,path,maturity,legacy) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body,title=excluded.title,description=excluded.description,"
                    "type=excluded.type,tags_json=excluded.tags_json,status='review',quality_json=excluded.quality_json,path=excluded.path,"
                    "maturity=excluded.maturity,legacy=excluded.legacy",
                    (
                        concept_id,
                        branch_id,
                        concept_type,
                        title,
                        description,
                        text,
                        json.dumps(tags, ensure_ascii=False),
                        "review",
                        json.dumps(quality, ensure_ascii=False),
                        path.relative_to(self.settings.bundle_dir).as_posix(),
                        maturity,
                        legacy,
                    ),
                )
                connection.execute("DELETE FROM claims WHERE concept_id=?", (concept_id,))
                for claim, stored_citations, verified in claim_records:
                    primary = stored_citations[0] if stored_citations else None
                    connection.execute(
                        "INSERT INTO claims(concept_id,text,confidence,document_checksum,source_uri,locator,excerpt,citations_json,verified) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            concept_id,
                            claim.text,
                            claim.confidence,
                            primary.checksum if primary else None,
                            primary.source_uri if primary else None,
                            primary.locator if primary else None,
                            primary.excerpt if primary else None,
                            json.dumps([asdict(citation) for citation in stored_citations], ensure_ascii=False),
                            int(verified),
                        ),
                    )
            index_concept(self.db, concept_id, title, text)
            imported += 1
        with self.db.transaction(immediate=True) as connection:
            canonical = connection.execute(
                "SELECT id FROM concepts WHERE branch_id=? AND status IN ('published','review')",
                (branch_id,),
            ).fetchall()
            for row in canonical:
                if row["id"] in seen_ids:
                    continue
                connection.execute("DELETE FROM search_fts WHERE concept_id=?", (row["id"],))
                connection.execute("DELETE FROM concepts WHERE id=?", (row["id"],))
        recompute_value_graph(self.db)
        return imported
