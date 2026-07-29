# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import time
from pathlib import Path


FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_reparse_point(path: str | Path) -> bool:
    candidate = Path(path)
    try:
        stat = candidate.lstat()
    except FileNotFoundError:
        return False
    return candidate.is_symlink() or bool(
        getattr(stat, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT
    )


def reject_reparse_points(path: str | Path, label: str) -> None:
    """Reject symlinks, junctions, and nested Windows reparse points in controlled stores."""

    root = Path(path)
    if not root.exists():
        return
    if is_reparse_point(root):
        raise ValueError(f"{label} cannot be a symlink, junction, or reparse point: {root}")
    if not root.is_dir():
        return
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in [*directories, *files]:
            candidate = current_path / name
            if is_reparse_point(candidate):
                raise ValueError(
                    f"{label} contains a symlink, junction, or reparse point: {candidate}"
                )


def reject_reparse_traversal(root: str | Path, target: str | Path, label: str) -> None:
    """Reject a reparse point on the lexical path from one controlled root to a target."""

    root_path = Path(os.path.abspath(root))
    target_path = Path(os.path.abspath(target))
    try:
        if os.path.commonpath(
            (os.path.normcase(str(root_path)), os.path.normcase(str(target_path)))
        ) != os.path.normcase(str(root_path)):
            raise ValueError(f"{label} escaped its controlled root")
        relative = target_path.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(f"{label} escaped its controlled root") from exc

    cursor = root_path
    if cursor.exists() and is_reparse_point(cursor):
        raise ValueError(f"{label} crosses a junction or reparse point: {cursor}")
    for segment in relative.parts:
        cursor /= segment
        if cursor.exists() and is_reparse_point(cursor):
            raise ValueError(f"{label} crosses a junction or reparse point: {cursor}")


def replace_file(source: str | Path, target: str | Path, attempts: int = 6) -> None:
    """Atomically replace a file, tolerating short Windows scanner/handle races."""

    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            transient = os.name == "nt" and (
                isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {5, 32}
            )
            if not transient or attempt + 1 >= attempts:
                raise
            time.sleep(0.02 * (2**attempt))


def unlink_file(path: str | Path, missing_ok: bool = True, attempts: int = 7) -> None:
    """Delete a file with bounded retries for transient Windows sharing violations."""

    candidate = Path(path)
    for attempt in range(attempts):
        try:
            candidate.unlink(missing_ok=missing_ok)
            return
        except OSError as exc:
            transient = os.name == "nt" and (
                isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {5, 32}
            )
            if not transient or attempt + 1 >= attempts:
                raise
            time.sleep(0.02 * (2**attempt))
