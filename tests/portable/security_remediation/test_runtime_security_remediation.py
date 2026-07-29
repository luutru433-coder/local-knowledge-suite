# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

from local_knowledge.ckb.cli import _parser as ckb_parser
from local_knowledge.ckb.config import Settings
from local_knowledge.ckb.db import SCHEMA_VERSION, Database
from local_knowledge.ckb.models import CitationLocator, ClaimDraft
from local_knowledge.ckb.okf import render_concept
from local_knowledge.ckb.pipeline import KnowledgeService
from local_knowledge.doctor import doctor_workspace
from local_knowledge.manifests import CompanyManifest, write_company_manifest
from local_knowledge.memorizer.core import capture as capture_memory
from local_knowledge.memorizer.core import redact_payload
from local_knowledge.migrations import migrate_workspace
from local_knowledge.registry import CompanyRegistry
from local_knowledge.services import (
    bootstrap_workspace,
    initialize_company_repository,
    knowledge_status,
    recall_context,
    register_company,
)


def _remove_database(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        path.with_name(path.name + suffix).unlink(missing_ok=True)


def _commit(repo: Path, message: str, *paths: str) -> None:
    subprocess.run(["git", "add", "--", *paths], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Security Test",
            "-c",
            "user.email=security-test@localhost",
            "commit",
            "-m",
            message,
            "--",
            *paths,
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_future_database_schema_is_rejected_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE schema_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        connection.execute("INSERT INTO schema_meta VALUES('version','999')")
    before = path.read_bytes()

    database = Database(path)
    with pytest.raises(RuntimeError, match="newer than supported"):
        database.initialize()
    with pytest.raises(RuntimeError, match="newer than supported"):
        with database.connect():
            pass
    with pytest.raises(RuntimeError, match="newer than supported"):
        with database.transaction():
            pass
    current = Database(tmp_path / "current.sqlite3")
    current.initialize()
    with pytest.raises(RuntimeError, match="newer than supported"):
        current.restore_from(path)
    assert current.assert_compatible() == SCHEMA_VERSION

    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()[0] == "999"
        assert connection.execute("SELECT 1 FROM sqlite_master WHERE name='users'").fetchone() is None
    assert path.read_bytes() == before


def test_sqlite_backup_captures_wal_and_restore_removes_stale_sidecars(tmp_path: Path) -> None:
    live = tmp_path / "live.sqlite3"
    backup = tmp_path / "backup.sqlite3"
    database = Database(live)
    database.initialize()
    with database.connect() as connection:
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            "INSERT INTO sources(kind,uri,title,allowed_domains) VALUES('website','https://example.test','WAL row','[]')"
        )
    database.backup_to(backup)
    with database.connect() as connection:
        connection.execute("DELETE FROM sources")
    database.restore_from(backup)

    with database.connect() as connection:
        assert connection.execute("SELECT title FROM sources").fetchone()[0] == "WAL row"
    assert not live.with_name(live.name + "-wal").exists()
    assert not live.with_name(live.name + "-shm").exists()


def test_status_and_doctor_fail_closed_on_future_company_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "company"
    project = tmp_path / "project"
    project.mkdir()
    initialize_company_repository(company, "Future Company", "future-company")
    bootstrap_workspace(
        str(project.resolve()),
        "future-company",
        profile="combined",
    )
    database_path = Settings.for_company(company, "future-company").database
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE schema_meta SET value='999' WHERE key='version'"
        )

    status = knowledge_status(str(project.resolve()))
    assert status["company"]["available"] is False
    assert any("newer than supported" in warning for warning in status["warnings"])
    doctor = doctor_workspace(str(project.resolve()))
    assert doctor["ok"] is False
    database_check = next(
        check for check in doctor["checks"] if check["name"] == "company-database"
    )
    assert database_check["ok"] is False
    assert "newer than supported" in str(database_check["detail"])


