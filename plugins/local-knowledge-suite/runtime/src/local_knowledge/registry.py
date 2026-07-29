# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from . import REGISTRY_SCHEMA_VERSION
from .errors import ManifestError, RegistryError
from .manifests import CompanyManifest, validate_id
from .winio import replace_file


_PROCESS_GUARDS_LOCK = threading.Lock()
_PROCESS_GUARDS: dict[str, threading.RLock] = {}
_THREAD_HELD_GUARDS = threading.local()


def _process_guard(key: str) -> threading.RLock:
    with _PROCESS_GUARDS_LOCK:
        return _PROCESS_GUARDS.setdefault(key, threading.RLock())


def default_registry_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    return Path(local_app_data).resolve() / "LocalKnowledgeSuite" / "registry.json"


class CompanyRegistry:
    """Machine-local Windows mapping from stable company IDs to repository roots."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).resolve() if path else default_registry_path()

    @property
    def lock_path(self) -> Path:
        return self.path.with_name(f"{self.path.name}.lock")

    @contextmanager
    def mutation_guard(self) -> Iterator["CompanyRegistry"]:
        """Serialize registry transactions across threads and processes."""

        lock_path = self.lock_path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        key = os.path.normcase(str(lock_path.resolve()))
        process_guard = _process_guard(key)
        with process_guard:
            held: dict[str, tuple[int, int]] = getattr(
                _THREAD_HELD_GUARDS,
                "descriptors",
                {},
            )
            _THREAD_HELD_GUARDS.descriptors = held
            existing = held.get(key)
            if existing is not None:
                descriptor, depth = existing
                held[key] = (descriptor, depth + 1)
                try:
                    yield self
                finally:
                    held[key] = (descriptor, depth)
                return

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

                        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(descriptor, fcntl.LOCK_EX)
                    locked = True
                except OSError as exc:
                    raise RegistryError(
                        f"machine-local registry is busy: {self.path}"
                    ) from exc
                held[key] = (descriptor, 1)
                try:
                    yield self
                finally:
                    del held[key]
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

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "schema_version": REGISTRY_SCHEMA_VERSION,
                "companies": {},
                "projects": {},
            }
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RegistryError(f"cannot read company registry {self.path}: {exc}") from exc
        if not isinstance(data, dict):
            raise RegistryError(f"unsupported or invalid registry schema in {self.path}")
        schema_version = data.get("schema_version")
        companies = data.get("companies")
        projects = data.get("projects", {})
        if (
            not isinstance(schema_version, int)
            or isinstance(schema_version, bool)
            or schema_version != REGISTRY_SCHEMA_VERSION
            or not isinstance(companies, dict)
            or not isinstance(projects, dict)
        ):
            raise RegistryError(f"unsupported or invalid registry schema in {self.path}")
        for company_id, entry in companies.items():
            if not isinstance(company_id, str):
                raise RegistryError(f"invalid company ID in registry {self.path}")
            try:
                canonical_id = validate_id(company_id, "company_id")
            except ManifestError as exc:
                raise RegistryError(
                    f"invalid company ID {company_id!r} in registry {self.path}"
                ) from exc
            if canonical_id != company_id:
                raise RegistryError(
                    f"company ID {company_id!r} is not canonical in registry {self.path}"
                )
            self._entry_root(company_id, entry)
        for project_id, entry in projects.items():
            if not isinstance(project_id, str):
                raise RegistryError(f"invalid project ID in registry {self.path}")
            try:
                canonical_id = validate_id(project_id, "project_id")
            except ManifestError as exc:
                raise RegistryError(
                    f"invalid project ID {project_id!r} in registry {self.path}"
                ) from exc
            if canonical_id != project_id:
                raise RegistryError(
                    f"project ID {project_id!r} is not canonical in registry {self.path}"
                )
            self._project_entry(project_id, entry)
        # Schema 1 registries created before project enrollment remain readable.
        # The new private section is added only on the next authorized write.
        data["projects"] = projects
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".registry.", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            replace_file(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    @staticmethod
    def _canonical_directory(root: str | Path) -> Path:
        requested_root = Path(root)
        if not requested_root.is_absolute():
            raise RegistryError("company root must be an absolute canonical path")
        try:
            company_root = requested_root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RegistryError(f"company root is unavailable: {requested_root}") from exc
        if os.path.normcase(str(requested_root)) != os.path.normcase(str(company_root)):
            raise RegistryError(
                f"company root must be canonical: requested={requested_root}, canonical={company_root}"
            )
        if not company_root.is_dir():
            raise RegistryError(f"company root is not a directory: {company_root}")
        return company_root

    def _assert_registration_conflicts(
        self,
        company_root: Path,
        identifier: str,
        data: dict[str, Any],
    ) -> None:
        companies: dict[str, Any] = data["companies"]
        normalized = os.path.normcase(str(company_root))
        existing = companies.get(identifier)
        if existing is not None:
            existing_root = self._entry_root(identifier, existing)
            if os.path.normcase(str(existing_root)) != normalized:
                raise RegistryError(
                    f"company {identifier} is already registered at {existing_root}"
                )
        for registered_id, entry in companies.items():
            if registered_id == identifier:
                continue
            registered_root = self._entry_root(registered_id, entry)
            if os.path.normcase(str(registered_root)) == normalized:
                raise RegistryError(
                    "registry identity mismatch: "
                    f"{company_root} is already registered as {registered_id}"
                )

    def assert_can_initialize(self, root: str | Path, company_id: str) -> Path:
        """Preflight an existing or prospective company root without creating it."""

        requested_root = Path(root).expanduser()
        if not requested_root.is_absolute():
            raise RegistryError("company root must be an absolute canonical path")
        try:
            company_root = requested_root.resolve(strict=False)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RegistryError(f"company root is unavailable: {requested_root}") from exc
        if company_root.exists() and not company_root.is_dir():
            raise RegistryError(f"company root is not a directory: {company_root}")
        identifier = validate_id(company_id, "company_id")
        with self.mutation_guard():
            self._assert_registration_conflicts(
                company_root,
                identifier,
                self._load(),
            )
        return company_root

    def assert_can_register(self, root: str | Path, company_id: str) -> Path:
        """Fail before repository writes when a machine-local identity conflicts."""

        company_root = self._canonical_directory(root)
        identifier = validate_id(company_id, "company_id")
        with self.mutation_guard():
            self._assert_registration_conflicts(
                company_root,
                identifier,
                self._load(),
            )
        return company_root

    def register(self, root: str | Path) -> dict[str, Any]:
        company_root = self._canonical_directory(root)
        manifest = CompanyManifest.load(company_root)
        with self.mutation_guard():
            data = self._load()
            self._assert_registration_conflicts(
                company_root,
                manifest.company_id,
                data,
            )
            companies: dict[str, Any] = data["companies"]
            existing = companies.get(manifest.company_id)
            entry = existing or {
                "root": str(company_root),
                "registered_at": datetime.now(UTC).isoformat(),
            }
            companies[manifest.company_id] = entry
            self._write(data)
            return {
                "company_id": manifest.company_id,
                **entry,
                "registry": str(self.path),
            }

    @staticmethod
    def _canonical_project_directory(root: str | Path) -> Path:
        requested_root = Path(root)
        if not requested_root.is_absolute():
            raise RegistryError("project root must be an absolute canonical path")
        try:
            project_root = requested_root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RegistryError(f"project root is unavailable: {requested_root}") from exc
        if os.path.normcase(str(requested_root)) != os.path.normcase(str(project_root)):
            raise RegistryError(
                f"project root must be canonical: requested={requested_root}, canonical={project_root}"
            )
        if not project_root.is_dir():
            raise RegistryError(f"project root is not a directory: {project_root}")
        return project_root

    @staticmethod
    def _project_entry(project_id: str, entry: object) -> tuple[Path, str, str]:
        if not isinstance(entry, dict):
            raise RegistryError(f"project {project_id} has an invalid authorization entry")
        raw_root = entry.get("root")
        raw_company_id = entry.get("company_id")
        authorized_at = entry.get("authorized_at")
        if (
            not isinstance(raw_root, str)
            or not raw_root
            or raw_root != raw_root.strip()
            or not isinstance(raw_company_id, str)
            or not raw_company_id
            or raw_company_id != raw_company_id.strip()
            or not isinstance(authorized_at, str)
            or not authorized_at
            or authorized_at != authorized_at.strip()
        ):
            raise RegistryError(f"project {project_id} has an invalid authorization entry")
        try:
            company_id = validate_id(raw_company_id, "company_id")
        except ManifestError as exc:
            raise RegistryError(
                f"project {project_id} has an invalid authorized company ID"
            ) from exc
        if company_id != raw_company_id:
            raise RegistryError(
                f"project {project_id} has a non-canonical authorized company ID"
            )
        try:
            timestamp = datetime.fromisoformat(authorized_at)
        except ValueError as exc:
            raise RegistryError(
                f"project {project_id} has an invalid authorization timestamp"
            ) from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise RegistryError(
                f"project {project_id} has an invalid authorization timestamp"
            )
        registered_root = Path(raw_root)
        if not registered_root.is_absolute():
            raise RegistryError(
                f"project {project_id} has a non-absolute authorized root"
            )
        try:
            canonical_root = registered_root.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise RegistryError(
                f"project {project_id} has an invalid authorized root"
            ) from exc
        if os.path.normcase(raw_root) != os.path.normcase(str(canonical_root)):
            raise RegistryError(
                f"project {project_id} has a non-canonical authorized root"
            )
        return canonical_root, company_id, authorized_at

    def authorize_project(
        self,
        root: str | Path,
        project_id: str,
        company_id: str,
        *,
        allow_rebind: bool = False,
    ) -> dict[str, Any]:
        """Authorize one explicit project root to use one registered company."""

        project_root = self._canonical_project_directory(root)
        identifier = validate_id(project_id, "project_id")
        authorized_company = validate_id(company_id, "company_id")
        with self.mutation_guard():
            return self._authorize_project_locked(
                project_root,
                identifier,
                authorized_company,
                allow_rebind=allow_rebind,
            )

    def _authorize_project_locked(
        self,
        root: str | Path,
        project_id: str,
        company_id: str,
        *,
        allow_rebind: bool,
    ) -> dict[str, Any]:
        project_root = self._canonical_project_directory(root)
        identifier = validate_id(project_id, "project_id")
        authorized_company = validate_id(company_id, "company_id")
        data = self._load()
        if authorized_company not in data["companies"]:
            raise RegistryError(
                f"company {authorized_company} is not registered; register it before authorizing a project"
            )
        projects: dict[str, Any] = data["projects"]
        existing = projects.get(identifier)
        if existing is not None:
            existing_root, existing_company, authorized_at = self._project_entry(
                identifier,
                existing,
            )
            if existing_company != authorized_company:
                raise RegistryError(
                    "project authorization company binding is immutable: "
                    f"project={identifier}, existing={existing_company}, requested={authorized_company}"
                )
            if os.path.normcase(str(existing_root)) != os.path.normcase(
                str(project_root)
            ):
                if not allow_rebind:
                    raise RegistryError(
                        f"project {identifier} is authorized at {existing_root}, not {project_root}; "
                        "run `local-knowledge restore --root PROJECT_ROOT` to explicitly re-enroll the moved clone"
                    )
                authorized_at = datetime.now(UTC).isoformat()
        else:
            authorized_at = datetime.now(UTC).isoformat()
        entry = {
            "root": str(project_root),
            "company_id": authorized_company,
            "authorized_at": authorized_at,
        }
        projects[identifier] = entry
        self._write(data)
        return {
            "project_id": identifier,
            **entry,
            "registry": str(self.path),
        }

    def assert_project_authorized(
        self,
        root: str | Path,
        project_id: str,
        company_id: str,
    ) -> dict[str, Any]:
        """Fail closed unless the exact machine-local project binding exists."""

        project_root = self._canonical_project_directory(root)
        identifier = validate_id(project_id, "project_id")
        expected_company = validate_id(company_id, "company_id")
        entry = self._load()["projects"].get(identifier)
        if entry is None:
            raise RegistryError(
                f"project {identifier} is not locally authorized for company {expected_company}; "
                "run `local-knowledge restore --root PROJECT_ROOT` or explicitly bootstrap the project"
            )
        authorized_root, authorized_company, authorized_at = self._project_entry(
            identifier,
            entry,
        )
        if authorized_company != expected_company:
            raise RegistryError(
                "project authorization company mismatch: "
                f"project={identifier}, authorized={authorized_company}, requested={expected_company}"
            )
        if os.path.normcase(str(authorized_root)) != os.path.normcase(
            str(project_root)
        ):
            raise RegistryError(
                f"project {identifier} is authorized at {authorized_root}, not {project_root}; "
                "run `local-knowledge restore --root PROJECT_ROOT` to explicitly re-enroll the moved clone"
            )
        return {
            "project_id": identifier,
            "root": str(authorized_root),
            "company_id": authorized_company,
            "authorized_at": authorized_at,
            "registry": str(self.path),
        }

    def list_projects(self) -> dict[str, dict[str, Any]]:
        return dict(self._load()["projects"])

    @staticmethod
    def _entry_root(company_id: str, entry: object) -> Path:
        if not isinstance(entry, dict):
            raise RegistryError(f"company {company_id} has an invalid registry entry")
        raw_root = entry.get("root")
        registered_at = entry.get("registered_at")
        if (
            not isinstance(raw_root, str)
            or not raw_root
            or raw_root != raw_root.strip()
            or not isinstance(registered_at, str)
            or not registered_at
            or registered_at != registered_at.strip()
        ):
            raise RegistryError(f"company {company_id} has an invalid registry entry")
        try:
            timestamp = datetime.fromisoformat(registered_at)
        except ValueError as exc:
            raise RegistryError(
                f"company {company_id} has an invalid registration timestamp"
            ) from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise RegistryError(
                f"company {company_id} has an invalid registration timestamp"
            )
        registered_root = Path(raw_root)
        if not registered_root.is_absolute():
            raise RegistryError(
                f"company {company_id} has a non-absolute registry root"
            )
        try:
            canonical_root = registered_root.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise RegistryError(
                f"company {company_id} has an invalid registry root"
            ) from exc
        if os.path.normcase(raw_root) != os.path.normcase(str(canonical_root)):
            raise RegistryError(
                f"company {company_id} has a non-canonical registry root"
            )
        return canonical_root

    def unregister(self, root: str | Path) -> dict[str, Any]:
        """Remove exactly one verified company-to-root mapping.

        The repository itself is never modified. An absent mapping is an
        idempotent no-op, while identity or root mismatches block all writes.
        Project authorizations for the removed company are revoked in the same
        registry write so they cannot silently follow a reused company ID.
        """

        company_root = Path(root).expanduser()
        if not company_root.is_absolute():
            raise RegistryError("company root must be an absolute Windows path")
        company_root = company_root.resolve(strict=True)
        if not company_root.is_dir():
            raise RegistryError(f"company root is not a directory: {company_root}")
        CompanyManifest.load(company_root)
        with self.mutation_guard():
            return self._unregister_locked(company_root)

    def _unregister_locked(self, root: str | Path) -> dict[str, Any]:
        company_root = Path(root).expanduser()
        if not company_root.is_absolute():
            raise RegistryError("company root must be an absolute Windows path")
        company_root = company_root.resolve(strict=True)
        if not company_root.is_dir():
            raise RegistryError(f"company root is not a directory: {company_root}")
        manifest = CompanyManifest.load(company_root)
        data = self._load()
        companies: dict[str, Any] = data["companies"]
        projects: dict[str, Any] = data["projects"]
        normalized_root = os.path.normcase(str(company_root))
        matching_ids = [
            str(company_id)
            for company_id, entry in companies.items()
            if os.path.normcase(str(self._entry_root(str(company_id), entry)))
            == normalized_root
        ]
        existing = companies.get(manifest.company_id)
        if existing is None:
            if matching_ids:
                raise RegistryError(
                    "registry identity mismatch: "
                    f"{company_root} is registered as {', '.join(sorted(matching_ids))}, "
                    f"but its manifest declares {manifest.company_id}"
                )
            revoked_projects = sorted(
                project_id
                for project_id, entry in projects.items()
                if self._project_entry(project_id, entry)[1] == manifest.company_id
            )
            for project_id in revoked_projects:
                del projects[project_id]
            if revoked_projects:
                self._write(data)
            return {
                "company_id": manifest.company_id,
                "root": str(company_root),
                "registry": str(self.path),
                "unregistered": False,
                "revoked_projects": revoked_projects,
            }

        registered_root = self._entry_root(manifest.company_id, existing)
        if os.path.normcase(str(registered_root)) != normalized_root:
            raise RegistryError(
                f"registry root mismatch for company {manifest.company_id}: "
                f"registered={registered_root}, requested={company_root}"
            )
        aliases = sorted(
            identifier for identifier in matching_ids if identifier != manifest.company_id
        )
        if aliases:
            raise RegistryError(
                "registry identity mismatch: "
                f"{company_root} is also registered as {', '.join(aliases)}"
            )

        revoked_projects = sorted(
            project_id
            for project_id, entry in projects.items()
            if self._project_entry(project_id, entry)[1] == manifest.company_id
        )
        del companies[manifest.company_id]
        for project_id in revoked_projects:
            del projects[project_id]
        self._write(data)
        return {
            "company_id": manifest.company_id,
            "root": str(company_root),
            "registry": str(self.path),
            "unregistered": True,
            "revoked_projects": revoked_projects,
        }

    def resolve(self, company_id: str) -> Path:
        identifier = validate_id(company_id, "company_id")
        entry = self._load()["companies"].get(identifier)
        if entry is None:
            raise RegistryError(
                f"company {identifier} is not registered; run `local-knowledge company register --root PATH`"
            )
        root = self._entry_root(identifier, entry)
        if not root.is_dir():
            raise RegistryError(f"registered company path is unavailable: {root}")
        manifest = CompanyManifest.load(root)
        if manifest.company_id != identifier:
            raise RegistryError(f"registry identity mismatch for company {identifier}")
        try:
            current_root = root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RegistryError(f"registered company path is unavailable: {root}") from exc
        if os.path.normcase(str(current_root)) != os.path.normcase(str(root)):
            raise RegistryError(
                f"registered company path identity changed for company {identifier}"
            )
        return root

    def list(self) -> dict[str, dict[str, Any]]:
        return dict(self._load()["companies"])
