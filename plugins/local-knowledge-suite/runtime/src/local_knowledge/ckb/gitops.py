# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import base64
import ctypes
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .. import WORKSPACE_SCHEMA_VERSION
from ..manifests import CompanyManifest
from ..winio import reject_reparse_points
from .executables import resolve_trusted_executable
from .okf import append_log, atomic_write, regenerate_indexes, validate_bundle


class GitOperationError(RuntimeError):
    pass


_URL_AUTHORITY = re.compile(
    r"(?i)\b(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<authority>[^/\s?#]+)"
)
_QUERY_SECRET = re.compile(
    r"(?i)(?P<prefix>[?&](?:access[_-]?token|auth|key|password|passwd|secret|token)=)"
    r"[^&#\s]*"
)
_AUTHORIZATION_SECRET = re.compile(
    r"(?im)(?P<prefix>\b(?:proxy-)?authorization\s*:\s*(?:basic|bearer)\s+)\S+"
)
_KNOWN_TOKEN = re.compile(
    r"(?i)\b(?:"
    r"github_pat_[a-z0-9_]{16,}|"
    r"gh[pousr]_[a-z0-9_]{16,}|"
    r"glpat-[a-z0-9_-]{10,}|"
    r"xox[baprs]-[a-z0-9-]{10,}"
    r")\b"
)
_REDACTED = "[REDACTED]"
COMPANY_PRIVATE_TRACKED_PATHS = (
    ".ckb",
    ".local-sources",
    ".memorizer",
    "web/dist",
    ".local-knowledge/project.toml",
    ".local-knowledge/vendor-lock.json",
    ".local-knowledge/backups",
    ".local-knowledge/memory-snapshot",
)
PROJECT_PRIVATE_TRACKED_PATHS = (
    ".memorizer",
    ".local-knowledge/backups",
    ".local-knowledge/memory-snapshot",
)
REQUIRED_COMPANY_IGNORE_ENTRIES = (
    ".ckb/",
    ".local-sources/",
    "web/dist/",
)


def _sanitize_git_output(
    value: str,
    environment: dict[str, str] | None = None,
) -> str:
    """Remove credentials from Git output before it crosses an API/log boundary."""

    sanitized = value
    if environment is not None:
        for name in ("CKB_GIT_USERNAME", "CKB_GIT_TOKEN"):
            secret = environment.get(name, "")
            if secret:
                sanitized = sanitized.replace(secret, _REDACTED)

    def redact_authority(match: re.Match[str]) -> str:
        authority = match.group("authority")
        if "@" not in authority:
            return match.group(0)
        host = authority.rsplit("@", 1)[1]
        return f"{match.group('scheme')}{_REDACTED}@{host}"

    sanitized = _URL_AUTHORITY.sub(redact_authority, sanitized)
    sanitized = _QUERY_SECRET.sub(
        lambda match: f"{match.group('prefix')}{_REDACTED}",
        sanitized,
    )
    sanitized = _AUTHORIZATION_SECRET.sub(
        lambda match: f"{match.group('prefix')}{_REDACTED}",
        sanitized,
    )
    return _KNOWN_TOKEN.sub(_REDACTED, sanitized)


def _run(
    repo: Path,
    *args: str,
    check: bool = True,
    env: dict[str, str] | None = None,
    executable: str | Path | None = None,
) -> subprocess.CompletedProcess[str]:
    active_environment = env or os.environ
    git_executable = resolve_trusted_executable(
        "git",
        explicit=executable,
        path_value=active_environment.get("PATH", ""),
        untrusted_roots=(repo, Path.cwd()),
    )
    result = subprocess.run(
        [str(git_executable), *args],
        cwd=repo,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        env=env,
    )
    if check and result.returncode:
        detail = _sanitize_git_output(
            (result.stderr or result.stdout).strip(),
            active_environment,
        )
        raise GitOperationError(detail or "Git command failed")
    return result