def test_recursive_redaction_removes_git_tokens_and_encoded_secrets(tmp_path: Path) -> None:
    secret = "gl" + "pat-" + "abcdefghijklmnop123456"
    encode = lambda value: base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii")
    encoded = encode(json.dumps({"github_token": secret}))
    double_encoded = encode(encoded)
    encoded_child = encode(json.dumps({"payload": encoded}))
    basic_value = "dXNlcjpwYXNzd29yZC1zdXBlci1zZWNyZXQ="
    payload = {
        "source": {
            "github_token": secret,
            "nested": [{"deploy_secret": secret}],
            "encoded": encoded,
            "double_encoded": double_encoded,
            "encoded_child": encoded_child,
            "credentials": {"username": "robot", "value": secret},
            "authorization": f"Basic {basic_value}",
        },
        "memory_key": "project:safe-structural-key",
    }

    safe, changed = redact_payload(payload)
    serialized = json.dumps(safe)

    assert changed is True
    assert secret not in serialized
    assert encoded not in serialized
    assert double_encoded not in serialized
    assert encoded_child not in serialized
    assert basic_value not in serialized
    assert safe["memory_key"] == payload["memory_key"]

    captured = capture_memory(
        tmp_path,
        {
            "id": "evt_recursive_encoded_secret",
            "kind": "secret",
            "title": "Encoded credential indicator",
            "text": "A credential exists but its value must not persist.",
            "memory_key": "security:encoded-indicator",
            "source": payload["source"],
        },
        defer=True,
    )
    vault = tmp_path / ".memorizer"
    persisted = b"".join(path.read_bytes() for path in vault.rglob("*") if path.is_file())
    assert captured["redacted"] is True
    for forbidden in (secret, encoded, double_encoded, encoded_child, basic_value):
        assert forbidden.encode("utf-8") not in persisted


def test_ckb_cli_does_not_accept_password_arguments() -> None:
    with pytest.raises(SystemExit):
        ckb_parser().parse_args(["init", "--password", "visible-in-process-list"])
    with pytest.raises(SystemExit):
        ckb_parser().parse_args(
            ["user-add", "reviewer", "--role", "reviewer", "--password", "visible"]
        )


def test_local_sources_use_company_allowlist_and_portable_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    roots = {name: tmp_path / name for name in ("company-a", "company-b")}
    registry = CompanyRegistry()
    for identifier, root in roots.items():
        root.mkdir()
        write_company_manifest(root, CompanyManifest(1, identifier, identifier))
        registry.register(root)
    foreign = roots["company-b"] / ".local-sources" / "policy.txt"
    foreign.parent.mkdir()
    foreign.write_text("foreign", encoding="utf-8")
    settings = Settings.for_company(roots["company-a"], "company-a")
    database = Database(settings.database)
    database.initialize()
    service = KnowledgeService(settings, db=database)

    with pytest.raises(ValueError, match="absolute"):
        service.add_source("file", "..\\policy.txt", None, [], None)
    with pytest.raises(ValueError, match="allowlist"):
        service.add_source("file", str(foreign), None, [], None)
    private = roots["company-a"] / ".ckb" / "private.txt"
    private.write_text("private", encoding="utf-8")
    with pytest.raises(ValueError, match="allowlist"):
        service.add_source("file", str(private), None, [], None)

    outside = tmp_path / "personal.txt"
    outside.write_text("outside company boundary", encoding="utf-8")
    with pytest.raises(ValueError, match="allowlist"):
        service.add_source("file", str(outside), None, [], None)

    allowed = roots["company-a"] / ".local-sources" / "policies" / "portable.txt"
    allowed.parent.mkdir(parents=True)
    allowed.write_text("portable company source", encoding="utf-8")
    source_id = service.add_source("file", str(allowed), None, [], None)
    with database.connect() as connection:
        source = dict(connection.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone())
    document = service._load_documents(source)[0]
    assert document.source_uri == "company-source://company-a/policies/portable.txt"

    nested_private = roots["company-a"] / ".local-sources" / "unsafe" / ".memorizer"
    nested_private.mkdir(parents=True)
    (nested_private / "secret.txt").write_text("private", encoding="utf-8")
    with pytest.raises(ValueError, match="private|canonical"):
        service.add_source("folder", str(nested_private.parent), None, [], None)

    nested_company = roots["company-a"] / ".local-sources" / "nested-company"
    nested_company.mkdir()
    write_company_manifest(nested_company, CompanyManifest(1, "nested-company", "Nested Company"))
    CompanyRegistry().register(nested_company)
    nested_document = nested_company / "docs" / "private.txt"
    nested_document.parent.mkdir()
    nested_document.write_text("cross-company", encoding="utf-8")
    with pytest.raises(ValueError, match="cross-company"):
        service.add_source("file", str(nested_document), None, [], None)
    with pytest.raises(ValueError, match="cross-company"):
        service.add_source("folder", str(roots["company-a"] / ".local-sources"), None, [], None)


