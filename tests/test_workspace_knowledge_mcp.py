# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from local_knowledge.ckb.db import Database


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SCRIPTS = ROOT / "plugins" / "local-knowledge-suite" / "scripts"
if str(PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS))

import workspace_knowledge_core as knowledge  # noqa: E402


def _initialized_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    company_id: str,
) -> tuple[Path, Path]:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local-app-data"))
    for name in ("CKB_ROOT", "CKB_DATA_DIR", "CKB_DATABASE", "CKB_BUNDLE_DIR"):
        monkeypatch.delenv(name, raising=False)
    company = tmp_path / "company"
    project = tmp_path / "project"
    company.mkdir()
    project.mkdir()
    knowledge.initialize_company_repository(company, "Compatibility Company", company_id)
    knowledge.bootstrap_workspace(
        str(project.resolve()),
        company_id,
        profile="combined",
    )
    return company, project


def _seed_company_claim(
    company: Path,
    *,
    concept_id: str,
    title: str,
    claim_text: str,
    citations: list[dict[str, str]],
    chunk_citations: list[dict[str, str]],
) -> None:
    database_path = company / ".ckb" / "ckb.sqlite3"
    db = Database(database_path)
    db.initialize()
    primary = citations[0]
    quality = json.dumps(
        {"coverage": 1.0, "minimum_confidence": 0.96, "average_confidence": 0.96}
    )
    with db.transaction(immediate=True) as connection:
        source_id = int(
            connection.execute(
                "INSERT INTO sources(kind,uri,title,allowed_domains,branch_id) "
                "VALUES('website',?,?,?,1)",
                (primary["source_uri"], title, '["example.test"]'),
            ).lastrowid
        )
        document_id = int(
            connection.execute(
                "INSERT INTO documents(source_id,branch_id,source_uri,title,media_type,"
                "checksum,language,normalized_json) VALUES(?,1,?,?,?,?,?,?)",
                (
                    source_id,
                    primary["source_uri"],
                    title,
                    "text/html",
                    primary["checksum"],
                    "en",
                    "{}",
                ),
            ).lastrowid
        )
        connection.execute(
            "INSERT INTO concepts(id,document_id,branch_id,type,title,description,body,"
            "tags_json,status,quality_json) "
            "VALUES(?, ?,1,'Reference',?,'Citation contract',?,'[]','published',?)",
            (concept_id, document_id, title, claim_text, quality),
        )
        for citation in chunk_citations:
            connection.execute(
                "INSERT INTO chunks(document_id,concept_id,locator,title,text,checksum) "
                "VALUES(?,?,?,?,?,?)",
                (
                    document_id,
                    concept_id,
                    citation["locator"],
                    title,
                    citation["excerpt"],
                    hashlib.sha256(citation["excerpt"].encode("utf-8")).hexdigest(),
                ),
            )
        connection.execute(
            "INSERT INTO search_fts(concept_id,title,body,folded) VALUES(?,?,?,?)",
            (concept_id, title, claim_text, claim_text.casefold()),
        )
        connection.execute(
            "INSERT INTO claims(concept_id,text,confidence,document_checksum,source_uri,"
            "locator,excerpt,citations_json,verified) VALUES(?,?,?,?,?,?,?,?,1)",
            (
                concept_id,
                claim_text,
                0.96,
                primary["checksum"],
                primary["source_uri"],
                primary["locator"],
                primary["excerpt"],
                json.dumps(citations),
            ),
        )


def test_recall_finds_skill_guidance_without_conflating_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, project = _initialized_project(tmp_path, monkeypatch, "compat-skill")
    skill = project / "skills" / "release-helper" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: release-helper\ndescription: Validate a release checklist before deployment.\n---\n"
        "# Release helper\nCheck the rollback plan and deployment evidence.\n",
        encoding="utf-8",
    )

    result = knowledge.recall_context(
        "release deployment checklist",
        str(project.resolve()),
        include_memory=False,
        include_company=False,
    )

    match = result["skills"]["results"][0]
    assert match["name"] == "release-helper"
    assert match["authority"] == "instruction"
    assert result["insufficient_evidence"] is False