def reject_tracked_private_paths(
    repo: str | Path,
    forbidden_paths: tuple[str, ...],
    *,
    label: str,
    require_own_repository: bool,
) -> None:
    """Reject machine-local paths already committed to a Git repository.

    Git output is NUL-delimited so unusual tracked filenames cannot hide a
    second path. Matching is case-insensitive because the runtime is
    intentionally Windows-only.
    """

    root = Path(repo).resolve()
    top_level_result = _run(
        root,
        "rev-parse",
        "--show-toplevel",
        check=False,
    )
    if top_level_result.returncode:
        if require_own_repository:
            raise GitOperationError(f"{label} is not a Git repository: {root}")
        return
    top_level = Path(top_level_result.stdout.strip()).resolve()
    if require_own_repository and top_level != root:
        raise GitOperationError(f"{label} root is not its own Git repository: {root}")

    prefix = _run(root, "rev-parse", "--show-prefix").stdout.replace("\\", "/").strip()
    if prefix:
        prefix = prefix.rstrip("/") + "/"
    tracked_output = _run(
        root,
        "ls-files",
        "-z",
        "--full-name",
        "--",
        ".",
    ).stdout
    forbidden = tuple(
        item.replace("\\", "/").strip("/").casefold()
        for item in forbidden_paths
    )
    findings: list[str] = []
    prefix_folded = prefix.casefold()
    for tracked in tracked_output.split("\0"):
        normalized = tracked.replace("\\", "/").strip("/")
        if not normalized:
            continue
        if prefix:
            if not normalized.casefold().startswith(prefix_folded):
                continue
            normalized = normalized[len(prefix):]
        folded = normalized.casefold()
        if any(folded == item or folded.startswith(item + "/") for item in forbidden):
            findings.append(normalized)
    if findings:
        raise GitOperationError(
            f"{label} must not track private or derived Local Knowledge paths: "
            + ", ".join(sorted(findings, key=str.casefold))
        )


def require_owned_repository(
    repo: str | Path,
    *,
    label: str = "company repository",
) -> Path:
    """Resolve an existing repository without implicitly creating one."""

    root = Path(repo).resolve()
    result = _run(root, "rev-parse", "--show-toplevel", check=False)
    if result.returncode or not result.stdout.strip():
        raise GitOperationError(f"{label} is not an existing Git repository: {root}")
    if Path(result.stdout.strip()).resolve() != root:
        raise GitOperationError(
            f"{label} is not an existing Git repository owned by this root: {root}"
        )
    return root


def _private_path_findings(
    paths: list[str],
    forbidden_paths: tuple[str, ...],
) -> list[str]:
    forbidden = tuple(
        item.replace("\\", "/").strip("/").casefold()
        for item in forbidden_paths
    )
    findings: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/").strip("/")
        folded = normalized.casefold()
        if any(folded == item or folded.startswith(item + "/") for item in forbidden):
            findings.append(normalized)
    return sorted(set(findings), key=str.casefold)


def _tree_paths_and_modes(root: Path, revision: str) -> tuple[list[str], list[str]]:
    output = _run(
        root,
        "ls-tree",
        "-r",
        "-z",
        revision,
    ).stdout
    paths: list[str] = []
    unsafe_entries: list[str] = []
    for entry in output.split("\0"):
        if not entry:
            continue
        metadata, separator, path = entry.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) < 3:
            raise GitOperationError("incoming Git tree contains malformed metadata")
        mode = fields[0]
        paths.append(path)
        if mode not in {"100644", "100755"}:
            unsafe_entries.append(path)
    return paths, unsafe_entries


def _show_text_file(root: Path, revision: str, relative_path: str) -> str:
    result = _run(
        root,
        "show",
        f"{revision}:{relative_path}",
        check=False,
    )
    if result.returncode:
        raise GitOperationError(
            f"incoming Git history is missing required file: {relative_path}"
        )
    return result.stdout


