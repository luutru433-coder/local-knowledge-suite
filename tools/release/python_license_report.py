# SPDX-License-Identifier: MIT
# Copyright (c) 2026 John-IDK

"""Create a machine-readable Python license inventory from installed metadata."""

from __future__ import annotations

import argparse
import json
from importlib import metadata
from pathlib import Path


FIRST_PARTY = {"local-knowledge-runtime"}
UNKNOWN_VALUES = {"", "unknown", "unlicensed", "none", "n/a"}
LICENSE_ALIASES = {
    "BSD License": "BSD-3-Clause",
    "MIT License": "MIT",
    "PSF": "PSF-2.0",
    "BSD-3-Clause, Apache-2.0, dependency licenses": (
        "BSD-3-Clause AND Apache-2.0"
    ),
}
CLASSIFIER_LICENSES = {
    "Apache Software License": "Apache-2.0",
    "BSD License": "BSD-3-Clause",
    "ISC License (ISCL)": "ISC",
    "MIT License": "MIT",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "Python Software Foundation License": "PSF-2.0",
}


def _classifiers(distribution: metadata.Distribution) -> str | None:
    raw_values = [
        value.split("::")[-1].strip()
        for value in distribution.metadata.get_all("Classifier", [])
        if value.startswith("License ::")
        and "OSI Approved" in value
        and not value.endswith("OSI Approved")
    ]
    if not raw_values:
        return None
    values = [CLASSIFIER_LICENSES.get(value, "UNKNOWN") for value in raw_values]
    return " OR ".join(sorted(set(values)))


def _license_file(distribution: metadata.Distribution) -> str | None:
    for entry in distribution.files or ():
        lowered = entry.name.casefold()
        if not (
            lowered.startswith(("license", "licence", "copying"))
            or "licenses" in {part.casefold() for part in entry.parts}
        ):
            continue
        try:
            text = distribution.locate_file(entry).read_text(
                encoding="utf-8", errors="ignore"
            )
        except (OSError, UnicodeError):
            continue
        folded = text.casefold()
        if "apache license" in folded and "version 2.0" in folded:
            return "Apache-2.0"
        if "permission is hereby granted, free of charge" in folded:
            return "MIT"
        if "redistribution and use in source and binary forms" in folded:
            return "BSD-3-Clause"
        if "isc license" in folded:
            return "ISC"
        if "mozilla public license" in folded:
            return "MPL-2.0"
        if "python software foundation license" in folded:
            return "PSF-2.0"
    return None


def _normalize_declared_license(value: str) -> str:
    return LICENSE_ALIASES.get(value, value)


def _license(distribution: metadata.Distribution) -> tuple[str, str]:
    expression = (distribution.metadata.get("License-Expression") or "").strip()
    if expression.casefold() not in UNKNOWN_VALUES:
        return _normalize_declared_license(expression), "License-Expression"

    declared = (distribution.metadata.get("License") or "").strip()
    if (
        declared.casefold() not in UNKNOWN_VALUES
        and len(declared) <= 200
        and "\n" not in declared
    ):
        return _normalize_declared_license(declared), "License"

    classifier = _classifiers(distribution)
    if classifier:
        return classifier, "Classifier"

    inferred = _license_file(distribution)
    if inferred:
        return inferred, "License file"
    return "UNKNOWN", "Unresolved"


def inventory() -> list[dict[str, str]]:
    packages: dict[str, dict[str, str]] = {}
    for distribution in metadata.distributions():
        name = (distribution.metadata.get("Name") or "").strip()
        if not name or name.casefold() in FIRST_PARTY:
            continue
        license_name, source = _license(distribution)
        key = name.casefold()
        packages[key] = {
            "Name": name,
            "Version": distribution.version,
            "License": license_name,
            "Source": source,
        }
    return [packages[key] for key in sorted(packages)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(inventory(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Created Python license inventory: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