def test_clone_evidence_is_attested_but_requires_source_reingestion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "company"
    initialize_company_repository(company, "Evidence Company", "evidence-company")
    settings = Settings.for_company(company, "evidence-company")
    concept = company / "knowledge" / "trusted.md"
    citation = CitationLocator("https://example.test/policy", "section 1", "Trusted excerpt", "a" * 64)
    concept.write_text(
        render_concept(
            concept_type="Policy",
            title="Trusted policy",
            description="A signed canonical concept",
            tags=["policy"],
            resource=citation.source_uri,
            claims=[ClaimDraft("Trusted fact", 0.99, [citation])],
        ),
        encoding="utf-8",
    )
    _commit(company, "docs: add trusted policy", "knowledge/trusted.md")
    _remove_database(settings.database)
    register_company(company)
    with Database(settings.database).connect() as connection:
        assert connection.execute("SELECT verified FROM claims").fetchone()[0] == 0

    concept.write_text(
        concept.read_text(encoding="utf-8").replace("- Trusted fact [1]", "- Forged body [1]"),
        encoding="utf-8",
    )
    _commit(company, "docs: tamper without digest update", "knowledge/trusted.md")
    _remove_database(settings.database)
    register_company(company)
    with Database(settings.database).connect() as connection:
        assert connection.execute("SELECT verified FROM claims").fetchone() is None

    source = tmp_path / "local-source.txt"
    source.write_text("Local source bytes", encoding="utf-8")
    file_citation = CitationLocator(
        source.as_uri(),
        "line 1",
        "Local source bytes",
        hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    local_concept = company / "knowledge" / "local.md"
    local_concept.write_text(
        render_concept(
            concept_type="Policy",
            title="Local policy",
            description="File-backed evidence",
            tags=["local"],
            resource=file_citation.source_uri,
            claims=[ClaimDraft("Local source bytes", 0.99, [file_citation])],
        ),
        encoding="utf-8",
    )
    _commit(company, "docs: add local policy", "knowledge/local.md")
    source.unlink()
    _remove_database(settings.database)
    register_company(company)
    with Database(settings.database).connect() as connection:
        row = connection.execute(
            "SELECT verified FROM claims WHERE concept_id='local'"
        ).fetchone()
    assert row is not None and row[0] == 0


def test_company_init_commits_baseline_in_existing_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "existing-company-repo"
    company.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=company, check=True, capture_output=True)
    (company / "README.md").write_text("existing history\n", encoding="utf-8")
    _commit(company, "docs: existing repository", "README.md")

    result = initialize_company_repository(company, "Existing Company", "existing-company")

    assert result["git"]["initial_commit_created"] is True
    tracked = set(
        subprocess.run(
            ["git", "ls-files"], cwd=company, check=True, capture_output=True, text=True
        ).stdout.splitlines()
    )
    assert ".gitignore" in tracked
    assert ".local-knowledge/company.toml" in tracked
    assert "knowledge/index.md" in tracked
    ignore_text = (company / ".gitignore").read_text(encoding="utf-8")
    assert ".local-sources/" in ignore_text
    assert ignore_text.count("# Local Knowledge derived/private state") == 1
    registered = register_company(company)
    assert registered["git"]["valid"] is True

    subprocess.run(["git", "switch", "-c", "work"], cwd=company, check=True, capture_output=True)
    fresh_registry = CompanyRegistry(tmp_path / "failed-register" / "registry.json")
    with pytest.raises(Exception, match="canonical branch"):
        register_company(company, registry=fresh_registry)
    assert "existing-company" not in fresh_registry.list()