def _isolated_git_environment() -> dict[str, str]:
    environment = os.environ.copy()
    inherited_repository_state = {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CONFIG",
        "GIT_CONFIG_PARAMETERS",
        "GIT_DIR",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_TEMPLATE_DIR",
        "GIT_WORK_TREE",
    }
    for name in tuple(environment):
        if (
            name in inherited_repository_state
            or name == "GIT_CONFIG_COUNT"
            or name.startswith("GIT_CONFIG_KEY_")
            or name.startswith("GIT_CONFIG_VALUE_")
        ):
            environment.pop(name, None)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    return environment


def _ineffective_required_company_ignores(ignore_text: str) -> list[str]:
    """Use Git itself to verify that private directories remain excluded."""

    with tempfile.TemporaryDirectory(prefix="ckb-ignore-audit-") as temporary:
        audit_root = Path(temporary) / "worktree"
        empty_template = Path(temporary) / "template"
        audit_root.mkdir()
        empty_template.mkdir()
        (audit_root / ".gitignore").write_text(
            ignore_text,
            encoding="utf-8",
            newline="",
        )
        for entry in REQUIRED_COMPANY_IGNORE_ENTRIES:
            (audit_root / entry.rstrip("/")).mkdir(parents=True, exist_ok=True)
        environment = _isolated_git_environment()
        _run(
            audit_root,
            "init",
            "--quiet",
            f"--template={empty_template}",
            env=environment,
        )
        ineffective: list[str] = []
        for entry in REQUIRED_COMPANY_IGNORE_ENTRIES:
            result = _run(
                audit_root,
                "check-ignore",
                "--no-index",
                "--quiet",
                "--",
                entry.rstrip("/"),
                check=False,
                env=environment,
            )
            if result.returncode == 1:
                ineffective.append(entry)
            elif result.returncode:
                detail = _sanitize_git_output(
                    (result.stderr or result.stdout).strip(),
                    environment,
                )
                raise GitOperationError(
                    detail or "cannot validate company .gitignore semantics"
                )
        return ineffective


