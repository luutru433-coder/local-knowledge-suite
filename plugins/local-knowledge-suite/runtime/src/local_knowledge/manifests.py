# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import re
import tempfile
import tomllib
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import WORKSPACE_SCHEMA_VERSION
from .errors import CompatibilityError, ManifestError
from .winio import reject_reparse_points, replace_file


PROJECT_MANIFEST = Path(".local-knowledge/project.toml")
COMPANY_MANIFEST = Path(".local-knowledge/company.toml")
Profile = Literal["combined", "memory-only", "company-only"]
InstallMode = Literal["global", "vendored"]
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def validate_id(value: str, field: str) -> str:
    normalized = value.strip().lower()
    if not _ID_RE.fullmatch(normalized):
        raise ManifestError(f"{field} must match {_ID_RE.pattern}")
    return normalized


def _quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ManifestError(f"missing manifest: {path}") from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc


def _schema(value: object, path: Path) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ManifestError(f"invalid schema_version in {path}")
    if value > WORKSPACE_SCHEMA_VERSION:
        raise CompatibilityError(
            f"{path} uses schema {value}; runtime supports {WORKSPACE_SCHEMA_VERSION}. Upgrade the plugin."
        )
    return value


@dataclass(frozen=True, slots=True)
class ProjectManifest:
    schema_version: int
    project_id: str
    company_id: str | None = None
    profile: Profile = "memory-only"
    install_mode: InstallMode = "global"
    memory_path: str = ".memorizer"

    @classmethod
    def load(cls, root: str | Path) -> "ProjectManifest":
        path = Path(root).resolve() / PROJECT_MANIFEST
        data = _read(path)
        schema_version = _schema(data.get("schema_version"), path)
        profile = str(
            data.get("profile", "combined" if schema_version <= 1 else "memory-only")
        )
        install_mode = str(data.get("install_mode", "global"))
        memory_path = str(data.get("memory_path", ".memorizer"))
        if profile not in {"combined", "memory-only", "company-only"}:
            raise ManifestError(f"invalid profile in {path}: {profile}")
        if install_mode not in {"global", "vendored"}:
            raise ManifestError(f"invalid install_mode in {path}: {install_mode}")
        if memory_path != ".memorizer":
            raise ManifestError(
                f"memory_path must be exactly '.memorizer' in {path}"
            )
        raw_company_id = data.get("company_id")
        company_id = (
            None
            if raw_company_id is None or not str(raw_company_id).strip()
            else validate_id(str(raw_company_id), "company_id")
        )
        if profile in {"combined", "company-only"} and company_id is None:
            raise ManifestError(f"profile {profile} requires company_id in {path}")
        return cls(
            schema_version=schema_version,
            project_id=validate_id(str(data.get("project_id", "")), "project_id"),
            company_id=company_id,
            profile=profile,  # type: ignore[arg-type]
            install_mode=install_mode,  # type: ignore[arg-type]
            memory_path=memory_path,
        )

    def dump(self) -> str:
        lines = [
            f"schema_version = {self.schema_version}",
            f"project_id = {_quoted(self.project_id)}",
        ]
        if self.company_id is not None:
            lines.append(f"company_id = {_quoted(self.company_id)}")
        lines.extend(
            (
                f"profile = {_quoted(self.profile)}",
                f"install_mode = {_quoted(self.install_mode)}",
                f"memory_path = {_quoted(self.memory_path)}",
            )
        )
        return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class CompanyManifest:
    schema_version: int
    company_id: str
    name: str

    @classmethod
    def load(cls, root: str | Path) -> "CompanyManifest":
        path = Path(root).resolve() / COMPANY_MANIFEST
        data = _read(path)
        name = str(data.get("name", "")).strip()
        if not name:
            raise ManifestError(f"company name is missing in {path}")
        return cls(
            schema_version=_schema(data.get("schema_version"), path),
            company_id=validate_id(str(data.get("company_id", "")), "company_id"),
            name=name,
        )

    def dump(self) -> str:
        return (
            f"schema_version = {self.schema_version}\n"
            f"company_id = {_quoted(self.company_id)}\n"
            f"name = {_quoted(self.name)}\n"
        )


def new_project_manifest(
    company_id: str | None = None,
    profile: Profile = "memory-only",
    install_mode: InstallMode = "global",
) -> ProjectManifest:
    if profile in {"combined", "company-only"} and company_id is None:
        raise ManifestError(f"profile {profile} requires company_id")
    return ProjectManifest(
        schema_version=WORKSPACE_SCHEMA_VERSION,
        project_id=f"project-{uuid.uuid4().hex}",
        company_id=(
            validate_id(company_id, "company_id") if company_id is not None else None
        ),
        profile=profile,
        install_mode=install_mode,
    )


def write_project_manifest(root: str | Path, manifest: ProjectManifest) -> tuple[Path, bool]:
    path = Path(root).resolve() / PROJECT_MANIFEST
    reject_reparse_points(path.parent, "project .local-knowledge directory")
    if path.exists():
        current = ProjectManifest.load(root)
        if current.company_id != manifest.company_id:
            raise ManifestError(
                "project company binding is immutable: "
                f"existing={current.company_id!r}, requested={manifest.company_id!r}"
            )
        return path, False
    _atomic_text(path, manifest.dump())
    return path, True


def write_company_manifest(root: str | Path, manifest: CompanyManifest) -> tuple[Path, bool]:
    path = Path(root).resolve() / COMPANY_MANIFEST
    reject_reparse_points(path.parent, "company .local-knowledge directory")
    if path.exists():
        current = CompanyManifest.load(root)
        if current.company_id != manifest.company_id or current.name != manifest.name:
            raise ManifestError("company manifest already exists with different identity")
        return path, False
    _atomic_text(path, manifest.dump())
    return path, True


def replace_project_manifest(root: str | Path, manifest: ProjectManifest) -> Path:
    path = Path(root).resolve() / PROJECT_MANIFEST
    reject_reparse_points(path.parent, "project .local-knowledge directory")
    _atomic_text(path, manifest.dump())
    return path


def replace_company_manifest(root: str | Path, manifest: CompanyManifest) -> Path:
    path = Path(root).resolve() / COMPANY_MANIFEST
    reject_reparse_points(path.parent, "company .local-knowledge directory")
    _atomic_text(path, manifest.dump())
    return path
