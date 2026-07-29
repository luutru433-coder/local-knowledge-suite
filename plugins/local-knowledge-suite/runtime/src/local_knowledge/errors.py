# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

class LocalKnowledgeError(RuntimeError):
    """Base error with a user-actionable message."""


class ManifestError(LocalKnowledgeError):
    """A workspace or company manifest is absent or invalid."""


class RegistryError(LocalKnowledgeError):
    """The Windows company registry is unavailable or inconsistent."""


class CompatibilityError(LocalKnowledgeError):
    """Persisted state cannot safely be handled by this runtime."""


class SnapshotError(LocalKnowledgeError):
    """A project-memory snapshot is unsafe, incompatible, or invalid."""
