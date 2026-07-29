# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

"""Deterministic, text-only project-memory export and import."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .errors import SnapshotError
from .memorizer import core as memory_core
from .winio import reject_reparse_points, reject_reparse_traversal
from .workspace import WorkspaceContext, require_current_workspace_schema


SNAPSHOT_SCHEMA_VERSION = 1
SNAPSHOT_FORMAT = "local-knowledge-memory-snapshot"
DEFAULT_SNAPSHOT_PATH = Path(".local-knowledge/memory-snapshot")
SNAPSHOT_MANIFEST = "snapshot.json"
_CONFIG_PATH = "memory/config.json"
_NOTE_PREFIX = PurePosixPath("memory/notes")
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")
_PROJECT_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_KEYS = {
    "schema_version",
    "format",
    "project_id",
    "includes_sensitive",
    "excluded_sensitive_count",
    "item_count",
    "source_updated_at",
    "content_fingerprint",
    "files",
}
_FILE_ENTRY_KEYS = {"path", "sha256", "bytes"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _json_object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SnapshotError(f"snapshot JSON repeats field {key!r}")
        value[key] = item
    return value


def _resolve_snapshot_path(project_root: Path, raw_path: str | Path) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    return candidate.resolve()


def _resolve_snapshot_input_path(
    project_root: Path,
    raw_path: str | Path,
) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = project_root / candidate
    lexical = Path(os.path.abspath(candidate))
    try:
        reject_reparse_points(lexical, "memory snapshot")
    except ValueError as exc:
        raise SnapshotError(str(exc)) from exc
    return lexical.resolve()


def _safe_snapshot_relative(raw_path: object) -> PurePosixPath:
    if not isinstance(raw_path, str):
        raise SnapshotError("snapshot file paths must be strings")
    path = PurePosixPath(raw_path)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} or "\\" in part or ":" in part for part in path.parts)
    ):
        raise SnapshotError(f"unsafe snapshot file path: {raw_path!r}")
    if path.as_posix() == _CONFIG_PATH:
        return path
    if (
        len(path.parts) == 3
        and PurePosixPath(*path.parts[:2]) == _NOTE_PREFIX
        and path.suffix.casefold() == ".md"
    ):
        return path
    raise SnapshotError(
        f"snapshot contains unsupported source path {raw_path!r}; "
        "only memory/config.json and memory/notes/*.md are allowed"
    )


def _canonical_config(vault: Path) -> bytes:
    config = memory_core.load_config(vault)
    return _json_bytes(config)


def _sanitize_note(
    note: memory_core.Note,
    excluded_ids: set[str],
    excluded_titles: set[str],
) -> memory_core.Note:
    def replace_link(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        if target in excluded_ids or target.casefold() in excluded_titles:
            return (match.group(2) or target).strip()
        return match.group(0)

    relations = [
        relation
        for relation in note.relations
        if relation.get("target_kind", "note") != "note"
        or relation.get("target") not in excluded_ids
    ]
    supersedes = [target for target in note.supersedes if target not in excluded_ids]
    superseded_by = (
        None if note.superseded_by in excluded_ids else note.superseded_by
    )
    status = (
        "active"
        if note.status == "superseded" and note.superseded_by in excluded_ids
        else note.status
    )
    return dataclasses.replace(
        note,
        body=_WIKILINK.sub(replace_link, note.body),
        relations=relations,
        supersedes=supersedes,
        superseded_by=superseded_by,
        status=status,
        source_event_ids=[],
        path=None,
    )


def _snapshot_sources(
    context: WorkspaceContext,
    include_sensitive: bool,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    if not context.memory_enabled:
        raise SnapshotError("memory is disabled by this project's profile")
    if not context.memory_root.is_dir():
        raise SnapshotError("memory vault is not initialized")
    validation = memory_core.validate_vault(context.project_root)
    if not validation.get("valid"):
        raise SnapshotError(
            "memory vault must validate before export: "
            + "; ".join(str(item) for item in validation.get("errors", []))
        )
    notes = memory_core.load_notes(context.memory_root)
    sensitive = {identifier for identifier, note in notes.items() if note.privacy == "sensitive"}
    selected = {
        identifier: note
        for identifier, note in notes.items()
        if include_sensitive or identifier not in sensitive
    }
    excluded_titles = {
        notes[identifier].title.casefold() for identifier in sensitive if identifier not in selected
    }
    files: dict[str, bytes] = {_CONFIG_PATH: _canonical_config(context.memory_root)}
    for identifier, note in sorted(selected.items()):
        assert note.path is not None
        relative = (_NOTE_PREFIX / note.path.name).as_posix()
        files[relative] = memory_core.note_to_markdown(
            _sanitize_note(
                note,
                set() if include_sensitive else sensitive,
                set() if include_sensitive else excluded_titles,
            )
        ).encode("utf-8")
    updated_values = [note.updated_at for note in selected.values()]
    metadata = {
        "includes_sensitive": any(
            note.privacy == "sensitive" for note in selected.values()
        ),
        "excluded_sensitive_count": len(sensitive - set(selected)),
        "item_count": len(selected),
        "source_updated_at": max(updated_values) if updated_values else None,
    }
    return files, metadata


def _manifest_payload(
    project_id: str,
    files: dict[str, bytes],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    entries = [
        {"path": path, "sha256": _sha256(data), "bytes": len(data)}
        for path, data in sorted(files.items())
    ]
    unsigned = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "format": SNAPSHOT_FORMAT,
        "project_id": project_id,
        "includes_sensitive": metadata["includes_sensitive"],
        "excluded_sensitive_count": metadata["excluded_sensitive_count"],
        "item_count": metadata["item_count"],
        "source_updated_at": metadata["source_updated_at"],
        "files": entries,
    }
    return {
        **unsigned,
        "content_fingerprint": _sha256(_json_bytes(unsigned)),
    }


def _strict_manifest_metadata(manifest: dict[str, Any]) -> dict[str, Any]:
    includes_sensitive = manifest["includes_sensitive"]
    if type(includes_sensitive) is not bool:
        raise SnapshotError("snapshot includes_sensitive must be a boolean")
    counts: dict[str, int] = {}
    for field in ("excluded_sensitive_count", "item_count"):
        value = manifest[field]
        if type(value) is not int or value < 0:
            raise SnapshotError(
                f"snapshot {field} must be a non-negative integer"
            )
        counts[field] = value
    source_updated_at = manifest["source_updated_at"]
    if source_updated_at is not None:
        if not isinstance(source_updated_at, str) or not source_updated_at:
            raise SnapshotError(
                "snapshot source_updated_at must be a non-empty ISO-8601 string or null"
            )
        try:
            memory_core.parse_time(source_updated_at)
        except memory_core.MemorizerError as exc:
            raise SnapshotError(
                "snapshot source_updated_at must be a valid ISO-8601 timestamp"
            ) from exc
    if includes_sensitive and counts["excluded_sensitive_count"] != 0:
        raise SnapshotError(
            "snapshot cannot both include sensitive notes and report excluded sensitive notes"
        )
    return {
        "includes_sensitive": includes_sensitive,
        **counts,
        "source_updated_at": source_updated_at,
    }


def export_memory_snapshot(
    root: str,
    output: str,
    *,
    git_visibility: str = "private",
    include_sensitive: bool = False,
    acknowledge_sensitive: bool = False,
    allow_public: bool = False,
) -> dict[str, Any]:
    context = WorkspaceContext.resolve(root)
    if git_visibility not in {"private", "public"}:
        raise SnapshotError("git_visibility must be private or public")
    if include_sensitive and not acknowledge_sensitive:
        raise SnapshotError(
            "--include-sensitive requires --acknowledge-sensitive because the snapshot is plaintext"
        )
    if acknowledge_sensitive and not include_sensitive:
        raise SnapshotError(
            "--acknowledge-sensitive is only valid with --include-sensitive"
        )
    if git_visibility == "public" and not allow_public:
        raise SnapshotError(
            "public Git export requires --allow-public after reviewing the plaintext snapshot"
        )
    destination = _resolve_snapshot_path(context.project_root, output)
    try:
        if os.path.commonpath(
            (os.path.normcase(str(context.memory_root)), os.path.normcase(str(destination)))
        ) == os.path.normcase(str(context.memory_root)):
            raise SnapshotError("snapshot output cannot be inside the .memorizer vault")
    except ValueError as exc:
        raise SnapshotError("snapshot output is on an incompatible filesystem") from exc
    if destination.exists():
        raise SnapshotError(f"snapshot output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    reject_reparse_points(destination.parent, "snapshot output parent")
    files, metadata = _snapshot_sources(context, include_sensitive)
    manifest = _manifest_payload(context.project.project_id, files, metadata)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    try:
        for relative, data in sorted(files.items()):
            target = staging / Path(*PurePosixPath(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (staging / SNAPSHOT_MANIFEST).write_bytes(_json_bytes(manifest))
        os.replace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {
        "ok": True,
        "root": str(context.project_root),
        "project_id": context.project.project_id,
        "snapshot": str(destination),
        "git_visibility": git_visibility,
        **metadata,
        "content_fingerprint": manifest["content_fingerprint"],
        "files": manifest["files"],
    }


def inspect_memory_snapshot(
    snapshot: str | Path,
    *,
    expected_project_id: str | None = None,
) -> dict[str, Any]:
    lexical = Path(os.path.abspath(Path(snapshot).expanduser()))
    root = lexical.resolve()
    result: dict[str, Any] = {
        "present": root.is_dir(),
        "path": str(root),
        "valid": False,
        "project_id_matches": None,
        "freshness": "unknown",
    }
    if not root.is_dir():
        return result
    try:
        reject_reparse_points(lexical, "memory snapshot")
        reject_reparse_points(root, "memory snapshot")
        manifest_path = root / SNAPSHOT_MANIFEST
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8"),
            object_pairs_hook=_json_object_without_duplicates,
        )
        if not isinstance(manifest, dict):
            raise SnapshotError("snapshot manifest must be a JSON object")
        missing_fields = _MANIFEST_KEYS - set(manifest)
        extra_fields = set(manifest) - _MANIFEST_KEYS
        if missing_fields or extra_fields:
            raise SnapshotError(
                "snapshot manifest fields are not canonical: "
                f"missing={sorted(missing_fields)}, extra={sorted(extra_fields)}"
            )
        if (
            type(manifest["schema_version"]) is not int
            or manifest["schema_version"] != SNAPSHOT_SCHEMA_VERSION
        ):
            raise SnapshotError(
                f"unsupported snapshot schema: {manifest['schema_version']!r}"
            )
        if (
            not isinstance(manifest["format"], str)
            or manifest["format"] != SNAPSHOT_FORMAT
        ):
            raise SnapshotError(f"unsupported snapshot format: {manifest['format']!r}")
        project_id = manifest["project_id"]
        if not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id):
            raise SnapshotError("snapshot project_id is missing or non-canonical")
        metadata = _strict_manifest_metadata(manifest)
        fingerprint = manifest["content_fingerprint"]
        if not isinstance(fingerprint, str) or not _SHA256.fullmatch(fingerprint):
            raise SnapshotError(
                "snapshot content_fingerprint must be a lowercase SHA-256 digest"
            )
        raw_files = manifest["files"]
        if not isinstance(raw_files, list) or not raw_files:
            raise SnapshotError("snapshot files list is missing or empty")
        declared: set[str] = set()
        entries: list[dict[str, Any]] = []
        for raw_entry in raw_files:
            if not isinstance(raw_entry, dict):
                raise SnapshotError("snapshot file entry must be an object")
            if set(raw_entry) != _FILE_ENTRY_KEYS:
                raise SnapshotError(
                    "snapshot file entry fields are not canonical: "
                    f"{sorted(raw_entry)}"
                )
            relative = _safe_snapshot_relative(raw_entry.get("path"))
            relative_text = relative.as_posix()
            if relative_text in declared:
                raise SnapshotError(f"duplicate snapshot file entry: {relative_text}")
            declared.add(relative_text)
            declared_digest = raw_entry["sha256"]
            declared_bytes = raw_entry["bytes"]
            if (
                not isinstance(declared_digest, str)
                or not _SHA256.fullmatch(declared_digest)
            ):
                raise SnapshotError(
                    f"snapshot sha256 is invalid: {relative_text}"
                )
            if type(declared_bytes) is not int or declared_bytes < 0:
                raise SnapshotError(
                    f"snapshot byte count is invalid: {relative_text}"
                )
            target = root / Path(*relative.parts)
            if not target.is_file():
                raise SnapshotError(f"snapshot source file is missing: {relative_text}")
            data = target.read_bytes()
            digest = _sha256(data)
            if declared_digest != digest or declared_bytes != len(data):
                raise SnapshotError(f"snapshot checksum mismatch: {relative_text}")
            entries.append(
                {"path": relative_text, "sha256": digest, "bytes": len(data)}
            )
        if entries != sorted(entries, key=lambda entry: entry["path"]):
            raise SnapshotError("snapshot file entries are not in canonical path order")
        if _CONFIG_PATH not in declared:
            raise SnapshotError("snapshot must contain memory/config.json")
        actual = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.name != SNAPSHOT_MANIFEST
        }
        if actual != declared:
            raise SnapshotError(
                "snapshot has undeclared or missing files: "
                f"extra={sorted(actual - declared)}, missing={sorted(declared - actual)}"
            )
        expected_manifest = _manifest_payload(
            project_id,
            {
                entry["path"]: (
                    root / Path(*PurePosixPath(entry["path"]).parts)
                ).read_bytes()
                for entry in entries
            },
            metadata,
        )
        if fingerprint != expected_manifest["content_fingerprint"]:
            raise SnapshotError("snapshot content fingerprint mismatch")
        note_entries = [
            entry
            for entry in entries
            if entry["path"].startswith("memory/notes/")
        ]
        if metadata["item_count"] != len(note_entries):
            raise SnapshotError("snapshot item_count does not match its note files")
        notes: list[memory_core.Note] = []
        try:
            notes = [
                memory_core.parse_note(
                    root / Path(*PurePosixPath(entry["path"]).parts)
                )
                for entry in note_entries
            ]
        except memory_core.MemorizerError as exc:
            raise SnapshotError(f"snapshot note is invalid: {exc}") from exc
        if len({note.id for note in notes}) != len(notes):
            raise SnapshotError("snapshot contains duplicate memory note IDs")
        actual_includes_sensitive = any(
            note.privacy == "sensitive" for note in notes
        )
        if metadata["includes_sensitive"] != actual_includes_sensitive:
            raise SnapshotError(
                "snapshot includes_sensitive does not match its parsed notes"
            )
        actual_updated_at = (
            max(note.updated_at for note in notes) if notes else None
        )
        if metadata["source_updated_at"] != actual_updated_at:
            raise SnapshotError(
                "snapshot source_updated_at does not match its parsed notes"
            )
        matches = expected_project_id is None or project_id == expected_project_id
        result.update(
            {
                "valid": True,
                "project_id": project_id,
                "project_id_matches": matches,
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "content_fingerprint": fingerprint,
                **metadata,
                "files": entries,
            }
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SnapshotError, ValueError) as exc:
        result["error"] = str(exc)
    return result


def memory_snapshot_status(context: WorkspaceContext) -> dict[str, Any]:
    path = context.project_root / DEFAULT_SNAPSHOT_PATH
    status = inspect_memory_snapshot(
        path,
        expected_project_id=context.project.project_id,
    )
    if not status.get("valid") or not status.get("project_id_matches"):
        return status
    try:
        files, metadata = _snapshot_sources(
            context,
            bool(status.get("includes_sensitive", False)),
        )
        current = _manifest_payload(context.project.project_id, files, metadata)
        status["freshness"] = (
            "current"
            if current["content_fingerprint"] == status["content_fingerprint"]
            else "stale"
        )
    except Exception as exc:
        status["freshness"] = "unknown"
        status["freshness_error"] = str(exc)
    return status


def _vault_has_source(vault: Path) -> bool:
    return any((vault / "notes").glob("*.md")) or any(
        (vault / "daily").glob("*.md")
    )


def _verified_snapshot_entry_bytes(
    snapshot_root: Path,
    entry: dict[str, Any],
) -> tuple[PurePosixPath, bytes]:
    relative = _safe_snapshot_relative(entry.get("path"))
    source = snapshot_root / Path(*relative.parts)
    try:
        reject_reparse_traversal(
            snapshot_root,
            source,
            f"snapshot source {relative.as_posix()}",
        )
    except ValueError as exc:
        raise SnapshotError(str(exc)) from exc
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise SnapshotError(
            f"cannot read snapshot source file {relative.as_posix()}: {exc}"
        ) from exc
    if (
        type(entry.get("bytes")) is not int
        or entry.get("bytes") != len(data)
        or not isinstance(entry.get("sha256"), str)
        or entry.get("sha256") != _sha256(data)
    ):
        raise SnapshotError(
            f"snapshot changed while being imported: {relative.as_posix()}"
        )
    return relative, data


def _require_matching_staged_snapshot(
    original: dict[str, Any],
    staged: dict[str, Any],
) -> None:
    if not staged.get("valid"):
        raise SnapshotError(
            "staged memory snapshot is invalid: "
            f"{staged.get('error', 'validation failed')}"
        )
    if not staged.get("project_id_matches"):
        raise SnapshotError(
            "staged snapshot project_id does not match this workspace"
        )
    for field in ("project_id", "content_fingerprint", "files"):
        if staged.get(field) != original.get(field):
            raise SnapshotError(
                f"snapshot changed while being imported: {field} mismatch"
            )


def _copy_verified_snapshot(
    snapshot_root: Path,
    project_root: Path,
    inspected: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """Copy an untrusted snapshot into controlled staging, then verify that copy."""

    local_root = project_root / ".local-knowledge"
    local_root.mkdir(parents=True, exist_ok=True)
    try:
        reject_reparse_traversal(
            project_root,
            local_root,
            "memory snapshot staging directory",
        )
        reject_reparse_points(snapshot_root, "memory snapshot")
    except ValueError as exc:
        raise SnapshotError(str(exc)) from exc
    staged_snapshot = Path(
        tempfile.mkdtemp(prefix=".snapshot-import.", dir=local_root)
    )
    try:
        manifest_source = snapshot_root / SNAPSHOT_MANIFEST
        try:
            reject_reparse_traversal(
                snapshot_root,
                manifest_source,
                "snapshot manifest",
            )
        except ValueError as exc:
            raise SnapshotError(str(exc)) from exc
        (staged_snapshot / SNAPSHOT_MANIFEST).write_bytes(
            manifest_source.read_bytes()
        )
        for entry in list(inspected["files"]):
            relative, data = _verified_snapshot_entry_bytes(snapshot_root, entry)
            target = staged_snapshot / Path(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        try:
            reject_reparse_points(snapshot_root, "memory snapshot")
            reject_reparse_points(staged_snapshot, "staged memory snapshot")
        except ValueError as exc:
            raise SnapshotError(str(exc)) from exc
        staged_inspection = inspect_memory_snapshot(
            staged_snapshot,
            expected_project_id=str(inspected["project_id"]),
        )
        _require_matching_staged_snapshot(inspected, staged_inspection)
        return staged_snapshot, staged_inspection
    except Exception:
        shutil.rmtree(staged_snapshot, ignore_errors=True)
        raise


def _stage_snapshot(snapshot_root: Path, project_root: Path, files: list[dict[str, Any]]) -> Path:
    local_root = project_root / ".local-knowledge"
    local_root.mkdir(parents=True, exist_ok=True)
    staging_project = Path(
        tempfile.mkdtemp(prefix=".memory-import.", dir=local_root)
    )
    try:
        staging_vault = staging_project / ".memorizer"
        (staging_vault / "notes").mkdir(parents=True)
        (staging_vault / "daily").mkdir()
        (staging_vault / "entities").mkdir()
        for entry in files:
            relative, data = _verified_snapshot_entry_bytes(snapshot_root, entry)
            if relative.as_posix() == _CONFIG_PATH:
                target = staging_vault / "config.json"
            else:
                target = staging_vault / "notes" / relative.name
            target.write_bytes(data)
        memory_core.init_vault(staging_project)
        validation = memory_core.validate_vault(staging_project)
        if not validation.get("valid"):
            raise SnapshotError(
                "imported memory did not validate: "
                + "; ".join(str(item) for item in validation.get("errors", []))
            )
        return staging_project
    except Exception:
        shutil.rmtree(staging_project, ignore_errors=True)
        raise


def import_memory_snapshot(
    root: str,
    input_path: str,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    context = WorkspaceContext.resolve(root)
    require_current_workspace_schema(context, "memory snapshot import")
    if not context.memory_enabled:
        raise SnapshotError("memory is disabled by this project's profile")
    snapshot_root = _resolve_snapshot_input_path(context.project_root, input_path)
    inspected = inspect_memory_snapshot(
        snapshot_root,
        expected_project_id=context.project.project_id,
    )
    if not inspected.get("valid"):
        raise SnapshotError(
            f"memory snapshot is invalid: {inspected.get('error', 'validation failed')}"
        )
    if not inspected.get("project_id_matches"):
        raise SnapshotError(
            "snapshot project_id does not match this workspace; cross-project import is forbidden"
        )
    vault = context.memory_root
    reject_reparse_points(vault, "project memory store")
    has_source = vault.is_dir() and _vault_has_source(vault)
    if has_source and not replace:
        raise SnapshotError(
            "memory vault is not empty; rerun with --replace to create a local backup first"
        )
    staged_snapshot: Path | None = None
    staging_project: Path | None = None
    previous: Path | None = None
    backup: Path | None = None
    moved_existing = False
    installed = False
    try:
        staged_snapshot, staged_inspection = _copy_verified_snapshot(
            snapshot_root,
            context.project_root,
            inspected,
        )
        inspected = staged_inspection
        staging_project = _stage_snapshot(
            staged_snapshot,
            context.project_root,
            list(inspected["files"]),
        )
        staging_vault = staging_project / ".memorizer"
        final_snapshot_check = inspect_memory_snapshot(
            staged_snapshot,
            expected_project_id=context.project.project_id,
        )
        _require_matching_staged_snapshot(inspected, final_snapshot_check)
        staged_validation = memory_core.validate_vault(staging_project)
        if not staged_validation.get("valid"):
            raise SnapshotError(
                "staged memory snapshot failed final validation: "
                + "; ".join(
                    str(item) for item in staged_validation.get("errors", [])
                )
            )
        if vault.exists():
            if has_source and replace:
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
                backup = (
                    context.project_root
                    / ".local-knowledge"
                    / "backups"
                    / f"{stamp}-memory-import"
                    / "memorizer"
                )
                backup.parent.mkdir(parents=True, exist_ok=False)
                os.replace(vault, backup)
                previous = backup
            else:
                previous = (
                    context.project_root
                    / ".local-knowledge"
                    / f".memory-before-import-{os.getpid()}"
                )
                if previous.exists():
                    raise SnapshotError(f"temporary import path already exists: {previous}")
                os.replace(vault, previous)
            moved_existing = True
        os.replace(staging_vault, vault)
        installed = True
        validation = memory_core.validate_vault(context.project_root)
        if not validation.get("valid"):
            raise SnapshotError(
                "installed memory snapshot failed validation: "
                + "; ".join(str(item) for item in validation.get("errors", []))
            )
        if moved_existing and backup is None and previous is not None:
            shutil.rmtree(previous)
            previous = None
    except Exception:
        if moved_existing and previous is not None and previous.exists():
            if vault.exists():
                failed = vault.with_name(f".memorizer.failed-import-{os.getpid()}")
                os.replace(vault, failed)
                shutil.rmtree(failed)
            os.replace(previous, vault)
        elif installed and vault.exists():
            failed = vault.with_name(f".memorizer.failed-import-{os.getpid()}")
            os.replace(vault, failed)
            shutil.rmtree(failed)
        raise
    finally:
        if staging_project is not None and staging_project.exists():
            shutil.rmtree(staging_project)
        if staged_snapshot is not None and staged_snapshot.exists():
            shutil.rmtree(staged_snapshot)
    return {
        "ok": True,
        "root": str(context.project_root),
        "project_id": context.project.project_id,
        "snapshot": str(snapshot_root),
        "imported": inspected["item_count"],
        "includes_sensitive": inspected["includes_sensitive"],
        "content_fingerprint": inspected["content_fingerprint"],
        "backup": str(backup.parent) if backup is not None else None,
        "validation": validation,
    }
