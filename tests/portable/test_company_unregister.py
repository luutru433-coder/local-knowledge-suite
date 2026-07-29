# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from local_knowledge import WORKSPACE_SCHEMA_VERSION
from local_knowledge.cli import main
from local_knowledge.errors import RegistryError
from local_knowledge.manifests import (
    CompanyManifest,
    replace_company_manifest,
    write_company_manifest,
)
from local_knowledge.registry import CompanyRegistry
from local_knowledge.services import (
    bootstrap_workspace,
    initialize_company_repository,
    knowledge_status,
)


class FakeKeyring:
    def __init__(self, values: dict[tuple[str, str], str] | None = None) -> None:
        self.values = dict(values or {})
        self.get_calls: list[tuple[str, str]] = []
        self.delete_calls: list[tuple[str, str]] = []

    def get_password(self, service: str, username: str) -> str | None:
        self.get_calls.append((service, username))
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.delete_calls.append((service, username))
        del self.values[(service, username)]


def _company(root: Path, company_id: str) -> dict[str, Path]:
    root.mkdir(parents=True)
    write_company_manifest(
        root,
        CompanyManifest(
            WORKSPACE_SCHEMA_VERSION,
            company_id,
            company_id.replace("-", " ").title(),
        ),
    )
    paths = {
        "git": root / ".git" / "sentinel",
        "database": root / ".ckb" / "sentinel",
        "sources": root / ".local-sources" / "sentinel",
        "knowledge": root / "knowledge" / "sentinel.md",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(path.name, encoding="utf-8")
    return paths


def test_unregister_removes_only_verified_mapping_and_exact_master_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company_a = tmp_path / "Company A"
    company_b = tmp_path / "Company B"
    preserved = _company(company_a, "company-a")
    _company(company_b, "company-b")
    registry = CompanyRegistry()
    registry.register(company_a)
    registry.register(company_b)

    service_a = "local-knowledge-suite/company-a"
    service_b = "local-knowledge-suite/company-b"
    fake_keyring = FakeKeyring(
        {
            (service_a, "master-key"): "encoded-a",
            (service_a, "unrelated-user"): "keep-a",
            (service_b, "master-key"): "keep-b",
        }
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    code = main(
        [
            "company",
            "unregister",
            "--root",
            str(company_a.resolve()),
            "--purge-credential-key",
            "--confirm-company",
            "company-a",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["company_id"] == "company-a"
    assert payload["unregistered"] is True
    assert payload["credential_key"] == {
        "requested": True,
        "service": service_a,
        "username": "master-key",
        "deleted": True,
        "missing": False,
    }
    assert "encoded-a" not in json.dumps(payload)
    assert set(registry.list()) == {"company-b"}
    assert fake_keyring.get_calls == [(service_a, "master-key")]
    assert fake_keyring.delete_calls == [(service_a, "master-key")]
    assert fake_keyring.values == {
        (service_a, "unrelated-user"): "keep-a",
        (service_b, "master-key"): "keep-b",
    }
    assert company_a.is_dir()
    assert (company_a / ".local-knowledge" / "company.toml").is_file()
    assert all(path.is_file() for path in preserved.values())


def test_unregister_revokes_projects_before_company_id_can_be_reused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    original_company = tmp_path / "Original Company"
    replacement_company = tmp_path / "Replacement Company"
    project = tmp_path / "Project"
    initialize_company_repository(
        original_company,
        "Reused Company",
        "reused-company",
    )
    project.mkdir()
    registry = CompanyRegistry()
    bootstrap = bootstrap_workspace(
        str(project.resolve()),
        "reused-company",
        "combined",
        registry=registry,
    )

    removed = registry.unregister(original_company)

    assert removed["revoked_projects"] == [bootstrap["project_id"]]
    assert registry.list_projects() == {}
    shutil.copytree(original_company, replacement_company)
    registry.register(replacement_company)
    with pytest.raises(RegistryError, match="not locally authorized"):
        knowledge_status(str(project.resolve()))


def test_unregister_blocks_registered_root_mismatch_before_any_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    requested = tmp_path / "Requested"
    registered = tmp_path / "Registered"
    preserved = _company(requested, "same-company")
    _company(registered, "same-company")
    registry = CompanyRegistry()
    registry.register(registered)
    fake_keyring = FakeKeyring(
        {("local-knowledge-suite/same-company", "master-key"): "keep"}
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    code = main(
        [
            "company",
            "unregister",
            "--root",
            str(requested.resolve()),
            "--purge-credential-key",
            "--confirm-company",
            "same-company",
        ]
    )

    assert code == 2
    error = json.loads(capsys.readouterr().err)
    assert "root mismatch" in error["error"]
    assert registry.resolve("same-company") == registered.resolve()
    assert fake_keyring.get_calls == []
    assert fake_keyring.delete_calls == []
    assert all(path.is_file() for path in preserved.values())


def test_unregister_blocks_manifest_identity_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "Changed Identity"
    _company(company, "old-company")
    registry = CompanyRegistry()
    registry.register(company)
    replace_company_manifest(
        company,
        CompanyManifest(
            WORKSPACE_SCHEMA_VERSION,
            "new-company",
            "New Company",
        ),
    )
    fake_keyring = FakeKeyring(
        {("local-knowledge-suite/new-company", "master-key"): "keep"}
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    code = main(
        [
            "company",
            "unregister",
            "--root",
            str(company.resolve()),
            "--purge-credential-key",
            "--confirm-company",
            "new-company",
        ]
    )

    assert code == 2
    error = json.loads(capsys.readouterr().err)
    assert "identity mismatch" in error["error"]
    assert set(registry.list()) == {"old-company"}
    assert fake_keyring.get_calls == []
    assert fake_keyring.delete_calls == []


def test_credential_purge_requires_exact_confirmation_before_unregister(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    company = tmp_path / "Confirmed Company"
    _company(company, "confirmed-company")
    registry = CompanyRegistry()
    registry.register(company)
    fake_keyring = FakeKeyring(
        {("local-knowledge-suite/confirmed-company", "master-key"): "keep"}
    )
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    attempts = (
        [
            "company",
            "unregister",
            "--root",
            str(company.resolve()),
            "--purge-credential-key",
        ],
        [
            "company",
            "unregister",
            "--root",
            str(company.resolve()),
            "--purge-credential-key",
            "--confirm-company",
            "Confirmed-Company",
        ],
        [
            "company",
            "unregister",
            "--root",
            str(company.resolve()),
            "--confirm-company",
            "confirmed-company",
        ],
    )
    for arguments in attempts:
        assert main(arguments) == 2
        assert json.loads(capsys.readouterr().err)["ok"] is False
        assert registry.resolve("confirmed-company") == company.resolve()

    assert fake_keyring.get_calls == []
    assert fake_keyring.delete_calls == []


def test_unregister_and_missing_credential_key_are_idempotent_no_ops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    local_app_data = tmp_path / "Local App Data"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    company = tmp_path / "Unregistered Company"
    preserved = _company(company, "unregistered-company")
    fake_keyring = FakeKeyring()
    monkeypatch.setitem(sys.modules, "keyring", fake_keyring)

    assert (
        main(
            [
                "company",
                "unregister",
                "--root",
                str(company.resolve()),
            ]
        )
        == 0
    )
    first = json.loads(capsys.readouterr().out)
    assert first["unregistered"] is False
    assert first["credential_key"]["requested"] is False
    assert not (local_app_data / "LocalKnowledgeSuite" / "registry.json").exists()

    assert (
        main(
            [
                "company",
                "unregister",
                "--root",
                str(company.resolve()),
                "--purge-credential-key",
                "--confirm-company",
                "unregistered-company",
            ]
        )
        == 0
    )
    second = json.loads(capsys.readouterr().out)
    assert second["unregistered"] is False
    assert second["credential_key"]["deleted"] is False
    assert second["credential_key"]["missing"] is True
    assert fake_keyring.delete_calls == []
    assert company.is_dir()
    assert all(path.is_file() for path in preserved.values())
