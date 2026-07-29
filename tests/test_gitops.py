# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

import local_knowledge.ckb.gitops as gitops
from local_knowledge.manifests import CompanyManifest
from local_knowledge.ckb.okf import render_concept


def _example_markdown() -> str:
    return render_concept(
        concept_type="Reference",
        title="Example",
        description="Publication lock fixture",
        tags=[],
        resource="manual:test-fixture",
        claims=[],
        body_override="Example fixture body.",
    )


@pytest.mark.parametrize(
    "tracked_path",
    [
        ".ckb/attacker-state.sqlite3",
        ".CKB/attacker-state.sqlite3",
        ".local-sources/private.txt",
        ".MEMORIZER/injected.md",
        "web/DIST/index.html",
        ".local-knowledge/BACKUPS/state.json",
    ],
)
def test_company_git_rejects_case_insensitive_tracked_private_paths(
    tmp_path: Path,
    tracked_path: str,
) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    target = tmp_path / Path(tracked_path)
    target.parent.mkdir(parents=True)
    target.write_text("must remain machine-local", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", "--", tracked_path],
        cwd=tmp_path,
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
            "test: force-track private state",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    with pytest.raises(
        gitops.GitOperationError,
        match="must not track private or derived",
    ):
        gitops.reject_tracked_private_paths(
            tmp_path,
            gitops.COMPANY_PRIVATE_TRACKED_PATHS,
            label="company repository",
            require_own_repository=True,
        )


def test_nested_project_git_check_is_nul_safe_and_scope_relative(
    tmp_path: Path,
) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    project = tmp_path / "nested-project"
    target = project / ".MEMORIZER" / "injected.md"
    target.parent.mkdir(parents=True)
    target.write_text("injected authority", encoding="utf-8")
    subprocess.run(
        ["git", "add", "-f", "--", target.relative_to(tmp_path).as_posix()],
        cwd=tmp_path,
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
            "test: track nested memory",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    with pytest.raises(gitops.GitOperationError, match=r"\.MEMORIZER/injected"):
        gitops.reject_tracked_private_paths(
            project,
            gitops.PROJECT_PRIVATE_TRACKED_PATHS,
            label="project repository",
            require_own_repository=False,
        )


def test_failed_commit_restores_bundle_and_index(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    bundle = tmp_path / "knowledge"
    bundle.mkdir()
    original_run = gitops._run

    def fail_commit(repo, *args, **kwargs):
        if "commit" in args:
            raise gitops.GitOperationError("simulated commit failure")
        return original_run(repo, *args, **kwargs)

    monkeypatch.setattr(gitops, "_run", fail_commit)
    with pytest.raises(gitops.GitOperationError, match="simulated"):
        gitops.publish_markdown(
            tmp_path,
            bundle,
            "reference/example.md",
            _example_markdown(),
            "Example",
            sync=False,
        )
    assert not list(bundle.rglob("*.md"))
    status = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, text=True, capture_output=True, check=True).stdout
    assert "knowledge" not in status


def test_candidate_publication_acquires_the_bundle_lock_once(tmp_path: Path, monkeypatch) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    marker = tmp_path / ".gitignore"
    marker.write_text(".ckb/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "initial"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    bundle = tmp_path / "knowledge"
    bundle.mkdir()
    original_lock = gitops.publication_lock
    locked_bundles: list[Path] = []
    lock_held = False
    sync_lock_states: list[bool] = []

    @contextmanager
    def counted_lock(bundle_dir):
        nonlocal lock_held
        locked_bundles.append(Path(bundle_dir).resolve())
        with original_lock(bundle_dir):
            lock_held = True
            try:
                yield
            finally:
                lock_held = False

    original_sync = gitops.sync_before_publish

    def checked_sync(repo, env=None):
        sync_lock_states.append(lock_held)
        return original_sync(repo, env)

    monkeypatch.setattr(gitops, "publication_lock", counted_lock)
    monkeypatch.setattr(gitops, "sync_before_publish", checked_sync)
    commit = gitops.publish_candidate(
        tmp_path,
        bundle,
        "ckb/reviewer/test-publication",
        "reference/example.md",
        _example_markdown(),
        "Example",
        actor_name="Reviewer",
        actor_email="reviewer@localhost",
        publication_id="test-publication",
    )

    assert commit != "no changes"
    assert locked_bundles == [(tmp_path / ".ckb").resolve()]
    assert sync_lock_states == [True]


def test_remote_backed_publication_lock_does_not_dirty_worktree(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "company"
    remote.mkdir()
    repo.mkdir()
    subprocess.run(
        ["git", "init", "--bare"],
        cwd=remote,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / ".gitignore").write_text(".ckb/\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore"],
        cwd=repo,
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
            "chore: initialize company",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    commit = gitops.publish_markdown(
        repo,
        repo / "knowledge",
        "reference/remote-safe.md",
        _example_markdown(),
        "Remote safe",
    )

    assert len(commit) == 40
    assert (repo / ".ckb" / ".publish.lock").is_file()
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        == ""
    )


def test_orphan_publication_lock_file_is_recovered(tmp_path: Path) -> None:
    private = tmp_path / ".ckb"
    private.mkdir()
    lock = private / ".publish.lock"
    lock.write_text("999999\n", encoding="ascii")

    with gitops.publication_lock(private):
        pass
    assert lock.read_text(encoding="ascii").strip() == str(os.getpid())


def test_live_publication_lock_still_rejects_second_writer(tmp_path: Path) -> None:
    private = tmp_path / ".ckb"

    with gitops.publication_lock(private):
        with pytest.raises(gitops.GitOperationError, match="in progress"):
            with gitops.publication_lock(private):
                raise AssertionError("second writer acquired the publication lock")


def test_pull_rejects_incoming_private_history_without_changing_head_or_worktree(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "remote.git"
    publisher = tmp_path / "publisher"
    victim = tmp_path / "victim"
    remote.mkdir()
    publisher.mkdir()
    subprocess.run(
        ["git", "init", "--bare"],
        cwd=remote,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=publisher,
        check=True,
        capture_output=True,
    )
    (publisher / ".gitignore").write_text(
        ".ckb/\n.local-sources/\nweb/dist/\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", ".gitignore"],
        cwd=publisher,
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
            "chore: initialize safe history",
        ],
        cwd=publisher,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)],
        cwd=publisher,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=publisher,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "clone", "--branch", "main", str(remote), str(victim)],
        check=True,
        capture_output=True,
    )
    before_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=victim,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    attacker = publisher / ".CKB" / "attacker-state.sqlite3"
    attacker.parent.mkdir()
    attacker.write_bytes(b"attacker-controlled state")
    subprocess.run(
        ["git", "add", "-f", "--", ".CKB/attacker-state.sqlite3"],
        cwd=publisher,
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
            "test: inject private company state",
        ],
        cwd=publisher,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=publisher,
        check=True,
        capture_output=True,
    )

    with pytest.raises(
        gitops.GitOperationError,
        match="incoming company Git history tracks private",
    ):
        gitops.pull(victim)

    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=victim,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        == before_head
    )
    assert not (victim / ".CKB").exists()
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=victim,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        == ""
    )
    assert ".CKB/attacker-state.sqlite3" not in subprocess.run(
        ["git", "ls-files"],
        cwd=victim,
        text=True,
        capture_output=True,
        check=True,
    ).stdout