def test_capture_is_distilled_and_recall_finds_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, project = _initialized_project(tmp_path, monkeypatch, "compat-memory")

    captured = knowledge.capture_memory(
        root=str(project.resolve()),
        kind="decision",
        title="Package manager",
        text="Use pnpm for frontend dependencies.",
        memory_key="frontend:package-manager",
        event_id="evt_mcp_package_manager",
        tags=["frontend"],
    )

    assert captured["ok"] is True
    assert captured["distilled"] is True
    assert captured["memory_ids"]
    assert captured["pending"] == 0

    recalled = knowledge.recall_context(
        "frontend package manager pnpm",
        str(project.resolve()),
        include_skills=False,
        include_company=False,
    )
    memory = recalled["memory"]["results"][0]
    assert memory["id"] == captured["memory_ids"][0]
    assert memory["authority"] == "remembered_context"
    assert "pnpm" in memory["excerpt"]


def test_company_recall_returns_verified_structured_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    company, project = _initialized_project(tmp_path, monkeypatch, "compat-company")
    database_path = company / ".ckb" / "ckb.sqlite3"
    db = Database(database_path)
    db.initialize()
    quality = json.dumps(
        {"coverage": 1.0, "minimum_confidence": 0.96, "average_confidence": 0.96}
    )
    citation = {
        "source_uri": "https://example.test/policies/revenue",
        "locator": "section 2",
        "excerpt": "Quarterly revenue is reviewed on Monday.",
        "checksum": "d" * 64,
    }
    with db.transaction(immediate=True) as connection:
        source_id = int(
            connection.execute(
                "INSERT INTO sources(kind,uri,title,allowed_domains,branch_id) VALUES('website',?,?,?,1)",
                (citation["source_uri"], "Revenue source", '["example.test"]'),
            ).lastrowid
        )
        document_id = int(
            connection.execute(
                "INSERT INTO documents(source_id,branch_id,source_uri,title,media_type,checksum,language,normalized_json) "
                "VALUES(?,1,?,?,?,?,?,?)",
                (
                    source_id,
                    citation["source_uri"],
                    "Revenue source",
                    "text/html",
                    citation["checksum"],
                    "en",
                    "{}",
                ),
            ).lastrowid
        )
        connection.execute(
            "INSERT INTO concepts(id,document_id,branch_id,type,title,description,body,tags_json,status,quality_json) "
            "VALUES('revenue-policy',?,1,'Reference','Revenue policy','Review schedule',?, '[]','published',?)",
            (document_id, "Quarterly revenue is reviewed on Monday.", quality),
        )
        connection.execute(
            "INSERT INTO chunks(document_id,concept_id,locator,title,text,checksum) VALUES(?,?,?,?,?,?)",
            (
                document_id,
                "revenue-policy",
                citation["locator"],
                "Revenue source",
                citation["excerpt"],
                hashlib.sha256(citation["excerpt"].encode("utf-8")).hexdigest(),
            ),
        )
        connection.execute(
            "INSERT INTO search_fts(concept_id,title,body,folded) VALUES(?,?,?,?)",
            (
                "revenue-policy",
                "Revenue policy",
                "Quarterly revenue is reviewed on Monday.",
                "quarterly revenue is reviewed on monday",
            ),
        )
        connection.execute(
            "INSERT INTO claims(concept_id,text,confidence,document_checksum,source_uri,locator,excerpt,citations_json,verified) "
            "VALUES(?,?,?,?,?,?,?,?,1)",
            (
                    "revenue-policy",
                    "Quarterly revenue is reviewed on Monday.",
                    0.96,
                    citation["checksum"],
                citation["source_uri"],
                citation["locator"],
                citation["excerpt"],
                json.dumps([citation]),
            ),
        )

    result = knowledge.recall_context(
        "quarterly revenue Monday",
        str(project.resolve()),
        include_skills=False,
        include_memory=False,
    )

    assert result["company"]["evidence_sufficient"] is True
    company = result["company"]["results"][0]
    assert company["evidence_sufficient"] is True
    claim = company["claims"][0]
    assert claim["verified"] is True
    assert claim["source_uri"] == citation["source_uri"]
    assert claim["locator"] == citation["locator"]
    assert claim["excerpt"] == citation["excerpt"]
    assert claim["citations"][0]["verified"] is True


