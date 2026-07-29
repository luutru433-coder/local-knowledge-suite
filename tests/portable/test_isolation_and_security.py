# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

"""Isolation, Windows path, and unsafe override acceptance tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest


pytestmark = pytest.mark.skipif(os.name != "nt", reason="runtime is intentionally Windows-only")


def _company_database(company: Path) -> Path:
    candidates = sorted((company / ".ckb").glob("*.sqlite3"))
    return candidates[0] if candidates else company / ".ckb" / "ckb.sqlite3"


def _seed_verified_company_fact(company: Path, marker: str) -> None:
    from local_knowledge.ckb.db import Database

    database = Database(_company_database(company))
    database.initialize()
    citation = {
        "source_uri": "https://example.test/policies/invoice-close",
        "locator": "section 2",
        "excerpt": marker,
        "checksum": "c" * 64,
    }
    quality = json.dumps(
        {"coverage": 1.0, "minimum_confidence": 0.99, "average_confidence": 0.99}
    )
    with database.transaction(immediate=True) as connection:
        branch = connection.execute(
            "SELECT id FROM branches WHERE is_canonical=1 ORDER BY id LIMIT 1"
        ).fetchone()
        if branch is None:
            cursor = connection.execute(
                "INSERT INTO branches(name,is_canonical,protected) VALUES('main',1,1)"
            )
            branch_id = int(cursor.lastrowid)
        else:
            branch_id = int(branch["id"])
        source_id = int(
            connection.execute(
                "INSERT INTO sources(kind,uri,title,allowed_domains,branch_id) VALUES('website',?,?,?,?)",
                (citation["source_uri"], "Portable source", '["example.test"]', branch_id),
            ).lastrowid
        )
        document_id = int(
            connection.execute(
                "INSERT INTO documents(source_id,branch_id,source_uri,title,media_type,checksum,language,normalized_json) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    source_id,
                    branch_id,
                    citation["source_uri"],
                    "Portable source",
                    "text/html",
                    citation["checksum"],
                    "en",
                    "{}",
                ),
            ).lastrowid
        )
        connection.execute(
            "INSERT INTO concepts(id,document_id,branch_id,type,title,description,body,tags_json,status,quality_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "portable-invoice-policy",
                document_id,
                branch_id,
                "Policy",
                "Portable invoice close policy",
                "Shared company policy",
                marker,
                "[]",
                "published",
                quality,
            ),
        )
        connection.execute(
            "INSERT INTO chunks(document_id,concept_id,locator,title,text,checksum) VALUES(?,?,?,?,?,?)",
            (
                document_id,
                "portable-invoice-policy",
                citation["locator"],
                "Portable source",
                marker,
                hashlib.sha256(marker.encode("utf-8")).hexdigest(),
            ),
        )
        connection.execute(
            "INSERT INTO search_fts(concept_id,title,body,folded) VALUES(?,?,?,?)",
            (
                "portable-invoice-policy",
                "Portable invoice close policy",
                marker,
                marker.casefold(),
            ),
        )
        connection.execute(
            "INSERT INTO claims(concept_id,text,confidence,document_checksum,source_uri,locator,excerpt,citations_json,verified) "
            "VALUES(?,?,?,?,?,?,?,?,1)",
            (
                "portable-invoice-policy",
                marker,
                0.99,
                citation["checksum"],
                citation["source_uri"],
                citation["locator"],
                citation["excerpt"],
                json.dumps([citation]),
            ),
        )


def test_same_company_projects_share_citations_but_not_memory_and_other_company_is_isolated(
    portable_world: Mapping[str, Path | str], portable_runtime: Any
) -> None:
    base = Path(portable_world["base"])
    company = Path(portable_world["company"])
    project_a = Path(portable_world["project_a"])
    project_b = Path(portable_world["project_b"])
    marker = "Invoices close every Friday, shared-company-marker-7719."
    _seed_verified_company_fact(company, marker)

    portable_runtime.capture(
        project_a,
        kind="preference",
        title="Alpha-only package manager",
        text="Project Alpha uses pnpm-alpha-marker-7719.",
        memory_key="project:package-manager",
        event_id="evt_project_alpha_isolation",
    )
    alpha_memory = portable_runtime.recall(
        project_a,
        "Alpha-only package manager",
        include_skills=False,
        include_company=False,
    )
    beta_memory = portable_runtime.recall(
        project_b,
        "Alpha-only package manager",
        include_skills=False,
        include_company=False,
    )
    assert "pnpm-alpha-marker-7719" in portable_runtime.section_text(alpha_memory, "memory")
    assert "pnpm-alpha-marker-7719" not in portable_runtime.section_text(beta_memory, "memory")
    assert (project_a / ".memorizer").resolve() != (project_b / ".memorizer").resolve()

    alpha_company = portable_runtime.recall(
        project_a,
        "invoice close policy Friday",
        include_skills=False,
        include_memory=False,
    )
    beta_company = portable_runtime.recall(
        project_b,
        "invoice close policy Friday",
        include_skills=False,
        include_memory=False,
    )
    assert marker.casefold() in portable_runtime.section_text(alpha_company, "company")
    assert marker.casefold() in portable_runtime.section_text(beta_company, "company")

    other_company = base / "Other Company Knowledge"
    project_c = base / "Project Gamma"
    other_company.mkdir()
    project_c.mkdir()
    portable_runtime.init_company(other_company, "fabrikam-contract", "Fabrikam Contract")
    portable_runtime.register_company(other_company)
    portable_runtime.init_project(project_c, "fabrikam-contract")
    other_result = portable_runtime.recall(
        project_c,
        "invoice close policy Friday",
        include_skills=False,
        include_memory=False,
    )
    assert marker.casefold() not in portable_runtime.section_text(other_result, "company")
    other_memory = portable_runtime.recall(
        project_c,
        "Alpha-only package manager",
        include_skills=False,
        include_company=False,
    )
    assert "pnpm-alpha-marker-7719" not in portable_runtime.section_text(
        other_memory, "memory"
    )


def test_unicode_and_space_windows_paths_support_accent_insensitive_memory_recall(
    tmp_path: Path,
    isolated_localappdata: Path,
    portable_runtime: Any,
) -> None:
    company = tmp_path / "Công ty Dữ liệu Việt Nam"
    project = tmp_path / "Dự án Thanh toán Alpha"
    company.mkdir()
    project.mkdir()
    portable_runtime.init_company(company, "cong-ty-du-lieu", "Công ty Dữ liệu")
    portable_runtime.register_company(company)
    portable_runtime.init_project(project, "cong-ty-du-lieu")

    portable_runtime.capture(
        project,
        kind="project-knowledge",
        title="Quy trình thanh toán",
        text="Nhóm sử dụng quy trình thanh toán vào thứ Sáu.",
        memory_key="du-an:quy-trinh-thanh-toan",
        event_id="evt_unicode_windows_path",
    )
    recalled = portable_runtime.recall(
        project,
        "quy trinh thanh toan thu sau",
        include_skills=False,
        include_company=False,
    )
    memory = portable_runtime.section_text(recalled, "memory")
    assert "quy trình thanh toán" in memory
    assert "thứ sáu" in memory
    status = portable_runtime.status(project)
    serialized = json.dumps(status, ensure_ascii=False)
    assert "Dự án Thanh toán Alpha" in serialized
    assert "�" not in serialized


def test_profiles_enforce_memory_and_company_boundaries(
    tmp_path: Path,
    isolated_localappdata: Path,
    portable_runtime: Any,
) -> None:
    company = tmp_path / "Profile Company"
    memory_project = tmp_path / "Memory Only Project"
    company_project = tmp_path / "Company Only Project"
    company.mkdir()
    memory_project.mkdir()
    company_project.mkdir()
    portable_runtime.init_company(company, "profile-company", "Profile Company")
    portable_runtime.register_company(company)
    portable_runtime.init_project(memory_project, "profile-company", profile="memory-only")
    portable_runtime.init_project(company_project, "profile-company", profile="company-only")

    portable_runtime.capture(
        memory_project,
        kind="preference",
        title="Memory profile marker",
        text="Memory-only-project-marker-7719",
        memory_key="profile:memory-only",
        event_id="evt_memory_only_profile",
    )
    memory_recall = portable_runtime.recall(memory_project, "memory profile marker")
    assert "memory-only-project-marker-7719" in portable_runtime.section_text(
        memory_recall, "memory"
    )
    assert memory_recall["company"]["available"] is False
    assert memory_recall["company"]["results"] == []

    with pytest.raises(Exception, match=r"(?i)(memory|profile|disabled)"):
        portable_runtime.capture(
            company_project,
            kind="preference",
            title="Forbidden company-only memory",
            text="This must not be stored.",
            memory_key="profile:company-only",
            event_id="evt_company_only_forbidden",
        )
    assert not (company_project / ".memorizer").exists()


def test_sensitive_memory_is_hidden_by_default_and_requires_explicit_opt_in(
    portable_world: Mapping[str, Path | str], portable_runtime: Any
) -> None:
    project = Path(portable_world["project_a"])
    fake_token = "sk-" + ("A" * 22)
    marker = "sensitive-launch-window-marker-7719"
    captured = portable_runtime.capture(
        project,
        kind="project-knowledge",
        title="Sensitive launch window",
        text=f"{marker} starts at midnight; api_key={fake_token}",
        memory_key="security:sensitive-launch-window",
        event_id="evt_sensitive_memory_contract",
    )
    assert fake_token not in json.dumps(captured, ensure_ascii=False)

    default_recall = portable_runtime.recall(
        project,
        "sensitive launch window",
        include_skills=False,
        include_company=False,
    )
    assert marker not in portable_runtime.section_text(default_recall, "memory")

    explicit_recall = portable_runtime.recall(
        project,
        "sensitive launch window",
        include_skills=False,
        include_company=False,
        include_sensitive_memory=True,
    )
    sensitive_section = portable_runtime.section_text(explicit_recall, "memory")
    assert marker in sensitive_section
    assert '"privacy": "sensitive"' in sensitive_section
    assert fake_token.casefold() not in sensitive_section


def test_memory_capture_retries_one_transient_windows_atomic_replace_failure(
    portable_world: Mapping[str, Path | str],
    portable_runtime: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from local_knowledge.memorizer import core as memory_core

    project = Path(portable_world["project_a"])
    original_replace = memory_core.os.replace
    failures = 0

    def replace_with_one_sharing_violation(source: Any, destination: Any) -> None:
        nonlocal failures
        if failures == 0 and ".memorizer" in Path(destination).parts:
            failures += 1
            raise PermissionError(
                13,
                "simulated transient Windows sharing violation",
                str(destination),
                5,
            )
        original_replace(source, destination)

    monkeypatch.setattr(memory_core.os, "replace", replace_with_one_sharing_violation)
    captured = portable_runtime.capture(
        project,
        kind="decision",
        title="Atomic retry contract",
        text="Windows atomic writes retry a transient sharing violation.",
        memory_key="windows:atomic-retry",
        event_id="evt_windows_atomic_retry",
    )
    assert failures == 1
    assert captured.get("ok", captured.get("accepted", False)) is True


def test_company_id_path_traversal_is_rejected_before_writes(
    tmp_path: Path,
    isolated_localappdata: Path,
    portable_runtime: Any,
) -> None:
    project = tmp_path / "Traversal Target"
    project.mkdir()
    escaped = tmp_path / "escaped-company"

    with pytest.raises(Exception, match=r"(?i)(company|identifier|travers|invalid|unsafe)"):
        portable_runtime.init_project(project, r"..\..\escaped-company")

    assert not escaped.exists()
    assert not (project / ".local-knowledge" / "project.toml").exists()


@pytest.mark.parametrize(
    "variable",
    ["CKB_ROOT", "CKB_DATA_DIR", "CKB_DATABASE", "CKB_BUNDLE_DIR"],
)
def test_legacy_process_wide_ckb_path_overrides_are_rejected(
    variable: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    portable_world: Mapping[str, Path | str],
    portable_runtime: Any,
) -> None:
    project = Path(portable_world["project_a"])
    outside = tmp_path / "Wrong Company" / f"{variable.casefold()}.sqlite3"
    outside.parent.mkdir()
    monkeypatch.setenv(variable, str(outside))

    with pytest.raises(Exception, match=r"(?i)(CKB_|environment|override|unsafe|not supported)"):
        portable_runtime.status(project)
    assert not outside.exists()


def test_company_clone_with_manifest_and_knowledge_rebuilds_local_database(
    tmp_path: Path,
    isolated_localappdata: Path,
    portable_runtime: Any,
) -> None:
    from local_knowledge.ckb.models import CitationLocator, ClaimDraft
    from local_knowledge.ckb.okf import render_concept

    source = tmp_path / "Source Company Repository"
    clone = tmp_path / "Cloned Company Repository"
    original_project = tmp_path / "Original Project"
    project = tmp_path / "Project Using Clone"
    source.mkdir()
    original_project.mkdir()
    project.mkdir()
    portable_runtime.init_company(source, "clone-contract", "Clone Contract")
    portable_runtime.init_project(original_project, "clone-contract")

    concept = source / "knowledge" / "policies" / "portable-clone.md"
    concept.parent.mkdir(parents=True, exist_ok=True)
    concept.write_text(
        render_concept(
            concept_type="Policy",
            title="Cloned portable policy",
            description="Policy reconstructed from committed Markdown.",
            tags=["portable", "clone"],
            resource="https://example.test/company/policies/portable-clone",
            claims=[
                ClaimDraft(
                    "Cloned projects rebuild local indexes from knowledge Markdown.",
                    0.99,
                    [
                        CitationLocator(
                            "https://example.test/company/policies/portable-clone",
                            "lines 1-2",
                            "Cloned projects rebuild local indexes from knowledge Markdown.",
                            "a" * 64,
                        )
                    ],
                )
            ],
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "--", "knowledge/policies/portable-clone.md"], cwd=source, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Portable Clone Test",
            "-c",
            "user.email=portable-clone@localhost",
            "commit",
            "-m",
            "docs: add portable clone policy",
            "--",
            "knowledge/policies/portable-clone.md",
        ],
        cwd=source,
        check=True,
    )
    subprocess.run(["git", "clone", "--local", str(source), str(clone)], check=True)
    shutil.copytree(
        original_project / ".local-knowledge",
        project / ".local-knowledge",
    )
    assert not (clone / ".ckb").exists()
    assert not (project / ".memorizer").exists()

    # A clone is registered on a different Windows machine/profile, where the
    # machine-local registry starts empty even though the repository identity
    # is unchanged.
    registry_path = isolated_localappdata / "LocalKnowledgeSuite" / "registry.json"
    registry_path.unlink()
    portable_runtime.register_company(clone)
    restored = portable_runtime.restore(project)
    assert _company_database(clone).is_file()
    assert restored["created"] is False
    assert (project / ".memorizer").is_dir()
    recalled = portable_runtime.recall(
        project,
        "cloned portable policy",
        include_skills=False,
        include_memory=False,
    )
    company_result = recalled["company"]
    assert company_result["evidence_sufficient"] is False
    assert company_result["insufficient_evidence"] is True
    assert company_result["results"] == []
    assert company_result["attested_results"]
    concept = company_result["attested_results"][0]
    assert concept["evidence_sufficient"] is False
    assert concept["authority"] == "unverified_canonical_claim"
    assert concept["status"] == "review"
    assert concept["requires_source_reingestion"] is True
    with sqlite3.connect(_company_database(clone)) as connection:
        connection.row_factory = sqlite3.Row
        claim = connection.execute(
            "SELECT verified,source_uri,locator,excerpt FROM claims"
        ).fetchone()
    assert claim is not None and claim[0] == 0
    assert claim["source_uri"] == "https://example.test/company/policies/portable-clone"
    assert claim["locator"] == "lines 1-2"
    assert claim["excerpt"] == "Cloned projects rebuild local indexes from knowledge Markdown."
    assert not (project / "src" / "ckb").exists()
