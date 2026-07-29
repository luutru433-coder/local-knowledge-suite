#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

"""Create a deterministic license inventory from pnpm's installed virtual store."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


REQUIRED_BUNDLE_IDENTITIES = frozenset(
    {
        "react@19.2.7",
        "react-dom@19.2.7",
        "rollup@4.62.2",
        "scheduler@0.27.0",
        "vite@8.1.5",
    }
)
UNKNOWN_LICENSES = frozenset(
    {
        "",
        "N/A",
        "NONE",
        "NOASSERTION",
        "UNLICENSED",
        "UNKNOWN",
    }
)


class InventoryError(RuntimeError):
    """Raised when installed, locked, and reported dependency evidence diverges."""


@dataclass(frozen=True)
class PackageRecord:
    name: str
    version: str
    license: str
    private: bool = False

    @property
    def identity(self) -> str:
        return f"{self.name.lower()}@{self.version}"

    def as_json(self) -> dict[str, object]:
        return {
            "Name": self.name,
            "Version": self.version,
            "License": self.license,
            "Private": self.private,
        }


def _unquote_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise InventoryError(f"Invalid quoted pnpm lock key: {value}") from exc
        if not isinstance(decoded, str):
            raise InventoryError(f"Non-string pnpm lock key: {value}")
        return decoded
    return value


def identity_from_lock_key(key: str) -> str:
    if key.startswith("@"):
        slash = key.find("/")
        separator = key.find("@", slash + 1) if slash > 1 else -1
    else:
        separator = key.find("@")
    if separator <= 0:
        raise InventoryError(f"Unsupported or malformed pnpm package key: {key}")

    name = key[:separator]
    version_with_peers = key[separator + 1 :]
    version = version_with_peers.split("(", 1)[0]
    if not name or not version or ":" in version:
        raise InventoryError(f"Unsupported or malformed pnpm package key: {key}")
    return f"{name.lower()}@{version}"


def parse_lock_section_keys(lock_path: Path, section: str) -> set[str]:
    try:
        text = lock_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InventoryError(f"Cannot read pnpm lockfile: {lock_path}") from exc

    version_match = re.search(r"(?m)^lockfileVersion:\s*['\"]?([^'\"\s]+)['\"]?\s*$", text)
    if not version_match or version_match.group(1) != "9.0":
        raise InventoryError(f"Unsupported pnpm lockfile version in {lock_path}; expected 9.0.")

    in_section = False
    keys: set[str] = set()
    for line in text.splitlines():
        if not in_section:
            if line == f"{section}:":
                in_section = True
            continue
        if line and not line.startswith(" "):
            break
        if not line.startswith("  ") or line.startswith("   ") or not line.strip():
            continue
        match = re.match(r"^  (.+):(?:\s+\{\})?\s*$", line)
        if not match:
            raise InventoryError(f"Malformed {section} entry in {lock_path}: {line}")
        key = _unquote_yaml_scalar(match.group(1))
        if key in keys:
            raise InventoryError(f"Duplicate {section} key in {lock_path}: {key}")
        identity_from_lock_key(key)
        keys.add(key)

    if not in_section or not keys:
        raise InventoryError(f"{lock_path} has no parseable {section} section.")
    return keys


def parse_lock_identities(lock_path: Path) -> set[str]:
    """Parse Name@Version identities from pnpm-lock v9's packages section."""

    return {
        identity_from_lock_key(key)
        for key in parse_lock_section_keys(lock_path, "packages")
    }


def active_installed_identities(
    installed_lock_path: Path,
    modules_path: Path,
) -> set[str]:
    snapshot_keys = parse_lock_section_keys(installed_lock_path, "snapshots")
    try:
        modules = json.loads(modules_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"Invalid pnpm modules state: {modules_path}") from exc
    if not isinstance(modules, dict):
        raise InventoryError(f"pnpm modules state is not an object: {modules_path}")
    if modules.get("packageManager") != "pnpm@11.9.0":
        raise InventoryError("Installed graph was not produced by pinned pnpm@11.9.0.")

    included = modules.get("included")
    if not isinstance(included, dict) or any(
        included.get(name) is not True
        for name in ("dependencies", "devDependencies", "optionalDependencies")
    ):
        raise InventoryError(
            "Installed graph must include dependencies, devDependencies, and optionalDependencies."
        )

    skipped = modules.get("skipped")
    if not isinstance(skipped, list) or any(not isinstance(item, str) for item in skipped):
        raise InventoryError("pnpm modules state has an invalid skipped package list.")
    if len(set(skipped)) != len(skipped):
        raise InventoryError("pnpm modules state contains duplicate skipped package keys.")
    unknown_skipped = sorted(set(skipped) - snapshot_keys)
    if unknown_skipped:
        raise InventoryError(
            "pnpm modules state skips package(s) absent from the installed lock: "
            + ", ".join(unknown_skipped)
        )

    return {
        identity_from_lock_key(key)
        for key in snapshot_keys - set(skipped)
    }