def test_rebuild_rejects_duplicate_concept_ids_before_database_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "duplicate-company"
    initialize_company_repository(company, "Duplicate Company", "duplicate-company")
    citation = CitationLocator(
        "https://example.test/policy",
        "section 1",
        "Duplicate identifiers must be rejected.",
        "b" * 64,
    )
    paths = [company / "knowledge" / name / "duplicate.md" for name in ("a", "b")]
    for index, path in enumerate(paths, 1):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            render_concept(
                concept_type="Policy",
                title=f"Duplicate policy {index}",
                description="Collision fixture",
                tags=["duplicate"],
                resource=citation.source_uri,
                claims=[ClaimDraft(f"Duplicate claim {index}", 0.99, [citation])],
            ),
            encoding="utf-8",
        )
    _commit(
        company,
        "docs: add duplicate identifiers",
        "knowledge/a/duplicate.md",
        "knowledge/b/duplicate.md",
    )
    settings = Settings.for_company(company, "duplicate-company")
    database = Database(settings.database)
    with pytest.raises(ValueError, match="duplicate canonical concept IDs"):
        KnowledgeService(settings, db=database).rebuild_from_bundle()
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 0


def test_company_source_recall_rechecks_live_file_checksum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class ExactLM:
        chat_model = "exact-test"
        embedding_model = "exact-embedding"

        def extract_claims(self, title: str, language: str, sections: list[object]) -> list[dict[str, object]]:
            section = sections[0]
            return [{
                "text": section.text,
                "confidence": 0.99,
                "section_index": 0,
                "excerpt": section.text,
                "entities": [],
            }]

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "live-source-company"
    project = tmp_path / "project"
    project.mkdir()
    initialize_company_repository(company, "Live Source Company", "live-source-company")
    bootstrap_workspace(
        str(project.resolve()),
        "live-source-company",
        profile="combined",
    )
    source = company / ".local-sources" / "policies" / "live-policy.txt"
    source.parent.mkdir(parents=True)
    marker = "Production invoices close every verified Friday."
    source.write_text(marker, encoding="utf-8")
    settings = Settings.for_company(company, "live-source-company")
    service = KnowledgeService(settings, lm_client=ExactLM())
    source_id = service.add_source("file", str(source), "Live policy", [], None)
    outcome = service.run_job(service.enqueue(source_id, None))
    assert outcome["concepts"][0]["status"] == "published"

    recalled = recall_context(
        marker,
        str(project.resolve()),
        include_skills=False,
        include_memory=False,
    )["company"]
    assert recalled["evidence_sufficient"] is True
    assert recalled["results"][0]["claims"][0]["verified"] is True

    registered_again = register_company(company)
    assert registered_again["rebuilt_concepts"] >= 1
    preserved = recall_context(
        marker,
        str(project.resolve()),
        include_skills=False,
        include_memory=False,
    )["company"]
    assert preserved["evidence_sufficient"] is True

    source.write_text("The local source changed after ingestion.", encoding="utf-8")
    stale = recall_context(
        marker,
        str(project.resolve()),
        include_skills=False,
        include_memory=False,
    )["company"]
    assert stale["evidence_sufficient"] is False
    assert stale["results"][0]["claims"][0]["verified"] is False
    assert stale["results"][0]["claims"][0]["stored_verified"] is True


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_local_source_junction_swap_is_rejected_before_job_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "company"
    initialize_company_repository(company, "Source Junction Company", "source-junction-company")
    settings = Settings.for_company(company, "source-junction-company")
    database = Database(settings.database)
    database.initialize()
    service = KnowledgeService(settings, db=database)
    source_folder = company / ".local-sources" / "approved"
    source_folder.mkdir(parents=True)
    (source_folder / "policy.txt").write_text("approved source", encoding="utf-8")
    source_id = service.add_source("folder", str(source_folder), None, [], None)

    original = tmp_path / "original-approved"
    source_folder.rename(original)
    outside = tmp_path / "outside-private"
    outside.mkdir()
    (outside / "secret.txt").write_text("must not be read", encoding="utf-8")
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(source_folder), str(outside)],
        text=True,
        capture_output=True,
    )
    if result.returncode:
        pytest.skip(f"cannot create junction: {result.stderr or result.stdout}")
    try:
        with database.connect() as connection:
            source = dict(
                connection.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
            )
        with pytest.raises(ValueError, match="junction|reparse"):
            service._load_documents(source)
    finally:
        os.rmdir(source_folder)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction contract")
