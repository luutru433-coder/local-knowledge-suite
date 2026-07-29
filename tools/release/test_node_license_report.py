#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

"""Adversarial self-test for the deterministic pnpm license inventory."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from node_license_report import (
    InventoryError,
    PackageRecord,
    REQUIRED_BUNDLE_IDENTITIES,
    _require_confined,
    active_installed_identities,
    discover_installed_packages,
    parse_lock_identities,
    parse_lock_section_keys,
    serialize_report,
    validate_installed_coverage,
    validate_report,
)


def _write_package(
    store: Path,
    entry: str,
    name: str,
    version: str,
    license_expression: object,
    *,
    private: bool = False,
) -> None:
    package_root = store / entry / "node_modules"
    for part in name.split("/"):
        package_root /= part
    package_root.mkdir(parents=True, exist_ok=True)
    (package_root / "package.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": version,
                "license": license_expression,
                "private": private,
            }
        ),
        encoding="utf-8",
    )


def _expect_rejected(action, expected: str) -> None:
    try:
        action()
    except InventoryError as exc:
        if expected not in str(exc):
            raise AssertionError(f"Rejected for the wrong reason: {exc}") from exc
        return
    raise AssertionError(f"Inventory accepted a forbidden fixture: {expected}")


def _lock_line(key: str, *, inline: bool = False) -> str:
    quoted = f"'{key}'" if key.startswith("@") else key
    return f"  {quoted}: {{}}" if inline else f"  {quoted}:"


def _write_lock(path: Path, package_keys: list[str], snapshot_keys: list[str]) -> None:
    path.write_text(
        "\n".join(
            [
                "lockfileVersion: '9.0'",
                "",
                "packages:",
                *[
                    _lock_line(key, inline=index == 0)
                    for index, key in enumerate(package_keys)
                ],
                "",
                "snapshots:",
                *[
                    _lock_line(key, inline=index == 0)
                    for index, key in enumerate(snapshot_keys)
                ],
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_modules(
    path: Path,
    skipped: list[str],
    *,
    package_manager: str = "pnpm@11.9.0",
    included_overrides: dict[str, bool] | None = None,
) -> None:
    included = {
        "dependencies": True,
        "devDependencies": True,
        "optionalDependencies": True,
    }
    if included_overrides:
        included.update(included_overrides)
    path.write_text(
        json.dumps(
            {
                "packageManager": package_manager,
                "included": included,
                "skipped": skipped,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lks-node-license-selftest-") as temporary:
        root = Path(temporary)
        store = root / "node_modules" / ".pnpm"
        packages = [
            ("react-entry", "react", "19.2.7", "MIT"),
            ("react-dom-entry", "react-dom", "19.2.7", "MIT"),
            ("rollup-entry", "rollup", "4.62.2", "MIT"),
            ("scheduler-entry", "scheduler", "0.27.0", "MIT"),
            ("vite-entry", "vite", "8.1.5", "MIT"),
            ("transitive-entry", "@example/transitive", "2.3.4", "Apache-2.0"),
            ("optional-entry", "@example/optional", "3.0.0", "MIT"),
            ("contextual-entry", "contextual", "1.0.0", "BSD-3-Clause"),
        ]
        for entry, name, version, license_expression in packages:
            _write_package(store, entry, name, version, license_expression)

        package_keys = [f"{name}@{version}" for _, name, version, _ in packages]
        package_keys = [
            key for key in package_keys if not key.startswith("contextual@")
        ] + ["contextual@1.0.0"]
        base_snapshot_keys = [
            f"{name}@{version}"
            for _, name, version, _ in packages
            if name != "contextual"
        ]
        contextual_one = "contextual@1.0.0(peer@1.0.0)"
        contextual_two = "contextual@1.0.0(peer@2.0.0)"
        snapshot_keys = [*base_snapshot_keys, contextual_one, contextual_two]
        lock_path = root / "pnpm-lock.yaml"
        _write_lock(lock_path, package_keys, snapshot_keys)
        modules_path = root / "node_modules" / ".modules.yaml"
        skipped = ["@example/optional@3.0.0", contextual_one]
        _write_modules(modules_path, skipped)

        active = active_installed_identities(lock_path, modules_path)
        if "@example/optional@3.0.0" in active or "contextual@1.0.0" not in active:
            raise AssertionError("Skipped peer-context reduction produced the wrong active set.")
        installed = discover_installed_packages(store, active_identities=active)
        validate_installed_coverage(installed, active)
        locked = parse_lock_identities(lock_path)
        report = sorted(installed.values(), key=lambda item: item.identity)
        validate_report(report, installed, locked)
        if not REQUIRED_BUNDLE_IDENTITIES.issubset(installed):
            raise AssertionError("Valid fixture omitted a required portal-bundle identity.")

        _write_modules(modules_path, [*skipped, contextual_two])
        all_contexts_skipped = active_installed_identities(lock_path, modules_path)
        if "contextual@1.0.0" in all_contexts_skipped:
            raise AssertionError("An identity with every peer context skipped remained active.")
        _write_modules(modules_path, skipped)
        _write_modules(root / "bad-modules.json", ["ghost@1.0.0"])
        _expect_rejected(
            lambda: active_installed_identities(
                lock_path,
                root / "bad-modules.json",
            ),
            "absent from the installed lock",
        )
        _write_modules(
            root / "bad-manager.json",
            skipped,
            package_manager="pnpm@11.8.0",
        )
        _expect_rejected(
            lambda: active_installed_identities(lock_path, root / "bad-manager.json"),
            "pinned pnpm@11.9.0",
        )
        _write_modules(
            root / "bad-included.json",
            skipped,
            included_overrides={"optionalDependencies": False},
        )
        _expect_rejected(
            lambda: active_installed_identities(lock_path, root / "bad-included.json"),
            "must include dependencies",
        )
        _write_modules(root / "duplicate-skipped.json", [skipped[0], skipped[0]])
        _expect_rejected(
            lambda: active_installed_identities(
                lock_path,
                root / "duplicate-skipped.json",
            ),
            "duplicate skipped",
        )

        transitive = "@example/transitive@2.3.4"
        missing_transitive = [
            record for record in report if record.identity != transitive
        ]
        _expect_rejected(
            lambda: validate_report(missing_transitive, installed, locked),
            "missing installed package",
        )

        orphan = PackageRecord("orphan", "9.9.9", "MIT")
        _expect_rejected(
            lambda: validate_report([*report, orphan], installed, locked),
            "orphan package",
        )

        installed_with_unlocked = dict(installed)
        installed_with_unlocked[orphan.identity] = orphan
        _expect_rejected(
            lambda: validate_report([*report, orphan], installed_with_unlocked, locked),
            "not present in pnpm-lock.yaml",
        )

        _expect_rejected(
            lambda: validate_installed_coverage(
                installed,
                {*active, "missing-active@1.0.0"},
            ),
            "metadata is missing",
        )
        _expect_rejected(
            lambda: validate_report(
                report,
                installed,
                locked,
                required={*REQUIRED_BUNDLE_IDENTITIES, "required-missing@1.0.0"},
            ),
            "bundle dependency is missing",
        )

        _write_package(store, "stale-entry", "stale-unlocked", "8.8.8", "UNKNOWN")
        active_installed = discover_installed_packages(store, active_identities=active)
        if "stale-unlocked@8.8.8" in active_installed:
            raise AssertionError("Stale virtual-store package entered the active inventory.")

        unknown_store = root / "unknown" / ".pnpm"
        _write_package(unknown_store, "bad-entry", "bad-license", "1.0.0", "UNKNOWN")
        _expect_rejected(
            lambda: discover_installed_packages(unknown_store),
            "missing or unknown license",
        )
        non_string_store = root / "non-string" / ".pnpm"
        _write_package(
            non_string_store,
            "bad-entry",
            "non-string-license",
            "1.0.0",
            ["MIT", "Apache-2.0"],
        )
        _expect_rejected(
            lambda: discover_installed_packages(non_string_store),
            "non-string license",
        )

        private_store = root / "private" / ".pnpm"
        _write_package(
            private_store,
            "private-entry",
            "private-registry-package",
            "1.0.0",
            "UNKNOWN",
            private=True,
        )
        _expect_rejected(
            lambda: discover_installed_packages(
                private_store,
                active_identities={"private-registry-package@1.0.0"},
            ),
            "missing or unknown license",
        )

        conflict_store = root / "conflict" / ".pnpm"
        _write_package(conflict_store, "one", "conflict", "1.0.0", "MIT")
        _write_package(conflict_store, "two", "conflict", "1.0.0", "Apache-2.0")
        _expect_rejected(
            lambda: discover_installed_packages(
                conflict_store,
                active_identities={"conflict@1.0.0"},
            ),
            "metadata conflicts",
        )

        boundary = store.resolve()
        external = root / "external-package"
        _write_package(
            root / "external-store",
            "external-entry",
            "external",
            "1.0.0",
            "MIT",
        )
        external = (
            root
            / "external-store"
            / "external-entry"
            / "node_modules"
            / "external"
        )
        link_root = store / "escape-entry" / "node_modules"
        link_root.mkdir(parents=True, exist_ok=True)
        link_path = link_root / "external"
        try:
            os.symlink(external, link_path, target_is_directory=True)
        except OSError:
            _expect_rejected(
                lambda: _require_confined(external.resolve(), boundary, "test package"),
                "escapes the pnpm virtual store",
            )
        else:
            _expect_rejected(
                lambda: discover_installed_packages(
                    store,
                    active_identities={*locked, "external@1.0.0"},
                ),
                "escapes the pnpm virtual store",
            )

        first_bytes = serialize_report(report).encode("utf-8")
        for package_json in store.rglob("package.json"):
            os.utime(package_json, (1_700_000_000, 1_700_000_000))
        second_bytes = serialize_report(list(reversed(report))).encode("utf-8")
        if first_bytes != second_bytes:
            raise AssertionError("Node inventory serialization is not deterministic.")

        bad_version_lock = root / "bad-version-lock.yaml"
        bad_version_lock.write_text(
            "lockfileVersion: '8.0'\npackages:\n  example@1.0.0:\n",
            encoding="utf-8",
        )
        _expect_rejected(
            lambda: parse_lock_section_keys(bad_version_lock, "packages"),
            "expected 9.0",
        )
        malformed_lock = root / "malformed-lock.yaml"
        malformed_lock.write_text(
            "lockfileVersion: '9.0'\npackages:\n  missing-version:\n",
            encoding="utf-8",
        )
        _expect_rejected(
            lambda: parse_lock_section_keys(malformed_lock, "packages"),
            "malformed pnpm package key",
        )

    print(
        "Node inventory self-test passed active/skipped peer contexts and determinism; "
        "it rejected missing transitive/metadata/required, orphan, unlocked, "
        "unknown/private/non-string/conflicting license, malformed lock, and path escape."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