def _license_expression(package: dict[str, object], identity: str) -> str:
    raw = package.get("license")
    if not isinstance(raw, str):
        raise InventoryError(
            f"Installed non-private package has a missing or non-string license: {identity}"
        )
    expression = raw.strip()
    normalized = expression.upper()
    if normalized in UNKNOWN_LICENSES or normalized.startswith("SEE LICENSE IN "):
        raise InventoryError(
            f"Installed non-private package has a missing or unknown license: {identity}"
        )
    return expression


def _is_within(path: Path, boundary: Path) -> bool:
    try:
        path.relative_to(boundary)
    except ValueError:
        return False
    return True


def _require_confined(path: Path, boundary: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise InventoryError(f"Cannot resolve {label}: {path}") from exc
    if not _is_within(resolved, boundary):
        raise InventoryError(f"{label} escapes the pnpm virtual store: {path} -> {resolved}")
    return resolved


def _candidate_package_roots(
    node_modules_path: Path,
    canonical_virtual_store: Path,
) -> Iterable[Path]:
    _require_confined(node_modules_path, canonical_virtual_store, "virtual node_modules")
    for entry in sorted(node_modules_path.iterdir(), key=lambda item: item.name.lower()):
        if entry.name.startswith(".") or not entry.is_dir():
            continue
        if entry.name.startswith("@"):
            _require_confined(entry, canonical_virtual_store, "scoped package directory")
            for scoped_entry in sorted(entry.iterdir(), key=lambda item: item.name.lower()):
                if scoped_entry.is_dir():
                    yield scoped_entry
            continue
        yield entry


def discover_installed_packages(
    virtual_store: Path,
    active_identities: set[str] | None = None,
) -> dict[str, PackageRecord]:
    """Read every first-level and scoped package under each virtual-store entry."""

    if not virtual_store.is_dir():
        raise InventoryError(f"pnpm virtual store is missing: {virtual_store}")
    canonical_virtual_store = virtual_store.resolve(strict=True)

    records: dict[str, PackageRecord] = {}
    virtual_entries = sorted(virtual_store.iterdir(), key=lambda item: item.name.lower())
    for virtual_entry in virtual_entries:
        node_modules_path = virtual_entry / "node_modules"
        if not node_modules_path.is_dir():
            continue
        for package_root in _candidate_package_roots(
            node_modules_path,
            canonical_virtual_store,
        ):
            _require_confined(package_root, canonical_virtual_store, "installed package root")
            package_json = package_root / "package.json"
            if not package_json.is_file():
                continue
            _require_confined(
                package_json,
                canonical_virtual_store,
                "installed package metadata",
            )
            try:
                package = json.loads(package_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise InventoryError(f"Invalid installed package metadata: {package_json}") from exc
            if not isinstance(package, dict):
                raise InventoryError(f"Installed package metadata is not an object: {package_json}")

            name = package.get("name")
            version = package.get("version")
            private = package.get("private") is True
            if not isinstance(name, str) or not name.strip():
                raise InventoryError(f"Installed package has no name: {package_json}")
            if not isinstance(version, str) or not version.strip():
                raise InventoryError(f"Installed package has no version: {package_json}")
            identity = f"{name.strip().lower()}@{version.strip()}"
            if active_identities is not None and identity not in active_identities:
                continue

            record = PackageRecord(
                name=name.strip(),
                version=version.strip(),
                license=_license_expression(package, identity),
                private=private,
            )
            previous = records.get(identity)
            if previous is not None and previous != record:
                raise InventoryError(
                    f"Installed package metadata conflicts for duplicate identity: {identity}"
                )
            records[identity] = record

    if not records:
        raise InventoryError("No installed third-party packages were found in pnpm's virtual store.")
    return records


def validate_report(
    report: Sequence[PackageRecord],
    installed: dict[str, PackageRecord],
    locked: set[str],
    required: set[str] | frozenset[str] = REQUIRED_BUNDLE_IDENTITIES,
) -> None:
    report_by_identity: dict[str, PackageRecord] = {}
    for record in report:
        if record.identity in report_by_identity:
            raise InventoryError(f"Duplicate report identity: {record.identity}")
        report_by_identity[record.identity] = record

    installed_keys = set(installed)
    report_keys = set(report_by_identity)
    missing = sorted(installed_keys - report_keys)
    if missing:
        raise InventoryError(
            "Node license report is missing installed package(s): " + ", ".join(missing)
        )
    orphaned = sorted(report_keys - installed_keys)
    if orphaned:
        raise InventoryError(
            "Node license report contains orphan package(s): " + ", ".join(orphaned)
        )
    for identity in sorted(installed_keys):
        if report_by_identity[identity] != installed[identity]:
            raise InventoryError(f"Node license report metadata differs from installed: {identity}")

    unlocked = sorted(report_keys - locked)
    if unlocked:
        raise InventoryError(
            "Installed Node package(s) are not present in pnpm-lock.yaml: "
            + ", ".join(unlocked)
        )
    required_missing = sorted(set(required) - report_keys)
    if required_missing:
        raise InventoryError(
            "Shipped portal bundle dependency is missing from the installed inventory: "
            + ", ".join(required_missing)
        )


def validate_installed_coverage(
    installed: dict[str, PackageRecord],
    expected_active: set[str],
) -> None:
    missing = sorted(expected_active - set(installed))
    if missing:
        raise InventoryError(
            "Active installed Node package metadata is missing: " + ", ".join(missing)
        )
    unexpected = sorted(set(installed) - expected_active)
    if unexpected:
        raise InventoryError(
            "Inactive Node package entered the installed inventory: "
            + ", ".join(unexpected)
        )


def create_inventory(repository_root: Path) -> list[PackageRecord]:
    repository_root = repository_root.resolve()
    virtual_store = repository_root / "node_modules" / ".pnpm"
    repository_lock_path = repository_root / "pnpm-lock.yaml"
    installed_lock_path = virtual_store / "lock.yaml"
    locked_package_keys = parse_lock_section_keys(repository_lock_path, "packages")
    installed_package_keys = parse_lock_section_keys(installed_lock_path, "packages")
    locked_snapshot_keys = parse_lock_section_keys(repository_lock_path, "snapshots")
    installed_snapshot_keys = parse_lock_section_keys(installed_lock_path, "snapshots")
    if (
        installed_package_keys != locked_package_keys
        or installed_snapshot_keys != locked_snapshot_keys
    ):
        missing = sorted(locked_package_keys - installed_package_keys)
        orphaned = sorted(installed_package_keys - locked_package_keys)
        details: list[str] = []
        if missing:
            details.append("package keys missing from installed lock: " + ", ".join(missing))
        if orphaned:
            details.append("package keys absent from repository lock: " + ", ".join(orphaned))
        if installed_snapshot_keys != locked_snapshot_keys:
            details.append("snapshot key sets differ")
        raise InventoryError(
            "Installed pnpm lock does not exactly match pnpm-lock.yaml ("
            + "; ".join(details)
            + "). Run pnpm install --frozen-lockfile."
        )
    locked = {
        identity_from_lock_key(key)
        for key in locked_package_keys
    }
    snapshot_identities = {
        identity_from_lock_key(key)
        for key in locked_snapshot_keys
    }
    if snapshot_identities != locked:
        raise InventoryError(
            "pnpm package and snapshot identity sets do not match exactly."
        )
    active = active_installed_identities(
        installed_lock_path,
        repository_root / "node_modules" / ".modules.yaml",
    )
    if not active.issubset(locked):
        raise InventoryError(
            "Installed active snapshot identities are not covered by pnpm package locks."
        )
    installed = discover_installed_packages(
        virtual_store,
        active_identities=active,
    )
    validate_installed_coverage(installed, active)
    report = sorted(
        installed.values(),
        key=lambda item: (item.name.lower(), item.version, item.license),
    )
    validate_report(report, installed, locked)
    return report


def serialize_report(report: Sequence[PackageRecord]) -> str:
    deterministic = sorted(
        report,
        key=lambda item: (item.name.lower(), item.version, item.license, item.private),
    )
    return (
        json.dumps(
            [record.as_json() for record in deterministic],
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        report = create_inventory(args.repository_root)
    except InventoryError as exc:
        parser.error(str(exc))

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(serialize_report(report), encoding="utf-8", newline="\n")
    print(f"Created deterministic Node license inventory: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
