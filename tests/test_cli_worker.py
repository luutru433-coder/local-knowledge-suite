# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

from local_knowledge.ckb.cli import main
from local_knowledge.ckb.config import Settings
from local_knowledge.ckb.okf import concept_evidence_sha256
from local_knowledge.ckb.pipeline import KnowledgeService
from local_knowledge.ckb.worker import run_worker
from local_knowledge.services import initialize_company_repository


def test_cli_initialization_validation_and_empty_worker(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    company = tmp_path / "company"
    monkeypatch.setattr(
        "local_knowledge.ckb.cli._password",
        lambda: "operator-password-123",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    initialize_company_repository(
        company,
        "CLI Initialization Company",
        "cli-initialization-company",
    )
    assert main(["--root", str(company), "init", "--admin", "operator"]) == 0
    assert (company / ".ckb" / "ckb.sqlite3").exists()
    assert (company / "knowledge" / "index.md").exists()
    assert main(["--root", str(company), "validate"]) == 0
    assert main(["--root", str(company), "sync"]) == 0
    output = capsys.readouterr().out
    assert "Initialized" in output


def test_worker_once_processes_no_jobs(settings, fake_lm) -> None:
    service = KnowledgeService(settings, lm_client=fake_lm)
    assert run_worker(service, once=True) == 0


def test_cli_reset_backs_up_state_and_reindexes_legacy_bundle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    company = tmp_path / "company"
    monkeypatch.setattr(
        "local_knowledge.ckb.cli._password",
        lambda: "operator-password-123",
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    initialize_company_repository(
        company,
        "CLI Reset Company",
        "cli-reset-company",
    )
    assert main(["--root", str(company), "init", "--admin", "operator"]) == 0
    legacy = company / "knowledge" / "reference" / "legacy-policy.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    body = "# Legacy Policy\n"
    legacy.write_text(
        "---\n"
        "type: Reference\n"
        "title: Legacy Policy\n"
        "description: Preserved knowledge\n"
        "tags: [legacy]\n"
        "claims: []\n"
        f"evidence_sha256: {concept_evidence_sha256(body, [])}\n"
        "---\n\n"
        f"{body}",
        encoding="utf-8",
    )
    assert main(["--root", str(company), "init", "--reset-state", "--admin", "operator"]) == 0
    backups = list((company / ".ckb" / "backups").glob("ckb-v1-*.sqlite3"))
    assert len(backups) == 1
    service = KnowledgeService(Settings.load(company))
    with service.db.connect() as connection:
        row = connection.execute("SELECT status,legacy,maturity FROM concepts WHERE id='legacy-policy'").fetchone()
    assert dict(row) == {"status": "review", "legacy": 1, "maturity": 0.6}
