# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from local_knowledge.ckb.db import Database
from local_knowledge.ckb.pipeline import KnowledgeService
from local_knowledge.ckb.search import search


def test_website_source_requires_explicit_public_allowlist(
    settings,
    fake_lm,
) -> None:
    service = KnowledgeService(settings, lm_client=fake_lm)

    with pytest.raises(ValueError, match="explicit allowed domain"):
        service.add_source(
            "website",
            "https://public.example/policy",
            None,
            [],
            None,
        )
    with pytest.raises(ValueError, match="non-global"):
        service.add_source(
            "website",
            "https://127.0.0.1/policy",
            None,
            ["127.0.0.1"],
            None,
        )
    source_id = service.add_source(
        "website",
        "https://sub.public.example/policy",
        None,
        [".PUBLIC.EXAMPLE."],
        None,
    )

    with service.db.connect() as connection:
        rows = connection.execute(
            "SELECT id,allowed_domains FROM sources ORDER BY id"
        ).fetchall()
    assert [(row["id"], json.loads(row["allowed_domains"])) for row in rows] == [
        (source_id, ["public.example"])
    ]


def test_end_to_end_ingest_publish_commit_and_search(
    settings,
    fake_lm,
    publishable_git_repo: Path,
) -> None:
    source_file = settings.root / ".local-sources" / "revenue-policy.md"
    source_file.write_text(
        "# Chính sách doanh thu\nDoanh thu hàng tuần được báo cáo vào thứ Hai.\nWeekly revenue is reported every Monday.\n",
        encoding="utf-8",
    )
    service = KnowledgeService(settings, lm_client=fake_lm)
    source_id = service.add_source("file", str(source_file), "Revenue policy", [], None)
    job_id = service.enqueue(source_id, None)
    result = service.run_job(job_id)
    concept = result["concepts"][0]
    assert concept["status"] == "published"
    assert concept["quality"]["coverage"] == 1.0
    assert concept["commit"] and concept["commit"] != "no changes"
    concept_path = settings.bundle_dir / "reference" / f"{concept['concept_id']}.md"
    assert concept_path.exists()
    assert "# Citations" in concept_path.read_text(encoding="utf-8")
    log = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=settings.root, text=True, capture_output=True, check=True).stdout
    assert "publish" in log

    without_accents = search(service.db, "doanh thu", 10, fake_lm)
    assert without_accents["results"][0]["id"] == concept["concept_id"]
    english = search(service.db, '"weekly revenue"', 10, fake_lm)
    assert english["results"][0]["id"] == concept["concept_id"]
    assert english["semantic_available"]
    with service.db.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM chunks WHERE concept_id=?", (concept["concept_id"],)).fetchone()[0] > 0
        assert connection.execute("SELECT COUNT(*) FROM chunk_embeddings").fetchone()[0] > 0
        assert connection.execute("SELECT COUNT(*) FROM concept_entities WHERE concept_id=?", (concept["concept_id"],)).fetchone()[0] == 1

    duplicate_job = service.enqueue(source_id, None)
    duplicate = service.run_job(duplicate_job)
    assert duplicate["concepts"][0]["status"] == "unchanged"

    canonical_before = concept_path.read_text(encoding="utf-8")
    source_file.write_text("# Chính sách doanh thu\nDoanh thu hàng tuần được báo cáo vào thứ Ba.\n", encoding="utf-8")
    update = service.run_job(service.enqueue(source_id, None))["concepts"][0]
    assert update["status"] == "review"
    assert "published version already exists" in " ".join(update["quality"]["reasons"])
    assert concept_path.read_text(encoding="utf-8") == canonical_before
    still_published = search(service.db, "doanh thu", 10, fake_lm)
    assert still_published["results"][0]["id"] == concept["concept_id"]
    approved = service.review(update["concept_id"], "approve", title="Updated Revenue Policy")
    assert approved["status"] == "published"
    after_approval = search(service.db, "thu Ba", 10, fake_lm)
    assert after_approval["results"][0]["id"] == update["concept_id"]
    with service.db.connect() as connection:
        assert connection.execute("SELECT 1 FROM concepts WHERE id=?", (concept["concept_id"],)).fetchone() is None
        updated_row = connection.execute("SELECT title FROM concepts WHERE id=?", (update["concept_id"],)).fetchone()
        assert updated_row["title"] == "Updated Revenue Policy"
    assert "title: Updated Revenue Policy" in concept_path.read_text(encoding="utf-8")


