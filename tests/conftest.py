# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from local_knowledge import WORKSPACE_SCHEMA_VERSION
from local_knowledge.ckb.config import Settings
from local_knowledge.manifests import CompanyManifest, write_company_manifest


class FakeLMStudio:
    chat_model = "test-chat"
    embedding_model = "test-embedding"

    def health(self):
        return {"reachable": True, "models": [self.chat_model, self.embedding_model], "chat_model_available": True, "embedding_model_available": True}

    def extract_claims(self, title, language, sections):
        claims = []
        for section_index, section in enumerate(sections):
            excerpt = next((line.strip() for line in section.text.splitlines() if len(line.strip()) >= 12), section.text[:80].strip())
            if excerpt:
                claims.append({"text": excerpt, "confidence": 0.96, "section_index": section_index, "excerpt": excerpt, "entities": [title]})
        return claims[:20]

    def embed(self, texts):
        vectors = []
        for text in texts:
            lowered = text.lower()
            vectors.append([
                float(lowered.count("revenue") + lowered.count("doanh thu")),
                float(lowered.count("policy") + lowered.count("chính sách")),
                float(len(lowered) % 17 + 1),
            ])
        return vectors


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    (tmp_path / ".local-sources").mkdir()
    write_company_manifest(
        tmp_path,
        CompanyManifest(
            WORKSPACE_SCHEMA_VERSION,
            "test-company",
            "Test Company",
        ),
    )
    return Settings(
        root=tmp_path,
        data_dir=tmp_path / ".ckb",
        database=tmp_path / ".ckb" / "test.sqlite3",
        bundle_dir=tmp_path / "knowledge",
        keyring_service="local-knowledge-suite/test-company",
        crawler_delay_seconds=0,
    )


@pytest.fixture
def fake_lm() -> FakeLMStudio:
    return FakeLMStudio()


@pytest.fixture
def git_repo(settings: Settings) -> Path:
    subprocess.run(["git", "init"], cwd=settings.root, check=True, capture_output=True)
    return settings.root


@pytest.fixture
def publishable_git_repo(settings: Settings, git_repo: Path) -> Path:
    """Create the clean company baseline required by guarded publication."""

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
            "user.name=Pipeline Test",
            "-c",
            "user.email=pipeline-test@localhost",
            "commit",
            "-m",
            "chore: initialize company test repository",
        ],
        cwd=settings.root,
        check=True,
        capture_output=True,
    )
    return git_repo