def _validate_incoming_company_revision(
    root: Path,
    revision: str,
    current_company: CompanyManifest | None,
) -> None:
    paths, unsafe_entries = _tree_paths_and_modes(root, revision)
    findings = _private_path_findings(paths, COMPANY_PRIVATE_TRACKED_PATHS)
    if findings:
        raise GitOperationError(
            "incoming company Git history tracks private or derived Local Knowledge "
            "paths: " + ", ".join(findings)
        )
    if unsafe_entries:
        raise GitOperationError(
            "incoming company Git history contains symlink, submodule, or special "
            "entries: " + ", ".join(sorted(unsafe_entries, key=str.casefold))
        )
    if current_company is None:
        return

    try:
        manifest_data = tomllib.loads(
            _show_text_file(
                root,
                revision,
                ".local-knowledge/company.toml",
            )
        )
    except tomllib.TOMLDecodeError as exc:
        raise GitOperationError("incoming company manifest is invalid TOML") from exc
    if (
        manifest_data.get("schema_version") != WORKSPACE_SCHEMA_VERSION
        or manifest_data.get("company_id") != current_company.company_id
        or not isinstance(manifest_data.get("name"), str)
        or not manifest_data["name"].strip()
    ):
        raise GitOperationError(
            "incoming company manifest is invalid, changes identity, or requires an "
            "explicit migration"
        )

    ignore_text = _show_text_file(root, revision, ".gitignore")
    ignore_entries = {
        line.strip().casefold()
        for line in ignore_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing_ignores = [
        entry
        for entry in REQUIRED_COMPANY_IGNORE_ENTRIES
        if entry.casefold() not in ignore_entries
    ]
    if missing_ignores:
        raise GitOperationError(
            "incoming company .gitignore removes required private-state entries: "
            + ", ".join(missing_ignores)
        )
    ineffective_ignores = _ineffective_required_company_ignores(ignore_text)
    if ineffective_ignores:
        raise GitOperationError(
            "incoming company .gitignore does not effectively ignore required "
            "private-state directories: " + ", ".join(ineffective_ignores)
        )


def _append_git_config(environment: dict[str, str], key: str, value: str) -> None:
    raw_count = environment.get("GIT_CONFIG_COUNT", "0")
    try:
        count = int(raw_count)
    except ValueError as exc:
        raise GitOperationError("inherited GIT_CONFIG_COUNT is invalid") from exc
    if count < 0 or count > 1024:
        raise GitOperationError("inherited GIT_CONFIG_COUNT is out of range")
    environment[f"GIT_CONFIG_KEY_{count}"] = key
    environment[f"GIT_CONFIG_VALUE_{count}"] = value
    environment["GIT_CONFIG_COUNT"] = str(count + 1)


def _write_windows_askpass(helper: Path) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buffer = ctypes.create_unicode_buffer(32768)
    length = int(kernel32.GetWindowsDirectoryW(buffer, len(buffer)))
    if length <= 0 or length >= len(buffer):
        raise GitOperationError("cannot resolve the trusted Windows directory")
    powershell = (
        Path(buffer.value)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.is_file():
        raise GitOperationError("Windows PowerShell is required for secure Git credentials")
    powershell_path = str(powershell.resolve())
    if any(character in powershell_path for character in ('"', "%", "\r", "\n")):
        raise GitOperationError("Windows PowerShell path is unsafe for the Git credential helper")
    command = (
        "[Console]::Out.Write("
        "[Environment]::GetEnvironmentVariable('CKB_GIT_TOKEN'))"
    )
    encoded_command = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    helper.write_text(
        "@echo off\r\n"
        "setlocal DisableDelayedExpansion\r\n"
        f'"{powershell_path}" -NoLogo -NoProfile -NonInteractive '
        f"-EncodedCommand {encoded_command}\r\n",
        encoding="utf-8",
    )


@contextmanager
def git_credential_environment(credentials: dict[str, str] | None) -> Iterator[dict[str, str] | None]:
    if not credentials:
        yield None
        return
    username = credentials.get("username", "")
    token = credentials.get("token", "")
    if not username or not token:
        raise GitOperationError("Git credential requires both username and token")
    if any(character in username or character in token for character in ("\x00", "\r", "\n")):
        raise GitOperationError("Git credential values cannot contain control characters")
    temp_dir = Path(tempfile.mkdtemp(prefix="ckb-askpass-"))
    environment: dict[str, str] | None = None
    try:
        if os.name == "nt":
            helper = temp_dir / "askpass.cmd"
            _write_windows_askpass(helper)
        else:
            helper = temp_dir / "askpass.sh"
            helper.write_text(
                "#!/bin/sh\ncase \"$1\" in *Username*) printf '%s\\n' \"$CKB_GIT_USERNAME\" ;; *) printf '%s\\n' \"$CKB_GIT_TOKEN\" ;; esac\n",
                encoding="utf-8",
            )
            helper.chmod(0o700)
        environment = os.environ.copy()
        environment.update(
            {
                "GIT_ASKPASS": str(helper),
                "GIT_ASKPASS_REQUIRE": "force",
                "GIT_TERMINAL_PROMPT": "0",
                "CKB_GIT_USERNAME": username,
                "CKB_GIT_TOKEN": token,
            }
        )
        _append_git_config(environment, "credential.username", username)
        yield environment
    finally:
        if environment is not None:
            environment.pop("CKB_GIT_USERNAME", None)
            environment.pop("CKB_GIT_TOKEN", None)
        shutil.rmtree(temp_dir, ignore_errors=True)


def ensure_repository(repo: str | Path) -> Path:
    root = Path(repo).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if _run(root, "rev-parse", "--is-inside-work-tree", check=False).returncode:
        _run(root, "init")
    return root


def initialize_company_repository(
    repo: str | Path,
    canonical_branch: str,
    tracked_paths: tuple[str, ...],
) -> dict[str, str | bool]:
    """Create a standalone company Git repository and its baseline commit."""

    root = Path(repo).resolve()
    root.mkdir(parents=True, exist_ok=True)
    created = not (root / ".git").exists()
    if created:
        result = _run(root, "init", "-b", canonical_branch, check=False)
        if result.returncode:
            _run(root, "init")
            checkout_canonical(root, canonical_branch)
    else:
        top_level = _run(root, "rev-parse", "--show-toplevel", check=False).stdout.strip()
        if not top_level or Path(top_level).resolve() != root:
            raise GitOperationError(f"company root is not its own Git repository: {root}")
        reject_tracked_private_paths(
            root,
            COMPANY_PRIVATE_TRACKED_PATHS,
            label="company repository",
            require_own_repository=True,
        )

    existing = [path for path in tracked_paths if (root / path).is_file()]
    if not existing:
        raise GitOperationError("company repository has no baseline files to commit")

    head = _run(root, "rev-parse", "--verify", "HEAD", check=False)
    initial_commit = head.returncode != 0
    if initial_commit:
        branch = _run(root, "branch", "--show-current", check=False).stdout.strip()
        if branch != canonical_branch:
            checkout_canonical(root, canonical_branch)
    else:
        branch = _run(root, "branch", "--show-current", check=False).stdout.strip()
        if branch != canonical_branch:
            raise GitOperationError(
                f"company repository must be on canonical branch {canonical_branch!r}; current branch is {branch or 'detached'}"
            )

    dirty_required = bool(
        _run(root, "status", "--porcelain=v1", "--untracked-files=all", "--", *existing).stdout.strip()
    )
    untracked_required = [
        path
        for path in existing
        if _run(root, "ls-files", "--error-unmatch", "--", path, check=False).returncode
    ]
    commit_created = initial_commit or dirty_required or bool(untracked_required)
    if commit_created:
        _run(root, "add", "--", *existing)
        _run(
            root,
            "-c",
            "user.name=Local Knowledge Suite",
            "-c",
            "user.email=local-knowledge@localhost",
            "commit",
            "-m",
            "chore(knowledge): initialize company repository",
            "--",
            *existing,
        )

    validation = validate_company_repository(root, canonical_branch, tuple(existing))
    return {
        "repository_initialized": created,
        "initial_commit_created": commit_created,
        "commit": str(validation["commit"]),
    }


def validate_company_repository(
    repo: str | Path,
    canonical_branch: str,
    tracked_paths: tuple[str, ...],
) -> dict[str, str | bool]:
    """Verify the company root owns a clean canonical Git contract."""

    root = Path(repo).resolve()
    top_level = _run(root, "rev-parse", "--show-toplevel", check=False).stdout.strip()
    if not top_level or Path(top_level).resolve() != root:
        raise GitOperationError(f"company root is not its own Git repository: {root}")
    reject_tracked_private_paths(
        root,
        COMPANY_PRIVATE_TRACKED_PATHS,
        label="company repository",
        require_own_repository=True,
    )
    head = _run(root, "rev-parse", "--verify", "HEAD", check=False)
    if head.returncode:
        raise GitOperationError("company repository has no baseline commit")
    branch = _run(root, "branch", "--show-current", check=False).stdout.strip()
    if branch != canonical_branch:
        raise GitOperationError(
            f"company repository must be on canonical branch {canonical_branch!r}; current branch is {branch or 'detached'}"
        )
    missing = [
        path
        for path in tracked_paths
        if not (root / path).is_file()
        or _run(root, "ls-files", "--error-unmatch", "--", path, check=False).returncode
    ]
    if missing:
        raise GitOperationError(
            "company repository baseline files are missing or untracked: " + ", ".join(missing)
        )
    ignore_text = (root / ".gitignore").read_text(encoding="utf-8")
    ignore_entries = {
        line.strip().casefold()
        for line in ignore_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    missing_ignores = [
        entry
        for entry in REQUIRED_COMPANY_IGNORE_ENTRIES
        if entry.casefold() not in ignore_entries
    ]
    if missing_ignores:
        raise GitOperationError(
            "company .gitignore is missing required private-state entries: "
            + ", ".join(missing_ignores)
        )
    ineffective_ignores = _ineffective_required_company_ignores(ignore_text)
    if ineffective_ignores:
        raise GitOperationError(
            "company .gitignore does not effectively ignore required private-state "
            "directories: " + ", ".join(ineffective_ignores)
        )
    dirty = _run(root, "status", "--porcelain=v1", "--untracked-files=all").stdout.strip()
    if dirty:
        raise GitOperationError("company repository worktree must be clean before registration or rebuild")
    return {
        "valid": True,
        "branch": branch,
        "commit": head.stdout.strip(),
    }


def checkout_canonical(repo: str | Path, branch: str) -> None:
    root = ensure_repository(repo)
    current = _run(root, "branch", "--show-current", check=False).stdout.strip()
    if current == branch:
        return
    exists = _run(root, "show-ref", "--verify", f"refs/heads/{branch}", check=False).returncode == 0
    _run(root, "switch", branch if exists else "-c", *( () if exists else (branch,) ))


def sync_before_publish(repo: str | Path, env: dict[str, str] | None = None) -> None:
    root = require_owned_repository(repo)
    reject_tracked_private_paths(
        root,
        COMPANY_PRIVATE_TRACKED_PATHS,
        label="company repository",
        require_own_repository=True,
    )
    dirty = _run(root, "status", "--porcelain", check=False).stdout.strip()
    if dirty:
        raise GitOperationError("worktree has uncommitted changes; refusing to pull before publication")
    remote_names = {
        name.strip()
        for name in _run(root, "remote", check=False).stdout.splitlines()
        if name.strip()
    }
    if not remote_names:
        return

    branch = _run(root, "branch", "--show-current", check=False).stdout.strip()
    if not branch:
        raise GitOperationError("company repository cannot sync from a detached HEAD")
    remote_name = _run(
        root,
        "config",
        "--get",
        f"branch.{branch}.remote",
        check=False,
    ).stdout.strip()
    merge_ref = _run(
        root,
        "config",
        "--get",
        f"branch.{branch}.merge",
        check=False,
    ).stdout.strip()
    if (
        not remote_name
        or remote_name not in remote_names
        or not merge_ref
        or _run(root, "check-ref-format", merge_ref, check=False).returncode
    ):
        raise GitOperationError(
            "current company branch must have one valid configured upstream before sync"
        )

    current_company = (
        CompanyManifest.load(root)
        if (root / ".local-knowledge" / "company.toml").is_file()
        else None
    )
    _run(
        root,
        "fetch",
        "--no-tags",
        remote_name,
        merge_ref,
        env=env,
    )
    fetched = _run(root, "rev-parse", "--verify", "FETCH_HEAD").stdout.strip()
    incoming = [
        commit.strip()
        for commit in _run(
            root,
            "rev-list",
            "--reverse",
            f"HEAD..{fetched}",
        ).stdout.splitlines()
        if commit.strip()
    ]
    for commit in incoming:
        _validate_incoming_company_revision(root, commit, current_company)

    _run(root, "rebase", fetched, env=env)
    reject_tracked_private_paths(
        root,
        COMPANY_PRIVATE_TRACKED_PATHS,
        label="company repository",
        require_own_repository=True,
    )
    if current_company is not None:
        updated_company = CompanyManifest.load(root)
        if (
            updated_company.company_id != current_company.company_id
            or updated_company.schema_version != current_company.schema_version
        ):
            raise GitOperationError(
                "company identity changed unexpectedly during sync"
            )
        reject_reparse_points(
            root / ".local-knowledge",
            "company .local-knowledge directory",
        )
        reject_reparse_points(root / "knowledge", "company knowledge store")


@contextmanager
def publication_lock(private_state_dir: str | Path) -> Iterator[None]:
    private_dir = Path(private_state_dir)
    private_dir.mkdir(parents=True, exist_ok=True)
    lock_path = private_dir / ".publish.lock"
    open_flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_BINARY"):
        open_flags |= os.O_BINARY
    descriptor = os.open(lock_path, open_flags, 0o600)
    locked = False
    try:
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except OSError as exc:
            raise GitOperationError("another publication is in progress") from exc
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        try:
            if locked:
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _publication_paths(
    repo: str | Path,
    bundle_dir: str | Path,
    relative_path: str,
) -> tuple[Path, Path, Path]:
    root = ensure_repository(repo)
    bundle = Path(bundle_dir).resolve()
    bundle.mkdir(parents=True, exist_ok=True)
    if not bundle.is_relative_to(root):
        raise GitOperationError("bundle directory must be inside the Git repository")
    target = (bundle / relative_path).resolve()
    if not target.is_relative_to(bundle) or target.suffix.lower() != ".md":
        raise GitOperationError("invalid concept path")
    return root, bundle, target


def _publish_markdown_locked(
    root: Path,
    bundle: Path,
    target: Path,
    markdown: str,
    title: str,
    *,
    sync: bool = True,
    actor_name: str = "Company Knowledge Base",
    actor_email: str = "ckb@localhost",
    publication_id: str | None = None,
    git_env: dict[str, str] | None = None,
) -> str:
    if sync:
        sync_before_publish(root, git_env)
    previous_files = {path.relative_to(bundle): path.read_bytes() for path in bundle.rglob("*.md")}
    attempted_paths: list[str] = []
    try:
        atomic_write(target, markdown)
        changed = [target, *regenerate_indexes(bundle)]
        changed.append(append_log(bundle, "Update" if target.relative_to(bundle) in previous_files else "Creation", target.relative_to(bundle).as_posix()))
        failures = validate_bundle(bundle)
        if failures:
            raise GitOperationError(f"OKF validation failed: {failures}")
        relative_files = [str(path.relative_to(root)) for path in dict.fromkeys(changed)]
        attempted_paths = relative_files
        _run(root, "add", "--", *relative_files)
        staged = _run(root, "diff", "--cached", "--quiet", check=False)
        if staged.returncode == 0:
            return "no changes"
        message = f"docs(knowledge): publish {title}"
        if publication_id:
            message += f"\n\nCKB-Publication: {publication_id}"
        _run(
            root,
            "-c",
            f"user.name={actor_name}",
            "-c",
            f"user.email={actor_email}",
            "commit",
            "-m",
            message,
            "--",
            *relative_files,
        )
        return _run(root, "rev-parse", "HEAD").stdout.strip()
    except Exception:
        for current in bundle.rglob("*.md"):
            if current.relative_to(bundle) not in previous_files:
                current.unlink(missing_ok=True)
        for relative, content in previous_files.items():
            restored = bundle / relative
            restored.parent.mkdir(parents=True, exist_ok=True)
            restored.write_bytes(content)
        if attempted_paths:
            _run(root, "restore", "--staged", "--", *attempted_paths, check=False)
            _run(root, "rm", "--cached", "--ignore-unmatch", "--", *attempted_paths, check=False)
        raise


def publish_markdown(
    repo: str | Path,
    bundle_dir: str | Path,
    relative_path: str,
    markdown: str,
    title: str,
    *,
    sync: bool = True,
    actor_name: str = "Company Knowledge Base",
    actor_email: str = "ckb@localhost",
    publication_id: str | None = None,
    credentials: dict[str, str] | None = None,
) -> str:
    root, bundle, target = _publication_paths(repo, bundle_dir, relative_path)
    with publication_lock(root / ".ckb"), git_credential_environment(credentials) as git_env:
        return _publish_markdown_locked(
            root,
            bundle,
            target,
            markdown,
            title,
            sync=sync,
            actor_name=actor_name,
            actor_email=actor_email,
            publication_id=publication_id,
            git_env=git_env,
        )


def publish_candidate(
    repo: str | Path,
    bundle_dir: str | Path,
    candidate_branch: str,
    relative_path: str,
    markdown: str,
    title: str,
    *,
    actor_name: str,
    actor_email: str,
    publication_id: str,
    credentials: dict[str, str] | None = None,
) -> str:
    root = ensure_repository(repo)
    bundle = Path(bundle_dir).resolve()
    if not bundle.is_relative_to(root):
        raise GitOperationError("bundle directory must be inside the Git repository")
    if _run(root, "rev-parse", "HEAD", check=False).returncode:
        raise GitOperationError("candidate publication requires an initial Git commit")
    commit: str | None = None
    with (
        publication_lock(root / ".ckb"),
        git_credential_environment(credentials) as git_env,
        tempfile.TemporaryDirectory(prefix="ckb-worktree-") as temp_dir,
    ):
        sync_before_publish(root, git_env)
        worktree = Path(temp_dir)
        added = False
        try:
            _run(root, "worktree", "add", "-b", candidate_branch, str(worktree), "HEAD")
            added = True
            relative_bundle = bundle.relative_to(root)
            worktree_root, worktree_bundle, target = _publication_paths(
                worktree,
                worktree / relative_bundle,
                relative_path,
            )
            commit = _publish_markdown_locked(
                worktree_root,
                worktree_bundle,
                target,
                markdown,
                title,
                sync=False,
                actor_name=actor_name,
                actor_email=actor_email,
                publication_id=publication_id,
            )
        finally:
            if added:
                _run(root, "worktree", "remove", "--force", str(worktree), check=False)
    if commit is None:
        raise GitOperationError("candidate commit was not created")
    if _run(root, "remote", check=False).stdout.strip():
        with git_credential_environment(credentials) as git_env:
            _run(root, "push", "--set-upstream", "origin", candidate_branch, env=git_env)
    return commit


def merge_candidate(
    repo: str | Path,
    canonical_branch: str,
    candidate_branch: str,
    *,
    actor_name: str,
    actor_email: str,
    publication_id: str,
    credentials: dict[str, str] | None = None,
) -> str:
    root = ensure_repository(repo)
    dirty = _run(root, "status", "--porcelain", check=False).stdout.strip()
    if dirty:
        raise GitOperationError("worktree has uncommitted changes; refusing to merge publication")
    current = _run(root, "branch", "--show-current", check=False).stdout.strip()
    if current != canonical_branch:
        _run(root, "switch", canonical_branch)
    with git_credential_environment(credentials) as git_env:
        _run(
            root,
            "-c",
            f"user.name={actor_name}",
            "-c",
            f"user.email={actor_email}",
            "merge",
            "--no-ff",
            candidate_branch,
            "-m",
            f"docs(knowledge): merge publication {publication_id}",
            env=git_env,
        )
    return _run(root, "rev-parse", "HEAD").stdout.strip()


def find_publication_commit(repo: str | Path, publication_id: str) -> str | None:
    root = ensure_repository(repo)
    result = _run(
        root,
        "log",
        "--all",
        "--fixed-strings",
        f"--grep=CKB-Publication: {publication_id}",
        "-1",
        "--format=%H",
        check=False,
    )
    commit = result.stdout.strip()
    return commit or None


def push(repo: str | Path, credentials: dict[str, str] | None = None) -> None:
    root = require_owned_repository(repo)
    reject_tracked_private_paths(
        root,
        COMPANY_PRIVATE_TRACKED_PATHS,
        label="company repository",
        require_own_repository=True,
    )
    with git_credential_environment(credentials) as git_env:
        _run(root, "push", env=git_env)


def pull(repo: str | Path, credentials: dict[str, str] | None = None) -> dict[str, str]:
    with git_credential_environment(credentials) as git_env:
        sync_before_publish(repo, git_env)
    reject_tracked_private_paths(
        repo,
        COMPANY_PRIVATE_TRACKED_PATHS,
        label="company repository",
        require_own_repository=True,
    )
    return status(repo)


def status(repo: str | Path) -> dict[str, str]:
    root = require_owned_repository(repo)
    return {
        "branch": _sanitize_git_output(
            _run(root, "branch", "--show-current", check=False).stdout.strip()
        ),
        "head": _sanitize_git_output(
            _run(root, "rev-parse", "HEAD", check=False).stdout.strip()
        ),
        "changes": _sanitize_git_output(
            _run(root, "status", "--porcelain", check=False).stdout
        ),
        "remotes": _sanitize_git_output(
            _run(root, "remote", "-v", check=False).stdout
        ),
    }
