# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

"""Fixtures and a narrow compatibility adapter for the portable runtime contract."""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
import sys
import tomllib
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPOSITORY_ROOT / "plugins" / "local-knowledge-suite"
RUNTIME_ROOT = PLUGIN_ROOT / "runtime"
RUNTIME_SRC = RUNTIME_ROOT / "src"

if str(RUNTIME_SRC) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SRC))


FUNCTION_MODULES = (
    "local_knowledge",
    "local_knowledge.workspace",
    "local_knowledge.services",
    "local_knowledge.core",
    "local_knowledge.service",
    "local_knowledge.portable",
    "local_knowledge.registry",
    "local_knowledge.migration",
)


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    for method_name in ("model_dump", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            result = method()
            if isinstance(result, Mapping):
                return dict(result)
    if isinstance(value, Path):
        return {"path": str(value)}
    raise AssertionError(
        "portable runtime operations must return a mapping, dataclass, Path, "
        f"or None; got {type(value)!r}"
    )


def flatten_mapping(value: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested mappings so layouts can evolve without weakening field checks."""

    flattened: dict[str, Any] = {}
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            flattened[path] = child
            flattened.update(flatten_mapping(child, path))
    return flattened


def value_for_key(value: Mapping[str, Any], key: str) -> Any:
    matches = [
        item
        for path, item in flatten_mapping(value).items()
        if path.rsplit(".", 1)[-1] == key
    ]
    if not matches:
        raise AssertionError(f"required field {key!r} is missing from {value!r}")
    return matches[0]


def read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def section_text(payload: Any, section_name: str) -> str:
    """Return one authority section, excluding echoed query and root metadata."""

    wanted = section_name.casefold()
    collected: list[Any] = []

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            source = str(value.get("source", "")).casefold()
            authority = str(value.get("authority", "")).casefold()
            if wanted in source or (
                wanted == "memory" and authority == "remembered_context"
            ):
                collected.append(value)
                return
            for raw_key, child in value.items():
                key = str(raw_key).casefold()
                if key in {wanted, f"{wanted}s"}:
                    collected.append(child)
                elif key not in {"query", "root", "workspace", "request"}:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return json.dumps(collected, ensure_ascii=False, sort_keys=True).casefold()


class RuntimeContract:
    """Find canonical operations while tolerating temporary module/name movement."""

    read_toml = staticmethod(read_toml)
    flatten_mapping = staticmethod(flatten_mapping)
    value_for_key = staticmethod(value_for_key)
    section_text = staticmethod(section_text)

    aliases = {
        "company_init": (
            "init_company",
            "initialize_company_repository",
            "company_init",
            "create_company",
        ),
        "company_register": ("register_company", "company_register"),
        "project_init": (
            "init_project",
            "bootstrap_workspace",
            "project_init",
            "create_project",
        ),
        "bootstrap": ("bootstrap_workspace",),
        "restore": ("restore_workspace",),
        "doctor": ("doctor_workspace", "project_doctor", "doctor"),
        "migrate": ("migrate_workspace", "project_migrate", "migrate"),
        "status": ("knowledge_status",),
        "recall": ("recall_context",),
        "capture": ("capture_memory",),
    }

    parameter_aliases = {
        "root": ("root", "path", "workspace_root", "project_root", "company_root"),
        "company_id": ("company_id", "company", "id", "slug"),
        "name": ("name", "company_name", "display_name"),
        "admin": ("admin", "admin_user", "admin_username", "username"),
        "install_mode": ("install_mode", "mode"),
        "profile": ("profile",),
        "query": ("query", "text"),
        "kind": ("kind", "memory_kind", "signal_kind"),
        "title": ("title",),
        "text": ("text", "body"),
        "memory_key": ("memory_key", "key"),
        "event_id": ("event_id", "id"),
        "tags": ("tags",),
        "importance": ("importance",),
        "pinned": ("pinned",),
        "supersedes": ("supersedes",),
        "limit": ("limit",),
        "include_skills": ("include_skills",),
        "include_memory": ("include_memory",),
        "include_company": ("include_company",),
        "include_sensitive_memory": ("include_sensitive_memory",),
        "dry_run": ("dry_run",),
    }

    def __init__(self) -> None:
        if not RUNTIME_SRC.is_dir():
            raise AssertionError(f"portable runtime source directory is missing: {RUNTIME_SRC}")
        self.modules: list[Any] = []
        import_errors: dict[str, str] = {}
        for module_name in FUNCTION_MODULES:
            try:
                self.modules.append(importlib.import_module(module_name))
            except ModuleNotFoundError as exc:
                if exc.name != module_name:
                    import_errors[module_name] = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # pragma: no cover - assertion text is the output
                import_errors[module_name] = f"{type(exc).__name__}: {exc}"
        if not self.modules:
            raise AssertionError(
                "portable package local_knowledge could not be imported from "
                f"{RUNTIME_SRC}; errors={import_errors}"
            )
        self.import_errors = import_errors

    def callable(self, operation: str) -> Callable[..., Any]:
        names = self.aliases[operation]
        for module in self.modules:
            for name in names:
                candidate = getattr(module, name, None)
                if callable(candidate):
                    return candidate
        searched = ", ".join(module.__name__ for module in self.modules)
        raise AssertionError(
            f"portable operation {operation!r} is missing; expected one of "
            f"{names!r} in {searched}. Import errors: {self.import_errors}"
        )

    def _invoke(self, operation: str, **canonical: Any) -> dict[str, Any]:
        function = self.callable(operation)
        signature = inspect.signature(function)
        parameters = signature.parameters
        accepts_kwargs = any(
            item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()
        )
        arguments: dict[str, Any] = {}
        for canonical_name, value in canonical.items():
            aliases = self.parameter_aliases.get(canonical_name, (canonical_name,))
            destination = next((name for name in aliases if name in parameters), None)
            if destination is not None:
                arguments[destination] = value
            elif accepts_kwargs:
                arguments[canonical_name] = value
        missing = [
            name
            for name, parameter in parameters.items()
            if parameter.default is inspect.Parameter.empty
            and parameter.kind
            not in {inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD}
            and name not in arguments
        ]
        if missing:
            raise AssertionError(
                f"{function.__module__}.{function.__name__}{signature} has unsupported "
                f"required parameters {missing}; canonical inputs were {sorted(canonical)}"
            )
        return _as_mapping(function(**arguments))

    def init_company(
        self, root: Path, company_id: str, name: str, admin: str | None = None
    ) -> dict[str, Any]:
        return self._invoke(
            "company_init",
            root=str(root.resolve()),
            company_id=company_id,
            name=name,
            admin=admin,
        )

    def register_company(self, root: Path) -> dict[str, Any]:
        return self._invoke("company_register", root=str(root.resolve()))

    def init_project(
        self,
        root: Path,
        company_id: str,
        install_mode: str = "global",
        profile: str = "combined",
    ) -> dict[str, Any]:
        return self._invoke(
            "project_init",
            root=str(root.resolve()),
            company_id=company_id,
            install_mode=install_mode,
            profile=profile,
        )

    def bootstrap(
        self,
        root: Path,
        company_id: str,
        profile: str = "combined",
        install_mode: str = "global",
    ) -> dict[str, Any]:
        return self._invoke(
            "bootstrap",
            root=str(root.resolve()),
            company_id=company_id,
            profile=profile,
            install_mode=install_mode,
        )

    def restore(self, root: Path) -> dict[str, Any]:
        return self._invoke("restore", root=str(root.resolve()))

    def doctor(self, root: Path) -> dict[str, Any]:
        return self._invoke("doctor", root=str(root.resolve()))

    def migrate(self, root: Path, dry_run: bool) -> dict[str, Any]:
        function = self.callable("migrate")
        signature = inspect.signature(function)
        if "apply" in signature.parameters and "dry_run" not in signature.parameters:
            return _as_mapping(function(root=str(root.resolve()), apply=not dry_run))
        return self._invoke("migrate", root=str(root.resolve()), dry_run=dry_run)

    def status(self, root: Path) -> dict[str, Any]:
        return self._invoke("status", root=str(root.resolve()))

    def recall(self, root: Path, query: str, **options: Any) -> dict[str, Any]:
        return self._invoke("recall", root=str(root.resolve()), query=query, **options)

    def capture(self, root: Path, **payload: Any) -> dict[str, Any]:
        return self._invoke("capture", root=str(root.resolve()), **payload)


@pytest.fixture
def portable_runtime() -> RuntimeContract:
    return RuntimeContract()


@pytest.fixture
def isolated_localappdata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    local_app_data = tmp_path / "Windows Local App Data"
    local_app_data.mkdir()
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Windows Roaming App Data"))
    for name in (
        "LOCAL_KNOWLEDGE_ALLOWED_ROOTS",
        "CKB_ROOT",
        "CKB_DATA_DIR",
        "CKB_DATABASE",
        "CKB_BUNDLE_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
    yield local_app_data


@pytest.fixture
def portable_world(
    tmp_path: Path,
    isolated_localappdata: Path,
    portable_runtime: RuntimeContract,
) -> dict[str, Path | str]:
    base = tmp_path / "Portable Knowledge Contract"
    company = base / "Company Shared Knowledge"
    project_a = base / "Project Alpha"
    project_b = base / "Project Beta"
    company.mkdir(parents=True)
    project_a.mkdir()
    project_b.mkdir()
    company_id = "contoso-contract"
    portable_runtime.init_company(company, company_id, "Contoso Contract")
    portable_runtime.register_company(company)
    portable_runtime.init_project(project_a, company_id)
    portable_runtime.init_project(project_b, company_id)
    return {
        "base": base,
        "company": company,
        "company_id": company_id,
        "project_a": project_a,
        "project_b": project_b,
        "localappdata": isolated_localappdata,
    }
