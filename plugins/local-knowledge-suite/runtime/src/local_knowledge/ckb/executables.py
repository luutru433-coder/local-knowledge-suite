# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from pathlib import Path


class ExecutableResolutionError(RuntimeError):
    pass


_COMMAND_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        return os.path.commonpath(
            (
                os.path.normcase(str(candidate)),
                os.path.normcase(str(root)),
            )
        ) == os.path.normcase(str(root))
    except ValueError:
        return False


def _resolved_untrusted_roots(
    roots: Iterable[str | Path],
) -> tuple[Path, ...]:
    resolved: list[Path] = []
    for raw_root in roots:
        root = Path(raw_root).expanduser().resolve()
        if root == Path(root.anchor):
            continue
        if root not in resolved:
            resolved.append(root)
    return tuple(resolved)


def _validate_candidate(
    candidate: Path,
    command: str,
    untrusted_roots: tuple[Path, ...],
) -> Path | None:
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    if not resolved.is_file():
        return None
    if os.name != "nt" and not os.access(resolved, os.X_OK):
        return None
    if any(_is_within(resolved, root) for root in untrusted_roots):
        return None
    if os.name == "nt" and resolved.suffix.casefold() != ".exe":
        return None
    if os.name != "nt" and resolved.name != command:
        return None
    return resolved


def resolve_trusted_executable(
    command: str,
    *,
    explicit: str | Path | None = None,
    path_value: str | None = None,
    untrusted_roots: Iterable[str | Path] = (),
) -> Path:
    """Resolve an executable without Windows current-directory search.

    Empty, relative, and project-local PATH entries are ignored. On Windows,
    only real ``.exe`` files are accepted so a project cannot inject a batch
    file through ``PATHEXT``.
    """

    if not _COMMAND_NAME.fullmatch(command):
        raise ExecutableResolutionError("executable command name is invalid")
    roots = _resolved_untrusted_roots(untrusted_roots)
    if explicit is not None:
        raw_explicit = Path(explicit).expanduser()
        if not raw_explicit.is_absolute():
            raise ExecutableResolutionError(
                f"explicit {command} executable must be an absolute path"
            )
        resolved = _validate_candidate(raw_explicit, command, roots)
        if resolved is None:
            raise ExecutableResolutionError(
                f"explicit {command} executable is unavailable or untrusted"
            )
        return resolved

    active_path = os.environ.get("PATH", "") if path_value is None else path_value
    filename = (
        command
        if os.name != "nt" or command.casefold().endswith(".exe")
        else f"{command}.exe"
    )
    for raw_entry in active_path.split(os.pathsep):
        entry = raw_entry.strip()
        if len(entry) >= 2 and entry[0] == entry[-1] == '"':
            entry = entry[1:-1]
        if not entry:
            continue
        directory = Path(os.path.expandvars(entry)).expanduser()
        if not directory.is_absolute():
            continue
        resolved = _validate_candidate(directory / filename, command, roots)
        if resolved is not None:
            return resolved
    raise ExecutableResolutionError(
        f"trusted {command} executable was not found on absolute PATH entries"
    )
