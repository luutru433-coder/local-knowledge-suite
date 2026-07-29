# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import threading
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import local_knowledge.ckb.pipeline as pipeline_module
from local_knowledge.ckb.api import create_app
from local_knowledge.ckb.db import Database
from local_knowledge.ckb.models import ParsedSection, SourceDocument
from local_knowledge.ckb.gitops import git_credential_environment
from local_knowledge.ckb.pipeline import JobCancelled, KnowledgeService
from local_knowledge.ckb.search import index_concept, recompute_value_graph, search
from local_knowledge.ckb.secrets_store import SecretStore, SecretStoreError
from local_knowledge.ckb.security import create_user
from local_knowledge.ckb.worker import run_worker


class BlockingLM:
    chat_model = "blocking-chat"
    embedding_model = "blocking-embedding"

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def extract_claims(self, title, language, sections):
        self.entered.set()
        self.release.wait(5)
        return [{"text": sections[0].text, "confidence": 0.99, "section_index": 0, "excerpt": sections[0].text}]

    def embed(self, texts):
        return [[1.0, 0.0] for _ in texts]


def test_v1_database_adds_job_lease_columns_before_dependent_indexes(settings) -> None:
    settings.database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(settings.database) as connection:
        connection.executescript(
            """
            CREATE TABLE jobs (
              id INTEGER PRIMARY KEY,
              source_id INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'queued',
              attempts INTEGER NOT NULL DEFAULT 0,
              error TEXT,
              result_json TEXT,
              created_by INTEGER,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )

    db = Database(settings.database)
    db.initialize()
    db.initialize()

    with db.connect() as connection:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)")}
        indexes = {row["name"] for row in connection.execute("PRAGMA index_list(jobs)")}
    assert {"worker_id", "lease_token", "lease_until", "heartbeat_at", "cancel_requested_at"} <= columns
    assert "idx_jobs_lease" in indexes


def test_generated_concepts_are_isolated_by_branch(settings, fake_lm) -> None:
    settings.auto_publish = False
    source = settings.root / ".local-sources" / "shared-policy.txt"
    source.write_text("The main branch retains this original policy statement.", encoding="utf-8")
    service = KnowledgeService(settings, lm_client=fake_lm)

    main_source_id = service.add_source("file", str(source), None, [], None)
    main = service.run_job(service.enqueue(main_source_id, None))["concepts"][0]

    finance_branch = service.create_branch("finance", None)
    finance_source_id = service.add_source("file", str(source), None, [], None, branch="finance")
    source.write_text("The finance branch has an independent policy statement.", encoding="utf-8")
    finance = service.run_job(service.enqueue(finance_source_id, None))["concepts"][0]

    assert main["concept_id"] != finance["concept_id"]
    with service.db.connect() as connection:
        main_row = connection.execute(
            "SELECT branch_id,body FROM concepts WHERE id=?", (main["concept_id"],)
        ).fetchone()
        finance_row = connection.execute(
            "SELECT branch_id,body FROM concepts WHERE id=?", (finance["concept_id"],)
        ).fetchone()
        concept_count = connection.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
        main_claim = connection.execute(
            "SELECT text FROM claims WHERE concept_id=?", (main["concept_id"],)
        ).fetchone()["text"]
        finance_claim = connection.execute(
            "SELECT text FROM claims WHERE concept_id=?", (finance["concept_id"],)
        ).fetchone()["text"]

    assert concept_count == 2
    assert main_row["branch_id"] == service.branch_id()
    assert finance_row["branch_id"] == finance_branch["id"]
    assert "main branch" in main_row["body"]
    assert "finance branch" in finance_row["body"]
    assert "main branch" in main_claim
    assert "finance branch" in finance_claim


def test_branch_scoping_preserves_existing_unscoped_concept_identity(settings, fake_lm) -> None:
    settings.auto_publish = False
    source = settings.root / ".local-sources" / "legacy-policy.txt"
    content = "The upgraded source keeps its existing canonical concept identity."
    source.write_text(content, encoding="utf-8")
    service = KnowledgeService(settings, lm_client=fake_lm)
    source_uri = service._company_source_uri(source)
    legacy_id = f"legacy-policy-{hashlib.sha1(source_uri.encode('utf-8')).hexdigest()[:8]}"
    main_branch_id = service.branch_id()
    with service.db.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO concepts(id,branch_id,type,title,body,tags_json,status,quality_json,path) "
            "VALUES(?,?,'Reference','Legacy policy','Earlier published body','[]','published','{}',?)",
            (legacy_id, main_branch_id, f"reference/{legacy_id}.md"),
        )

    source_id = service.add_source("file", str(source), None, [], None)
    result = service.run_job(service.enqueue(source_id, None))["concepts"][0]

    checksum = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert result["concept_id"] == f"{legacy_id}-update-{checksum[:8]}"
    with service.db.connect() as connection:
        paths = {
            row["id"]: row["path"]
            for row in connection.execute("SELECT id,path FROM concepts ORDER BY id")
        }
    assert paths == {
        legacy_id: f"reference/{legacy_id}.md",
        result["concept_id"]: f"reference/{legacy_id}.md",
    }


def test_running_cancellation_cannot_publish_or_finish_succeeded(settings, git_repo) -> None:
    settings.auto_publish = False
    source = settings.root / ".local-sources" / "blocking.txt"
    source.write_text("A source statement that blocks during extraction.", encoding="utf-8")
    lm = BlockingLM()
    service = KnowledgeService(settings, lm_client=lm)
    source_id = service.add_source("file", str(source), None, [], None)
    job_id = service.enqueue(source_id, None)
    errors: list[Exception] = []

    def run() -> None:
        try:
            service.run_job(job_id)
        except Exception as exc:
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    assert lm.entered.wait(2)
    assert service.cancel_job(job_id)
    lm.release.set()
    thread.join(timeout=5)
    assert errors and isinstance(errors[0], JobCancelled)
    with service.db.connect() as connection:
        assert connection.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()["status"] == "cancelled"
        assert connection.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 0


def test_expired_worker_token_cannot_heartbeat_or_finalize(settings, fake_lm) -> None:
    source = settings.root / ".local-sources" / "lease.txt"
    source.write_text("Lease ownership is exclusive and durable.", encoding="utf-8")
    service = KnowledgeService(settings, lm_client=fake_lm)
    source_id = service.add_source("file", str(source), None, [], None)
    job_id = service.enqueue(source_id, None)
    first = service.lease_job(worker_id="worker-one")
    assert first and first["id"] == job_id
    with service.db.transaction(immediate=True) as connection:
        connection.execute("UPDATE jobs SET lease_until=? WHERE id=?", ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), job_id))
    second = service.lease_job(worker_id="worker-two")
    assert second and second["lease_token"] != first["lease_token"]
    assert not service.heartbeat_job(job_id, str(first["lease_token"]))
    assert service.heartbeat_job(job_id, str(second["lease_token"]))


def test_review_rejects_forged_facts_and_citation_urls(settings, fake_lm, git_repo) -> None:
    settings.auto_publish = False
    source = settings.root / ".local-sources" / "evidence.txt"
    source.write_text("Original exact evidence for the verified policy.", encoding="utf-8")
    service = KnowledgeService(settings, lm_client=fake_lm)
    source_id = service.add_source("file", str(source), None, [], None)
    concept = service.run_job(service.enqueue(source_id, None))["concepts"][0]
    forged = """---
type: Reference
title: Forged
---

# Forged

- A fabricated fact. [1]

# Citations

[1] [Invented](https://fake.example/evidence)
"""
    with pytest.raises(ValueError, match="structured claim endpoint"):
        service.review(concept["concept_id"], "approve", body=forged)
    assert not list(settings.bundle_dir.rglob("evidence*.md"))


class CountingLM:
    chat_model = "counting-chat"
    embedding_model = "counting-embedding"

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def extract_claims(self, title, language, sections):
        self.batch_sizes.append(len(sections))
        return [
            {"text": section.text, "confidence": 0.99, "section_index": index, "excerpt": section.text, "entities": ["Batch Entity"]}
            for index, section in enumerate(sections)
        ]

    def embed(self, texts):
        return [[1.0, float(index + 1)] for index, _ in enumerate(texts)]


def test_large_document_extraction_is_bounded_and_locator_safe(settings) -> None:
    settings.auto_publish = False
    settings.claim_batch_sections = 20
    lm = CountingLM()
    service = KnowledgeService(settings, lm_client=lm)
    placeholder = settings.root / ".local-sources" / "large.txt"
    placeholder.write_text("placeholder", encoding="utf-8")
    source_id = service.add_source("file", str(placeholder), None, [], None)
    sections = [ParsedSection(f"page {index + 1}", f"Page {index + 1}", f"Exact statement number {index + 1} with durable evidence.") for index in range(100)]
    document = SourceDocument(placeholder.as_uri(), "Large source", "text/plain", hashlib.sha256(b"large").hexdigest(), "en", sections)
    result = service.process_document(source_id, document)
    assert result["status"] == "review"
    assert len(lm.batch_sizes) == 5
    assert max(lm.batch_sizes) <= 20
    with service.db.connect() as connection:
        claims = connection.execute("SELECT locator,excerpt,verified FROM claims WHERE concept_id=?", (result["concept_id"],)).fetchall()
    assert len(claims) == 100
    assert claims[-1]["locator"] == "page 100"
    assert all(row["verified"] for row in claims)


def test_secret_store_encrypts_at_rest_and_is_idempotent(settings) -> None:
    db = Database(settings.database)
    db.initialize()
    key = bytes(range(32))
    store = SecretStore(db, "test", key_provider=lambda create: key)
    store.set("lm_studio_token", "plain-secret-token")
    assert store.get("lm_studio_token") == "plain-secret-token"
    store.set("lm_studio_token", "replacement-token")
    with db.connect() as connection:
        rows = connection.execute("SELECT ciphertext,nonce FROM secret_records").fetchall()
    assert len(rows) == 1
    assert b"replacement-token" not in bytes(rows[0]["ciphertext"])
    assert len(bytes(rows[0]["nonce"])) == 12
    assert store.delete("lm_studio_token")


def test_locked_keyring_and_ephemeral_git_askpass_do_not_expose_credentials(settings) -> None:
    db = Database(settings.database)
    db.initialize()
    key = bytes(range(32))
    store = SecretStore(db, "test", key_provider=lambda create: key)
    store.set("git_https_credentials", "secret-token")
    store._key_provider = lambda create: None
    with pytest.raises(SecretStoreError, match="locked"):
        store.get("git_https_credentials")
    helper_path = None
    with git_credential_environment({"username": "git-user", "token": "secret-token"}) as environment:
        assert environment is not None
        helper_path = environment["GIT_ASKPASS"]
        helper_text = open(helper_path, encoding="utf-8").read()
        assert "secret-token" not in helper_text
        assert environment["CKB_GIT_TOKEN"] == "secret-token"
    assert helper_path is not None and not __import__("pathlib").Path(helper_path).exists()


def test_value_ranking_uses_graph_maturity_endorsements_and_usage(settings) -> None:
    db = Database(settings.database)
    db.initialize()
    quality = json.dumps({"coverage": 1.0, "minimum_confidence": 0.95, "average_confidence": 0.96})
    with db.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO concepts(id,type,title,description,body,tags_json,status,quality_json,path,maturity,endorsements,usage_count) VALUES('a','Reference','Policy A','A','shared policy term','[]','published',?,'reference/a.md',0.7,0,0)",
            (quality,),
        )
        connection.execute(
            "INSERT INTO concepts(id,type,title,description,body,tags_json,status,quality_json,path,maturity,endorsements,usage_count) VALUES('b','Reference','Policy B','B','shared policy term [A](a.md)','[]','published',?,'reference/b.md',1.0,3,4)",
            (quality,),
        )
        entity_id = connection.execute("INSERT INTO entities(name,slug,normalized_name) VALUES('Policy','policy','policy')").lastrowid
        connection.execute("INSERT INTO concept_entities(concept_id,entity_id) VALUES('a',?)", (entity_id,))
        connection.execute("INSERT INTO concept_entities(concept_id,entity_id) VALUES('b',?)", (entity_id,))
    index_concept(db, "a", "Policy A", "shared policy term")
    index_concept(db, "b", "Policy B", "shared policy term [A](a.md)")
    recompute_value_graph(db)
    first = search(db, "shared policy term", 10)
    second = search(db, "shared policy term", 10)
    assert [item["id"] for item in first["results"]] == [item["id"] for item in second["results"]]
    assert first["results"][0]["id"] == "b"
    assert first["results"][0]["value_score"] > first["results"][1]["value_score"]
    with db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM concept_links").fetchone()[0] == 1


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _commit_company_baseline(settings, message: str) -> None:
    (settings.root / ".gitignore").write_text(
        ".ckb/\n.local-sources/\nweb/dist/\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", ".gitignore", ".local-knowledge/company.toml"],
        cwd=settings.root,
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
            message,
        ],
        cwd=settings.root,
        check=True,
        capture_output=True,
    )


def test_branch_acl_unique_endorsement_and_usage_api(settings) -> None:
    db = Database(settings.database)
    db.initialize()
    admin_id = create_user(db, "admin", "administrator-password", "admin")
    reviewer_id = create_user(db, "reviewer", "reviewer-password", "reviewer")
    create_user(db, "reader", "reader-password-123", "reader")
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1") as admin:
        csrf = _login(admin, "admin", "administrator-password")
        created = admin.post("/api/v1/branches", headers={"X-CSRF-Token": csrf}, json={"name": "finance"})
        assert created.status_code == 201
        branch_id = created.json()["id"]
        assert admin.post(
            f"/api/v1/branches/{branch_id}/members",
            headers={"X-CSRF-Token": csrf},
            json={"user_id": reviewer_id, "role": "reviewer"},
        ).status_code == 200
        with db.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO concepts(id,branch_id,type,title,description,body,tags_json,status,quality_json,path) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("finance-policy", branch_id, "Reference", "Finance", "Finance policy", "---\ntype: Reference\n---\n\n# Finance\n", "[]", "published", json.dumps({}), "reference/finance-policy.md"),
            )
        first = admin.post("/api/v1/concepts/finance-policy/endorse", headers={"X-CSRF-Token": csrf})
        second = admin.post("/api/v1/concepts/finance-policy/endorse", headers={"X-CSRF-Token": csrf})
        assert first.json()["endorsements"] == second.json()["endorsements"] == 1
        assert admin.post("/api/v1/concepts/finance-policy/usage", headers={"X-CSRF-Token": csrf}).json()["usage_count"] == 1
        assert admin.post("/api/v1/concepts/finance-policy/usage", headers={"X-CSRF-Token": csrf}).json()["usage_count"] == 1
    with TestClient(app, base_url="http://127.0.0.1") as reader:
        _login(reader, "reader", "reader-password-123")
        denied = reader.post("/api/v1/search", json={"query": "finance", "branch": "finance"})
        assert denied.status_code == 403


def test_committed_publication_recovers_after_database_apply_failure(settings, fake_lm, git_repo, monkeypatch) -> None:
    settings.auto_publish = False
    _commit_company_baseline(
        settings,
        "chore: initialize publication recovery fixture",
    )
    source = settings.root / ".local-sources" / "recover.txt"
    source.write_text("Recoverable publication has exact cited evidence.", encoding="utf-8")
    service = KnowledgeService(settings, lm_client=fake_lm)
    source_id = service.add_source("file", str(source), None, [], None)
    concept = service.run_job(service.enqueue(source_id, None))["concepts"][0]
    original_index = pipeline_module.index_concept
    monkeypatch.setattr(pipeline_module, "index_concept", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("injected index failure")))
    with pytest.raises(RuntimeError, match="injected index failure"):
        service.publish_concept(concept["concept_id"], {"id": None, "username": "system", "role": "admin"}, direct=True)
    with service.db.connect() as connection:
        publication = connection.execute("SELECT id,state FROM publications").fetchone()
        assert publication["state"] == "committed"
    monkeypatch.setattr(pipeline_module, "index_concept", original_index)
    assert service.recover_publications() == 1
    with service.db.connect() as connection:
        assert connection.execute("SELECT status FROM concepts WHERE id=?", (concept["concept_id"],)).fetchone()["status"] == "published"
        assert connection.execute("SELECT state FROM publications WHERE id=?", (publication["id"],)).fetchone()["state"] == "applied"


def test_abandoned_direct_publication_retries_with_same_identity(
    settings,
    fake_lm,
    git_repo,
    monkeypatch,
) -> None:
    settings.auto_publish = False
    _commit_company_baseline(settings, "chore: initialize retry fixture")
    source = settings.root / ".local-sources" / "retry-publication.txt"
    source.write_text(
        "A transient Git failure must permit one safe publication retry.",
        encoding="utf-8",
    )
    service = KnowledgeService(settings, lm_client=fake_lm)
    source_id = service.add_source("file", str(source), None, [], None)
    concept = service.run_job(service.enqueue(source_id, None))["concepts"][0]
    real_publish = pipeline_module.publish_markdown
    attempts = 0

    def flaky_publish(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise pipeline_module.GitOperationError("transient Git failure")
        return real_publish(*args, **kwargs)

    monkeypatch.setattr(pipeline_module, "publish_markdown", flaky_publish)
    actor = {"id": None, "username": "system", "role": "admin"}
    first = service.publish_concept(
        concept["concept_id"],
        actor,
        direct=True,
    )
    with service.db.connect() as connection:
        abandoned = connection.execute(
            "SELECT id,state,error FROM publications"
        ).fetchone()
    assert first["error"] == "transient Git failure"
    assert abandoned["state"] == "abandoned"

    second = service.publish_concept(
        concept["concept_id"],
        actor,
        direct=True,
    )

    assert attempts == 2
    assert second["status"] == "published", second
    assert second["publication_id"] == abandoned["id"] == first["publication_id"]
    assert second["commit"]
    with service.db.connect() as connection:
        publication = connection.execute(
            "SELECT state,commit_hash,error FROM publications WHERE id=?",
            (second["publication_id"],),
        ).fetchone()
        count = connection.execute("SELECT COUNT(*) FROM publications").fetchone()[0]
    assert publication["state"] == "applied"
    assert publication["commit_hash"] == second["commit"]
    assert publication["error"] is None
    assert count == 1


def test_pending_publication_recovers_commit_from_git_trailer(settings, fake_lm, git_repo) -> None:
    settings.auto_publish = False
    _commit_company_baseline(
        settings,
        "chore: initialize trailer recovery fixture",
    )
    source = settings.root / ".local-sources" / "trailer-recovery.txt"
    source.write_text("The Git trailer makes publication recovery durable.", encoding="utf-8")
    service = KnowledgeService(settings, lm_client=fake_lm)
    source_id = service.add_source("file", str(source), None, [], None)
    concept = service.run_job(service.enqueue(source_id, None))["concepts"][0]
    published = service.publish_concept(concept["concept_id"], {"id": None, "username": "system", "role": "admin"}, direct=True)
    with service.db.transaction(immediate=True) as connection:
        connection.execute("UPDATE publications SET state='pending',commit_hash=NULL WHERE id=?", (published["publication_id"],))
        connection.execute("UPDATE concepts SET status='review',canonical_commit=NULL WHERE id=?", (concept["concept_id"],))
        connection.execute("DELETE FROM search_fts WHERE concept_id=?", (concept["concept_id"],))
    assert service.recover_publications() == 1
    with service.db.connect() as connection:
        row = connection.execute("SELECT state,commit_hash FROM publications WHERE id=?", (published["publication_id"],)).fetchone()
        assert row["state"] == "applied"
        assert row["commit_hash"] == published["commit"]


def test_management_api_covers_sources_feedback_entities_publications_and_secrets(
    settings,
    git_repo,
) -> None:
    ignore = settings.root / ".gitignore"
    ignore.write_text(
        ".ckb/\n.local-sources/\nweb/dist/\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", ".gitignore", ".local-knowledge/company.toml"],
        cwd=settings.root,
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
            "chore: initialize management API repository",
        ],
        cwd=settings.root,
        check=True,
        capture_output=True,
    )
    db = Database(settings.database)
    db.initialize()
    create_user(db, "admin", "administrator-password", "admin")
    reviewer_id = create_user(db, "reviewer", "reviewer-password", "reviewer")
    app = create_app(settings)
    key = bytes(reversed(range(32)))
    app.state.secret_store._key_provider = lambda create: key
    app.state.service.secrets._key_provider = lambda create: key
    with TestClient(app, base_url="http://127.0.0.1") as client:
        csrf = _login(client, "admin", "administrator-password")
        assert client.get("/api/v1/users").status_code == 200
        branch = client.post("/api/v1/branches", headers={"X-CSRF-Token": csrf}, json={"name": "operations"}).json()
        branch_id = branch["id"]
        assert client.get(f"/api/v1/branches/{branch_id}/members").status_code == 200
        assert client.post(
            f"/api/v1/branches/{branch_id}/members",
            headers={"X-CSRF-Token": csrf},
            json={"user_id": reviewer_id, "role": "reviewer"},
        ).status_code == 200
        source_path = settings.root / ".local-sources" / "operations.txt"
        source_path.write_text("Operations evidence is locally stored.", encoding="utf-8")
        source = client.post(
            "/api/v1/sources",
            headers={"X-CSRF-Token": csrf},
            json={"kind": "file", "uri": str(source_path), "allowed_domains": [], "branch": "operations"},
        )
        assert source.status_code == 201
        source_id = source.json()["id"]
        assert any(item["branch"] == "operations" for item in client.get("/api/v1/sources").json())
        job_id = client.post(f"/api/v1/sources/{source_id}/ingest", headers={"X-CSRF-Token": csrf}).json()["job_id"]
        assert client.post(f"/api/v1/jobs/{job_id}/cancel", headers={"X-CSRF-Token": csrf}).json()["status"] == "cancelled"
        assert client.post(f"/api/v1/jobs/{job_id}/retry", headers={"X-CSRF-Token": csrf}).json()["status"] == "queued"
        assert client.get("/api/v1/jobs").status_code == 200

        feedback_id = client.post(
            "/api/v1/feedback",
            headers={"X-CSRF-Token": csrf},
            json={"query": "missing operations policy", "details": "No result"},
        ).json()["id"]
        assert client.get("/api/v1/feedback").status_code == 200
        assert client.patch(
            f"/api/v1/feedback/{feedback_id}",
            headers={"X-CSRF-Token": csrf},
            json={"status": "resolved"},
        ).json()["status"] == "resolved"

        with db.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO concepts(id,branch_id,type,title,description,body,tags_json,status,quality_json,path) VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("ops-concept", branch_id, "Reference", "Operations", "Operations", "---\ntype: Reference\n---\n\n# Operations\n", "[]", "published", "{}", "reference/ops.md"),
            )
            entity_id = connection.execute("INSERT INTO entities(name,slug,normalized_name) VALUES('Operations','operations','operations')").lastrowid
            connection.execute("INSERT INTO concept_entities(concept_id,entity_id) VALUES('ops-concept',?)", (entity_id,))
            connection.execute(
                "INSERT INTO publications(id,concept_id,branch_id,candidate_branch,state,idempotency_key,created_by) VALUES('pub-test','ops-concept',?,'ckb/reviewer/pub-test','committed','idem-test',?)",
                (branch_id, reviewer_id),
            )
        entities = client.get("/api/v1/entities?branch=operations")
        assert entities.status_code == 200 and entities.json()[0]["name"] == "Operations"
        assert client.get(f"/api/v1/entities/{entity_id}?branch=operations").status_code == 200
        assert client.get("/api/v1/publications").status_code == 200

        assert client.put("/api/v1/secrets/lm-studio", headers={"X-CSRF-Token": csrf}, json={"value": "lm-token"}).status_code == 200
        assert client.put(
            "/api/v1/secrets/git",
            headers={"X-CSRF-Token": csrf},
            json={"username": "git-user", "token": "git-token"},
        ).status_code == 200
        secret_status = client.get("/api/v1/secrets/status").json()
        assert secret_status["global"] and secret_status["git"]
        assert client.delete("/api/v1/secrets/lm-studio", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert client.delete("/api/v1/secrets/git", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert client.get("/api/v1/git/status").status_code == 200
        assert client.post("/api/v1/git/pull", headers={"X-CSRF-Token": csrf}).status_code == 200


def test_candidate_branch_isolated_until_branch_admin_merge(settings, fake_lm, git_repo) -> None:
    settings.auto_publish = False
    ignore = settings.root / ".gitignore"
    ignore.write_text(".ckb/\n*.txt\n", encoding="utf-8")

    subprocess.run(
        ["git", "add", ".gitignore", ".local-knowledge/company.toml"],
        cwd=settings.root,
        check=True,
    )
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "chore: initialize"],
        cwd=settings.root,
        check=True,
        capture_output=True,
    )
    service = KnowledgeService(settings, lm_client=fake_lm)
    reviewer_id = create_user(service.db, "reviewer", "reviewer-password", "reviewer")
    reviewer = {"id": reviewer_id, "username": "reviewer", "role": "reviewer"}
    admin = {"id": None, "username": "admin", "role": "admin"}
    source = settings.root / ".local-sources" / "candidate.txt"
    source.write_text("The canonical policy is version one.", encoding="utf-8")
    source_id = service.add_source("file", str(source), None, [], reviewer_id)
    first = service.run_job(service.enqueue(source_id, reviewer_id))["concepts"][0]
    assert service.review(first["concept_id"], "approve", actor=admin)["status"] == "published"
    source.write_text("The canonical policy is version two.", encoding="utf-8")
    update = service.run_job(service.enqueue(source_id, reviewer_id))["concepts"][0]
    candidate = service.review(update["concept_id"], "approve", actor=reviewer)
    assert candidate["status"] == "review"
    assert candidate["candidate_branch"].startswith("ckb/reviewer/")
    with service.db.connect() as connection:
        assert connection.execute("SELECT state FROM publications WHERE id=?", (candidate["publication_id"],)).fetchone()["state"] == "committed"
    merged = service.merge_publication(candidate["publication_id"], {"id": None, "username": "admin", "role": "admin"})
    assert merged["state"] == "applied"
    with service.db.connect() as connection:
        assert connection.execute("SELECT status FROM concepts WHERE id=?", (update["concept_id"],)).fetchone()["status"] == "published"


def test_authenticated_api_ingest_revise_review_search_and_logout(settings, fake_lm, git_repo) -> None:
    _commit_company_baseline(
        settings,
        "chore: initialize authenticated API fixture",
    )
    db = Database(settings.database)
    db.initialize()
    create_user(db, "admin", "administrator-password", "admin")
    app = create_app(settings)
    app.state.service.lm = fake_lm
    source = settings.root / ".local-sources" / "api-policy.txt"
    source.write_text("API policy evidence is exact and durable.", encoding="utf-8")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-password"}).status_code == 401
        csrf = _login(client, "admin", "administrator-password")
        assert client.get("/api/v1/auth/me").status_code == 200
        source_id = client.post(
            "/api/v1/sources",
            headers={"X-CSRF-Token": csrf},
            json={"kind": "file", "uri": str(source), "allowed_domains": []},
        ).json()["id"]
        job_id = client.post(f"/api/v1/sources/{source_id}/ingest", headers={"X-CSRF-Token": csrf}).json()["job_id"]
        result = client.post(f"/api/v1/jobs/{job_id}/run", headers={"X-CSRF-Token": csrf})
        assert result.status_code == 200
        concept_id = result.json()["concepts"][0]["concept_id"]
        concepts = client.get("/api/v1/concepts?status_filter=published").json()
        assert concepts[0]["id"] == concept_id
        detail = client.get(f"/api/v1/concepts/{concept_id}").json()
        claim = detail["claims"][0]
        citation = claim["citations"][0]
        fabricated = client.patch(
            f"/api/v1/concepts/{concept_id}/claims/{claim['id']}",
            headers={"X-CSRF-Token": csrf},
            json={"text": "Completely unrelated bankruptcy assertion", "locator": citation["locator"], "excerpt": citation["excerpt"]},
        )
        assert fabricated.status_code == 200
        blocked = client.post(
            f"/api/v1/concepts/{concept_id}/review",
            headers={"X-CSRF-Token": csrf},
            json={"decision": "approve"},
        )
        assert blocked.status_code == 400
        revised = client.patch(
            f"/api/v1/concepts/{concept_id}/claims/{claim['id']}",
            headers={"X-CSRF-Token": csrf},
            json={"text": claim["text"], "locator": citation["locator"], "excerpt": citation["excerpt"]},
        )
        assert revised.status_code == 200
        approved = client.post(
            f"/api/v1/concepts/{concept_id}/review",
            headers={"X-CSRF-Token": csrf},
            json={"decision": "approve"},
        )
        assert approved.status_code == 200
        assert client.post("/api/v1/search", json={"query": "API policy"}).status_code == 200
        assert client.post(f"/api/v1/concepts/{concept_id}/endorse", headers={"X-CSRF-Token": csrf}).json()["endorsements"] == 1
        assert client.delete(f"/api/v1/concepts/{concept_id}/endorse", headers={"X-CSRF-Token": csrf}).json()["endorsements"] == 0
        assert client.post("/api/v1/users", headers={"X-CSRF-Token": csrf}, json={"username": "newreader", "password": "reader-password-456", "role": "reader"}).status_code == 201
        assert client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 401


def test_worker_processes_leased_job_with_heartbeat(settings, fake_lm, git_repo) -> None:
    settings.auto_publish = False
    source = settings.root / ".local-sources" / "worker.txt"
    source.write_text("Worker heartbeat protects this job.", encoding="utf-8")
    service = KnowledgeService(settings, lm_client=fake_lm)
    source_id = service.add_source("file", str(source), None, [], None)
    job_id = service.enqueue(source_id, None)
    assert run_worker(service, once=True) == 1
    with service.db.connect() as connection:
        assert connection.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()["status"] == "succeeded"