def test_incoming_company_revision_cannot_change_manifest_identity(
    tmp_path: Path,
) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    metadata = tmp_path / ".local-knowledge"
    metadata.mkdir()
    manifest = metadata / "company.toml"
    manifest.write_text(
        'schema_version = 2\ncompany_id = "company-a"\nname = "Company A"\n',
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        ".ckb/\n.local-sources/\nweb/dist/\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", ".gitignore", ".local-knowledge/company.toml"],
        cwd=tmp_path,
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
            "chore: safe company baseline",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    current = CompanyManifest.load(tmp_path)
    manifest.write_text(
        'schema_version = 2\ncompany_id = "company-b"\nname = "Company B"\n',
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", ".local-knowledge/company.toml"],
        cwd=tmp_path,
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
            "test: change company identity",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    with pytest.raises(gitops.GitOperationError, match="manifest"):
        gitops._validate_incoming_company_revision(tmp_path, revision, current)


@pytest.mark.parametrize(
    ("negation", "expected"),
    [
        pytest.param("!.ckb/\n", ".ckb/", id="company-database"),
        pytest.param(
            "!.local-sources/\n",
            ".local-sources/",
            id="local-sources",
        ),
        pytest.param("!web/dist/\n", "web/dist/", id="portal-dist"),
        pytest.param(
            "!.ckb/\n.ckb/*\n!.ckb/private.sqlite3\n",
            ".ckb/",
            id="child-negation",
        ),
    ],
)
def test_incoming_company_revision_rejects_effective_ignore_negation(
    tmp_path: Path,
    negation: str,
    expected: str,
) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    metadata = tmp_path / ".local-knowledge"
    metadata.mkdir()
    (metadata / "company.toml").write_text(
        'schema_version = 2\ncompany_id = "company-a"\nname = "Company A"\n',
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        ".ckb/\n.local-sources/\nweb/dist/\n" + negation,
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", ".gitignore", ".local-knowledge/company.toml"],
        cwd=tmp_path,
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
            "test: negate required private ignore",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    with pytest.raises(
        gitops.GitOperationError,
        match="does not effectively ignore",
    ) as captured:
        gitops._validate_incoming_company_revision(
            tmp_path,
            revision,
            CompanyManifest.load(tmp_path),
        )

    assert expected in str(captured.value)


def test_pull_rejects_ignore_negation_before_target_worktree_changes(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "remote.git"
    publisher = tmp_path / "publisher"
    victim = tmp_path / "victim"
    remote.mkdir()
    publisher.mkdir()

    def run_git(cwd: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=True,
        )

    run_git(remote, "init", "--bare")
    run_git(publisher, "init", "-b", "main")
    metadata = publisher / ".local-knowledge"
    metadata.mkdir()
    (metadata / "company.toml").write_text(
        'schema_version = 2\ncompany_id = "company-a"\nname = "Company A"\n',
        encoding="utf-8",
    )
    ignore = publisher / ".gitignore"
    ignore.write_text(
        ".ckb/\n.local-sources/\nweb/dist/\n",
        encoding="utf-8",
    )
    run_git(publisher, "add", ".gitignore", ".local-knowledge/company.toml")
    run_git(
        publisher,
        "-c",
        "user.name=Security Test",
        "-c",
        "user.email=security-test@localhost",
        "commit",
        "-m",
        "chore: initialize safe company",
    )
    run_git(publisher, "remote", "add", "origin", str(remote))
    run_git(publisher, "push", "-u", "origin", "main")
    subprocess.run(
        ["git", "clone", "--branch", "main", str(remote), str(victim)],
        text=True,
        capture_output=True,
        check=True,
    )
    before_head = run_git(victim, "rev-parse", "HEAD").stdout.strip()
    before_ignore = (victim / ".gitignore").read_bytes()

    ignore.write_text(
        ".ckb/\n.local-sources/\nweb/dist/\n"
        "!.ckb/\n.ckb/*\n!.ckb/private.sqlite3\n",
        encoding="utf-8",
    )
    run_git(publisher, "add", ".gitignore")
    run_git(
        publisher,
        "-c",
        "user.name=Security Test",
        "-c",
        "user.email=security-test@localhost",
        "commit",
        "-m",
        "test: negate private ignore",
    )
    run_git(publisher, "push", "origin", "main")

    with pytest.raises(
        gitops.GitOperationError,
        match="does not effectively ignore",
    ):
        gitops.pull(victim)

    assert run_git(victim, "rev-parse", "HEAD").stdout.strip() == before_head
    assert (victim / ".gitignore").read_bytes() == before_ignore
    assert run_git(victim, "status", "--porcelain").stdout == ""


def test_pull_does_not_initialize_non_repository(tmp_path: Path) -> None:
    with pytest.raises(gitops.GitOperationError, match="existing Git repository"):
        gitops.pull(tmp_path)
    assert not (tmp_path / ".git").exists()


def test_sync_rejects_dirty_repository_even_without_remote(tmp_path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    tracked = tmp_path / "knowledge.md"
    tracked.write_text("clean", encoding="utf-8")
    subprocess.run(
        ["git", "add", "knowledge.md"],
        cwd=tmp_path,
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
            "docs: baseline",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    tracked.write_text("unrelated local edit", encoding="utf-8")

    with pytest.raises(gitops.GitOperationError, match="uncommitted changes"):
        gitops.sync_before_publish(tmp_path)

    assert tracked.read_text(encoding="utf-8") == "unrelated local edit"


@pytest.mark.skipif(os.name != "nt", reason="Windows askpass hardening")
def test_windows_askpass_does_not_expand_cmd_metacharacters(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "askpass-owned.txt"
    username = "reviewer&echo USER_OWNED>askpass-owned.txt|rem)%PATH%"
    token = "token&echo TOKEN_OWNED>askpass-owned.txt|rem)%PATH%"
    retained_environment: dict[str, str] | None = None

    with gitops.git_credential_environment(
        {"username": username, "token": token}
    ) as environment:
        assert environment is not None
        retained_environment = environment
        helper = Path(environment["GIT_ASKPASS"])
        helper_text = helper.read_text(encoding="utf-8")
        assert username not in helper_text
        assert token not in helper_text
        assert "%CKB_GIT_USERNAME%" not in helper_text
        assert "%CKB_GIT_TOKEN%" not in helper_text
        assert environment[
            f"GIT_CONFIG_VALUE_{int(environment['GIT_CONFIG_COUNT']) - 1}"
        ] == username

        result = subprocess.run(
            [str(helper), "Password for https://example.invalid:"],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            check=True,
        )
        assert result.stdout.decode("ascii") == token
        assert not marker.exists()

    assert retained_environment is not None
    assert "CKB_GIT_USERNAME" not in retained_environment
    assert "CKB_GIT_TOKEN" not in retained_environment
    assert not marker.exists()


@pytest.mark.parametrize(
    "credentials",
    [
        {"username": "reviewer\r\nmalicious", "token": "safe-token"},
        {"username": "reviewer", "token": "token\r\nmalicious"},
        {"username": "reviewer\x00malicious", "token": "safe-token"},
        {"username": "reviewer", "token": "token\x00malicious"},
    ],
)
def test_git_credentials_reject_control_characters_without_echoing(
    credentials: dict[str, str],
) -> None:
    with pytest.raises(
        gitops.GitOperationError,
        match="cannot contain control characters",
    ) as captured:
        with gitops.git_credential_environment(credentials):
            raise AssertionError("unsafe credential context must not open")
    assert credentials["username"] not in str(captured.value)
    assert credentials["token"] not in str(captured.value)


def test_git_status_redacts_remote_userinfo_and_token_shapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    github_token = "ghp_" + ("A" * 36)
    gitlab_token = "glpat" + "-abcdefghijklmnop"
    remote_output = (
        f"origin\thttps://reviewer:{github_token}@example.test/org/repo.git (fetch)\n"
        f"origin\thttps://oauth2:{gitlab_token}@example.test/org/repo.git (push)\n"
        "backup\thttps://example.test/org/repo.git?access_token=plain-secret (fetch)\n"
    )
    outputs = {
        ("branch", "--show-current"): "main\n",
        ("rev-parse", "HEAD"): "a" * 40 + "\n",
        ("status", "--porcelain"): "",
        ("remote", "-v"): remote_output,
    }

    def fake_run(
        repo: Path,
        *args: str,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            [str(repo), *args],
            0,
            stdout=outputs[args],
            stderr="",
        )

    monkeypatch.setattr(gitops, "require_owned_repository", lambda repo: tmp_path)
    monkeypatch.setattr(gitops, "_run", fake_run)

    result = gitops.status(tmp_path)

    serialized = "\n".join(result.values())
    for secret in ("reviewer", "oauth2", github_token, gitlab_token, "plain-secret"):
        assert secret not in serialized
    assert serialized.count("[REDACTED]") == 3
    assert "https://[REDACTED]@example.test/org/repo.git" in result["remotes"]
    assert "access_token=[REDACTED]" in result["remotes"]


def test_git_failure_redacts_credentials_before_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    username = "release-reviewer"
    token = "plain-environment-secret"
    prefixed_token = "github_" + "pat_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    environment = {
        "PATH": str(tmp_path),
        "CKB_GIT_USERNAME": username,
        "CKB_GIT_TOKEN": token,
    }
    failure = (
        f"fatal: could not access https://{username}:{token}@example.test/repo.git\n"
        f"Authorization: Bearer {prefixed_token}\n"
    )

    monkeypatch.setattr(
        gitops,
        "resolve_trusted_executable",
        lambda *args, **kwargs: tmp_path / "git.exe",
    )
    monkeypatch.setattr(
        gitops.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            128,
            stdout="",
            stderr=failure,
        ),
    )

    with pytest.raises(gitops.GitOperationError) as captured:
        gitops._run(tmp_path, "fetch", env=environment)

    message = str(captured.value)
    for secret in (username, token, prefixed_token):
        assert secret not in message
    assert "[REDACTED]" in message


@pytest.mark.skipif(os.name != "nt", reason="Windows executable search hardening")
def test_git_run_ignores_project_candidates_and_uses_absolute_trusted_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = tmp_path / "company-repository"
    trusted = tmp_path / "trusted-bin"
    repository.mkdir()
    trusted.mkdir()
    (repository / "git.exe").write_bytes(b"project-controlled")
    trusted_git = trusted / "git.exe"
    trusted_git.write_bytes(b"trusted-test-double")
    monkeypatch.chdir(repository)
    environment = os.environ.copy()
    environment["PATH"] = (
        f".{os.pathsep}{repository}{os.pathsep}{trusted}"
    )
    calls: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(gitops.subprocess, "run", fake_run)
    gitops._run(repository, "status", env=environment)
    assert calls == [[str(trusted_git.resolve()), "status"]]