def test_nested_memory_junction_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "company"
    project = tmp_path / "project"
    external = tmp_path / "external"
    project.mkdir()
    external.mkdir()
    initialize_company_repository(company, "Junction Company", "junction-company")
    bootstrap_workspace(
        str(project.resolve()),
        "junction-company",
        profile="combined",
    )
    daily = project / ".memorizer" / "daily"
    shutil.rmtree(daily)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(daily), str(external)],
        text=True,
        capture_output=True,
    )
    if result.returncode:
        pytest.skip(f"cannot create junction: {result.stderr or result.stdout}")
    try:
        with pytest.raises(ValueError, match="junction|reparse"):
            knowledge_status(str(project.resolve()))
    finally:
        os.rmdir(daily)


def test_migration_failure_restores_database_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "company"
    project = tmp_path / "project"
    project.mkdir()
    initialize_company_repository(company, "Migration Company", "migration-company")
    bootstrap_workspace(
        str(project.resolve()),
        "migration-company",
        profile="combined",
    )
    settings = Settings.for_company(company, "migration-company")
    with Database(settings.database).connect() as connection:
        connection.execute(
            "INSERT INTO sources(kind,uri,title,allowed_domains) VALUES('website','https://example.test','Before failure','[]')"
        )
        connection.execute(
            "UPDATE schema_meta SET value='1' WHERE key='version'"
        )
    manifest = project / ".local-knowledge" / "project.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace("schema_version = 2", "schema_version = 0"),
        encoding="utf-8",
    )
    company_manifest = company / ".local-knowledge" / "company.toml"
    company_manifest.write_text(
        company_manifest.read_text(encoding="utf-8").replace(
            "schema_version = 2",
            "schema_version = 0",
        ),
        encoding="utf-8",
    )

    def fail_after_committed_mutation(self: Database) -> None:
        with self.connect() as connection:
            connection.execute("CREATE TABLE migration_partial(value TEXT)")
            connection.execute("INSERT INTO migration_partial VALUES('bad')")
        raise RuntimeError("injected migration failure")

    monkeypatch.setattr(Database, "initialize", fail_after_committed_mutation)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        migrate_workspace(str(project.resolve()), dry_run=False)

    with Database(settings.database).connect() as connection:
        assert connection.execute("SELECT title FROM sources").fetchone()[0] == "Before failure"
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='migration_partial'"
        ).fetchone() is None
    assert "schema_version = 0" in manifest.read_text(encoding="utf-8")
    assert "schema_version = 0" in company_manifest.read_text(encoding="utf-8")