def test_company_recall_accepts_multiple_valid_public_website_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    company, project = _initialized_project(
        tmp_path,
        monkeypatch,
        "compat-multiple-citations",
    )
    first = {
        "source_uri": "https://example.test/policies/change-control",
        "locator": "section 1",
        "excerpt": "Production changes require an approved request.",
        "checksum": "f" * 64,
    }
    second = {
        **first,
        "locator": "section 3",
        "excerpt": "Emergency changes require a retrospective review.",
    }
    _seed_company_claim(
        company,
        concept_id="change-control-policy",
        title="Change control policy",
        claim_text="Production changes require approval and retrospective review.",
        citations=[first, second],
        chunk_citations=[first, second],
    )

    result = knowledge.recall_context(
        "production changes approval retrospective review",
        str(project.resolve()),
        include_skills=False,
        include_memory=False,
    )

    company_result = result["company"]["results"][0]
    claim = company_result["claims"][0]
    assert [citation["verified"] for citation in claim["citations"]] == [
        True,
        True,
    ]
    assert claim["verified"] is True
    assert claim["evidence_sufficient"] is True
    assert company_result["evidence_sufficient"] is True
    assert result["company"]["evidence_sufficient"] is True


def test_company_recall_fails_closed_when_one_of_multiple_citations_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    company, project = _initialized_project(
        tmp_path,
        monkeypatch,
        "compat-mixed-citations",
    )
    valid = {
        "source_uri": "https://example.test/policies/security",
        "locator": "section 1",
        "excerpt": "Security exceptions require reviewer approval.",
        "checksum": "e" * 64,
    }
    invalid = {
        **valid,
        "locator": "section forged",
        "excerpt": "A fabricated excerpt that is absent from the stored document.",
    }
    _seed_company_claim(
        company,
        concept_id="security-policy",
        title="Security policy",
        claim_text="Security exceptions require reviewer approval.",
        citations=[valid, invalid],
        chunk_citations=[valid],
    )

    result = knowledge.recall_context(
        "security exceptions reviewer approval",
        str(project.resolve()),
        include_skills=False,
        include_memory=False,
    )

    company_result = result["company"]["results"][0]
    claim = company_result["claims"][0]
    assert [citation["verified"] for citation in claim["citations"]] == [
        True,
        False,
    ]
    assert claim["verified"] is False
    assert claim["evidence_sufficient"] is False
    assert company_result["evidence_sufficient"] is False
    assert result["company"]["evidence_sufficient"] is False
    assert result["company"]["insufficient_evidence"] is True


def test_company_recall_fails_closed_when_any_returned_result_lacks_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    company, project = _initialized_project(
        tmp_path,
        monkeypatch,
        "compat-mixed-results",
    )
    verified = {
        "source_uri": "https://example.test/policies/verified-access",
        "locator": "section 1",
        "excerpt": "Shared access reviews require quarterly approval.",
        "checksum": "a" * 64,
    }
    unverified = {
        "source_uri": "https://example.test/policies/unverified-access",
        "locator": "section forged",
        "excerpt": "Shared access reviews may skip approval.",
        "checksum": "b" * 64,
    }
    _seed_company_claim(
        company,
        concept_id="verified-access-policy",
        title="Verified shared access policy",
        claim_text="Shared access reviews require quarterly approval.",
        citations=[verified],
        chunk_citations=[verified],
    )
    _seed_company_claim(
        company,
        concept_id="unverified-access-policy",
        title="Unverified shared access policy",
        claim_text="Shared access reviews may skip approval.",
        citations=[unverified],
        chunk_citations=[],
    )

    result = knowledge.recall_context(
        "shared access reviews approval",
        str(project.resolve()),
        include_skills=False,
        include_memory=False,
    )

    evidence_by_id = {
        item["id"]: item["evidence_sufficient"]
        for item in result["company"]["results"]
    }
    assert evidence_by_id == {
        "verified-access-policy": True,
        "unverified-access-policy": False,
    }
    assert result["company"]["evidence_sufficient"] is False
    assert result["company"]["insufficient_evidence"] is True


def test_compatibility_bridge_requires_initialized_project_not_process_allowlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, allowed = _initialized_project(tmp_path, monkeypatch, "compat-boundary")
    denied = tmp_path / "denied"
    denied.mkdir()
    monkeypatch.setenv("LOCAL_KNOWLEDGE_ALLOWED_ROOTS", str(allowed.resolve()))

    assert knowledge.knowledge_status(str(allowed.resolve()))["root"] == str(allowed.resolve())
    with pytest.raises(knowledge.KnowledgeToolError, match="missing manifest"):
        knowledge.knowledge_status(str(denied.resolve()))