def test_branch_filter_is_applied_before_fts_candidate_limit(settings) -> None:
    db = Database(settings.database)
    db.initialize()
    quality = json.dumps({"coverage": 1.0, "minimum_confidence": 1.0, "average_confidence": 1.0})
    with db.transaction(immediate=True) as connection:
        finance_branch_id = connection.execute(
            "INSERT INTO branches(name,is_canonical,protected) VALUES('finance',0,1)"
        ).lastrowid
        connection.execute(
            "INSERT INTO concepts(id,branch_id,type,title,description,body,tags_json,status,quality_json) "
            "VALUES('main-needle',1,'Reference','Canonical result','Main result','needle','[]','published',?)",
            (quality,),
        )
        connection.execute(
            "INSERT INTO search_fts(concept_id,title,body,folded) VALUES('main-needle','Canonical result','needle','needle')"
        )
        finance_concepts = [
            (
                f"finance-needle-{index}",
                finance_branch_id,
                "Reference",
                f"needle finance {index}",
                "Finance result",
                "needle needle needle",
                "[]",
                "published",
                quality,
            )
            for index in range(250)
        ]
        connection.executemany(
            "INSERT INTO concepts(id,branch_id,type,title,description,body,tags_json,status,quality_json) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            finance_concepts,
        )
        connection.executemany(
            "INSERT INTO search_fts(concept_id,title,body,folded) VALUES(?,?,?,?)",
            [
                (concept_id, title, body, f"{title} {body}".lower())
                for concept_id, _branch_id, _type, title, _description, body, _tags, _status, _quality in finance_concepts
            ],
        )

    result = search(db, "needle", 10, branch_id=1)

    assert [item["id"] for item in result["results"]] == ["main-needle"]


class LowQualityLM:
    chat_model = "low"
    embedding_model = "low"
    def health(self): return {"reachable": True}
    def extract_claims(self, title, language, sections):
        return [{"text": "Unsupported inference", "confidence": 0.4, "section_index": 0, "excerpt": "not present"}]
    def embed(self, texts): return [[1.0, 0.0] for _ in texts]


def test_low_quality_routes_to_review(settings, git_repo: Path) -> None:
    source_file = settings.root / ".local-sources" / "note.txt"
    source_file.write_text("A durable statement with enough content.", encoding="utf-8")
    service = KnowledgeService(settings, lm_client=LowQualityLM())
    source_id = service.add_source("file", str(source_file), None, [], None)
    result = service.run_job(service.enqueue(source_id, None))["concepts"][0]
    assert result["status"] == "review"
    assert result["quality"]["coverage"] == 0
    assert not list(settings.bundle_dir.rglob("note*.md"))
    with service.db.connect() as connection:
        row = connection.execute("SELECT status FROM concepts WHERE id=?", (result["concept_id"],)).fetchone()
    assert row["status"] == "review"
    try:
        service.review(result["concept_id"], "approve")
    except ValueError as exc:
        assert "verified citations" in str(exc)
    else:
        raise AssertionError("uncited concept was approved")


def test_job_cancel_and_retry(settings, fake_lm, git_repo: Path) -> None:
    source_file = settings.root / ".local-sources" / "jobs.txt"
    source_file.write_text("A durable job statement for testing.", encoding="utf-8")
    service = KnowledgeService(settings, lm_client=fake_lm)
    source_id = service.add_source("file", str(source_file), None, [], None)
    job_id = service.enqueue(source_id, None)
    assert service.cancel_job(job_id)
    assert not service.cancel_job(job_id)
    assert service.retry_job(job_id)
    leased = service.lease_job()
    assert leased and leased["id"] == job_id


class FlakyLM:
    chat_model = "flaky"
    embedding_model = "flaky"
    def __init__(self): self.calls = 0
    def health(self): return {"reachable": True}
    def extract_claims(self, title, language, sections):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary model failure")
        excerpt = sections[0].text
        return [{"text": excerpt, "confidence": 0.96, "section_index": 0, "excerpt": excerpt}]
    def embed(self, texts): return [[1.0, 1.0] for _ in texts]


def test_failed_extraction_can_retry_same_document(
    settings,
    publishable_git_repo: Path,
) -> None:
    source_file = settings.root / ".local-sources" / "retry.txt"
    source_file.write_text("Retry preserves this exact cited statement.", encoding="utf-8")
    lm = FlakyLM()
    service = KnowledgeService(settings, lm_client=lm)
    source_id = service.add_source("file", str(source_file), None, [], None)
    job_id = service.enqueue(source_id, None)
    try:
        service.run_job(job_id)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the first extraction to fail")
    assert service.retry_job(job_id)
    result = service.run_job(job_id)
    assert result["concepts"][0]["status"] == "published"
