# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import base64
import binascii
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import time
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

import httpx

from ..ckb.network import canonicalize_lm_studio_url
from ..winio import replace_file


VAULT_VERSION = 1
SIGNAL_KINDS = {
    "commitment",
    "correction",
    "decision",
    "entity-fact",
    "habit",
    "preference",
    "project-knowledge",
    "secret",
}
PRIVACY_LEVELS = {"private", "sensitive"}
ENTITY_TYPES = {"concept", "organization", "person", "place", "project", "system"}
EVENT_MARKER_RE = re.compile(r"^<!-- memorizer:event ([A-Za-z0-9_-]+) -->$", re.MULTILINE)
EVENT_MARKER_PREFIX = "<!-- memorizer:event"
DAILY_EVENT_HEADING_RE = re.compile(
    rf"^## (?P<time>\d{{2}}:\d{{2}}:\d{{2}}Z) · (?P<kind>{'|'.join(sorted(map(re.escape, SIGNAL_KINDS)))}) · (?P<id>[A-Za-z0-9_.:-]{{3,128}})$",
    re.MULTILINE,
)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{3,128}$")
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
WINDOWS_RESERVED = {
    "aux",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "con",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
    "nul",
    "prn",
}


class MemorizerError(RuntimeError):
    """A user-facing vault or input error."""


class _DerivedStateStale(RuntimeError):
    def __init__(self, pending_events: bool) -> None:
        super().__init__("derived memory state is stale")
        self.pending_events = pending_events


@dataclass
class Note:
    id: str
    title: str
    kind: str
    body: str
    created_at: str
    updated_at: str
    memory_key: str
    status: str = "active"
    privacy: str = "private"
    pinned: bool = False
    revisit_count: int = 0
    confidence: float = 1.0
    importance: float = 0.7
    tags: list[str] = field(default_factory=list)
    entities: list[dict[str, str]] = field(default_factory=list)
    relations: list[dict[str, str]] = field(default_factory=list)
    source_event_ids: list[str] = field(default_factory=list)
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    @property
    def content_hash(self) -> str:
        payload = json.dumps(
            {
                "id": self.id,
                "title": self.title,
                "kind": self.kind,
                "body": self.body,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "memory_key": self.memory_key,
                "status": self.status,
                "privacy": self.privacy,
                "pinned": self.pinned,
                "revisit_count": self.revisit_count,
                "confidence": self.confidence,
                "importance": self.importance,
                "tags": self.tags,
                "entities": self.entities,
                "relations": self.relations,
                "source_event_ids": self.source_event_ids,
                "supersedes": self.supersedes,
                "superseded_by": self.superseded_by,
                "extra": self.extra,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def embedding_content_hash(self) -> str:
        return _embedding_content_hash(self.title, self.body, self.tags, self.entities)


def _embedding_content_hash(
    title: str, body: str, tags: list[str], entities: list[dict[str, str]]
) -> str:
    payload = json.dumps(
        {"title": title, "body": body, "tags": tags, "entities": entities},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> dt.datetime:
    if not isinstance(value, str):
        raise MemorizerError(f"invalid ISO-8601 timestamp: {value!r}")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MemorizerError(f"invalid ISO-8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _ensure_json_compatible(value: Any, context: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise MemorizerError(f"{context} must contain JSON-compatible Unicode values: {exc}") from exc


def vault_path(root: str | Path) -> Path:
    return Path(root).resolve() / ".memorizer"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


@contextlib.contextmanager
def vault_lock(vault: Path, timeout: float = 5.0) -> Iterator[None]:
    vault.mkdir(parents=True, exist_ok=True)
    lock_path = vault / ".write.lock"
    deadline = time.monotonic() + timeout
    open_flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_BINARY"):
        open_flags |= os.O_BINARY
    descriptor = os.open(lock_path, open_flags, 0o600)
    locked = False
    try:
        if os.fstat(descriptor).st_size == 0:
            try:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            except OSError:
                # Another writer may already hold the first byte while this
                # descriptor observed the just-created file at size zero.
                pass
        while not locked:
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise MemorizerError(
                        "the vault is busy; retry after the other memory operation finishes"
                    ) from exc
                time.sleep(0.05)
        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
            os.fsync(descriptor)
        yield
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


DEFAULT_CONFIG: dict[str, Any] = {
    "version": VAULT_VERSION,
    "memory_limit": 60,
    "embedding": {"url": "", "model": "", "timeout_seconds": 4},
    "ranking": {
        "lexical": 0.50,
        "semantic": 0.20,
        "recency": 0.10,
        "revisit": 0.08,
        "pin": 0.08,
        "graph": 0.04,
    },
}


def init_vault(root: str | Path) -> dict[str, Any]:
    vault = vault_path(root)
    with vault_lock(vault):
        for directory in ("daily", "notes", "entities"):
            (vault / directory).mkdir(parents=True, exist_ok=True)
        config_path = vault / "config.json"
        if not config_path.exists():
            _atomic_write(config_path, json.dumps(DEFAULT_CONFIG, indent=2, ensure_ascii=False) + "\n")
        memory_path = vault / "MEMORY.md"
        if not memory_path.exists():
            _atomic_write(memory_path, "# Memory\n\n_No distilled memories yet._\n")
        notes = load_notes(vault)
        _regenerate_entities(vault, notes.values())
        _regenerate_memory(vault, notes.values())
        if not _index_is_current(vault, notes):
            rebuild_index_unlocked(vault)
    return {"vault": str(vault), "version": VAULT_VERSION}


def load_config(vault: Path) -> dict[str, Any]:
    path = vault / "config.json"
    if not path.exists():
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemorizerError(f"cannot read {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise MemorizerError(f"{path} must contain one JSON object")
    _ensure_json_compatible(config, str(path))
    if isinstance(config.get("version"), bool) or config.get("version") != VAULT_VERSION:
        raise MemorizerError(f"unsupported vault version: {config.get('version')!r}")
    if not isinstance(config.get("embedding", {}), dict) or not isinstance(config.get("ranking", {}), dict):
        raise MemorizerError(f"{path} embedding and ranking settings must be objects")
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    merged.update({key: value for key, value in config.items() if key not in {"embedding", "ranking"}})
    merged["embedding"].update(config.get("embedding", {}))
    merged["ranking"].update(config.get("ranking", {}))
    if (
        isinstance(merged.get("memory_limit"), bool)
        or not isinstance(merged.get("memory_limit"), int)
        or merged["memory_limit"] < 1
    ):
        raise MemorizerError(f"{path} memory_limit must be a positive integer")
    embedding = merged["embedding"]
    if not isinstance(embedding.get("url"), str) or not isinstance(embedding.get("model"), str):
        raise MemorizerError(f"{path} embedding url and model must be strings")
    timeout_value = embedding.get("timeout_seconds")
    if (
        isinstance(timeout_value, bool)
        or not isinstance(timeout_value, (int, float))
        or not math.isfinite(timeout_value)
        or timeout_value <= 0
    ):
        raise MemorizerError(f"{path} embedding timeout_seconds must be a positive finite number")
    weights = merged["ranking"]
    unknown_weights = set(weights) - set(DEFAULT_CONFIG["ranking"])
    if unknown_weights:
        raise MemorizerError(f"{path} has unknown ranking weights: {', '.join(sorted(unknown_weights))}")
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in weights.values()
    ):
        raise MemorizerError(f"{path} ranking weights must be finite non-negative numbers")
    if not sum(float(value) for value in weights.values()):
        raise MemorizerError(f"{path} ranking weights cannot all be zero")
    return merged


SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----", re.I), "[REDACTED PRIVATE KEY]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED AWS KEY]"),
    (re.compile(r"\b(?:sk|rk|pk)-[A-Za-z0-9_\-]{16,}\b", re.I), "[REDACTED TOKEN]"),
    (re.compile(r"\b(?:gh[pousr]_|github_pat_)[A-Za-z0-9_\-]{12,}\b", re.I), "[REDACTED TOKEN]"),
    (re.compile(r"\bglpat-[A-Za-z0-9_\-]{12,}\b", re.I), "[REDACTED TOKEN]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9_\-]{16,}\b", re.I), "[REDACTED TOKEN]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}\b", re.I), "Bearer [REDACTED]"),
    (re.compile(r"\bBasic\s+[A-Za-z0-9+/]{16,}={0,2}\b", re.I), "Basic [REDACTED]"),
    (
        re.compile(
            r"(?i)([\"'])(password|passwd|pwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|private[_ -]?key|secret|token)\1(\s*:\s*)([\"'])(?!\[REDACTED\])[^\"']+\4"
        ),
        r"\1\2\1\3\4[REDACTED]\4",
    ),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|private[_ -]?key|secret|token)\b(\s*[:=]\s*)([\"'])(?!\[REDACTED\])[^\"']+\3"
        ),
        r"\1\2\3[REDACTED]\3",
    ),
    (
        re.compile(
            r"(?i)([\"'])(password|passwd|pwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|private[_ -]?key|secret|token)\1(\s*:\s*)([\"'])(?!\[REDACTED\])[^\"']*$"
        ),
        r"\1\2\1\3\4[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|private[_ -]?key|secret|token)\b(\s*[:=]\s*)([\"'])(?!\[REDACTED\])[^\"']*$"
        ),
        r"\1\2\3[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b(password|passwd|pwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|private[_ -]?key|secret|token)\b(\s*[:=]\s*|\s+is\s+)(?!\\?[\"']?\[REDACTED(?: [A-Z ]+)?\])([^\s,;\"']+)"
        ),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"(?i)([?&](?:token|api_key|access_token|password)=)[^&#\s]+"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)\b(authorization|proxy[_ -]?authorization|cookie|set[_ -]?cookie|credentials?|session[_ -]?id)\b(\s*[:=]\s*)([^\s,;]+)"
        ),
        r"\1\2[REDACTED]",
    ),
    (re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s/@:]+:[^\s/@]+@"), "[REDACTED CREDENTIALS]@"),
]
SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:password|passwd|pwd|token|secret|key|credentials?|authorization|auth|cookie|session|session[_\-\s]?id|bearer|basic)$"
)
BASE64_CANDIDATE_RE = re.compile(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{20,}={0,2}(?![A-Za-z0-9+/_-])")
MAX_ENCODED_SECRET_DEPTH = 4
MAX_ENCODED_SECRET_CHARS = 262_144


def _payload_contains_secret(value: Any, depth: int, seen: set[str]) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).strip().casefold()
            if (
                normalized_key != "memory_key"
                and SENSITIVE_KEY_RE.search(normalized_key)
                and not (
                item is None or item == "" or item == "[REDACTED]"
                )
            ):
                return True
            if _payload_contains_secret(item, depth, seen):
                return True
        return False
    if isinstance(value, list):
        return any(_payload_contains_secret(item, depth, seen) for item in value)
    if not isinstance(value, str):
        return False
    if any(pattern.search(value) for pattern, _ in SECRET_PATTERNS):
        return True
    if depth >= MAX_ENCODED_SECRET_DEPTH:
        return False
    return any(
        _decoded_base64_contains_secret(match.group(0), depth + 1, seen)
        for match in BASE64_CANDIDATE_RE.finditer(value)
    )


def _decoded_base64_contains_secret(
    candidate: str,
    depth: int = 0,
    seen: set[str] | None = None,
) -> bool:
    if depth > MAX_ENCODED_SECRET_DEPTH:
        return False
    if len(candidate) > MAX_ENCODED_SECRET_CHARS:
        return True
    active_seen = seen if seen is not None else set()
    normalized = candidate.rstrip("=")
    if normalized in active_seen:
        return False
    active_seen.add(normalized)
    padded = candidate + "=" * (-len(candidate) % 4)
    for altchars in (None, b"-_"):
        try:
            decoded = base64.b64decode(padded, altchars=altchars, validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError, binascii.Error):
            continue
        if _payload_contains_secret(decoded, depth, active_seen):
            return True
        try:
            payload = json.loads(decoded)
        except json.JSONDecodeError:
            continue
        if _payload_contains_secret(payload, depth, active_seen):
            return True
    return False


def redact_text(value: str) -> tuple[str, bool]:
    redacted = value
    changed = False
    for pattern, replacement in SECRET_PATTERNS:
        redacted, count = pattern.subn(replacement, redacted)
        changed = changed or bool(count)
    encoded_changed = False

    def replace_encoded(match: re.Match[str]) -> str:
        nonlocal encoded_changed
        if _decoded_base64_contains_secret(match.group(0)):
            encoded_changed = True
            return "[REDACTED ENCODED SECRET]"
        return match.group(0)

    redacted = BASE64_CANDIDATE_RE.sub(replace_encoded, redacted)
    changed = changed or encoded_changed
    return redacted, changed


def redact_payload(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        output: list[Any] = []
        changed = False
        for item in value:
            safe, item_changed = redact_payload(item)
            output.append(safe)
            changed = changed or item_changed
        return output, changed
    if isinstance(value, dict):
        output_dict: dict[str, Any] = {}
        changed = False
        for key, item in value.items():
            safe_key, key_changed = redact_text(str(key))
            normalized_key = str(key).strip().casefold()
            if (
                normalized_key != "memory_key"
                and SENSITIVE_KEY_RE.search(normalized_key)
                and not (
                item is None or item == "" or item == "[REDACTED]"
                )
            ):
                safe_item, item_changed = "[REDACTED]", True
            else:
                safe_item, item_changed = redact_payload(item)
            output_dict[safe_key] = safe_item
            changed = changed or key_changed or item_changed
        return output_dict, changed
    return value, False


def _normalize_space(value: str) -> str:
    return " ".join(value.split()).strip()


def normalized_text(value: str) -> str:
    return unicodedata.normalize("NFKC", _normalize_space(value)).casefold()


def slugify(value: str, fallback: str = "memory") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-. ")[:80]
    if not slug:
        slug = fallback
    if slug.casefold() in WINDOWS_RESERVED:
        slug = f"{slug}-item"
    return slug


def _clean_string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise MemorizerError(f"{field_name} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not _normalize_space(item):
            raise MemorizerError(f"{field_name} must contain non-empty strings")
        cleaned = _normalize_space(item)
        if cleaned not in result:
            result.append(cleaned)
    return result


def validate_event_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MemorizerError("capture input must be one JSON object")
    _ensure_json_compatible(payload, "capture input")
    safe_payload, redacted = redact_payload(payload)
    text = safe_payload.get("text")
    if not isinstance(text, str) or not _normalize_space(text):
        raise MemorizerError("capture input requires non-empty text")
    kind = safe_payload.get("kind")
    if not isinstance(kind, str):
        raise MemorizerError("capture input requires a signal kind")
    if kind not in SIGNAL_KINDS:
        raise MemorizerError(f"unknown signal kind {kind!r}; expected one of {', '.join(sorted(SIGNAL_KINDS))}")
    event_id = safe_payload["id"] if "id" in safe_payload else f"evt_{uuid.uuid4().hex}"
    if not isinstance(event_id, str) or not SAFE_ID_RE.fullmatch(event_id):
        raise MemorizerError("event id must use 3-128 letters, digits, dots, colons, underscores, or hyphens")
    title = safe_payload.get("title")
    if not isinstance(title, str) or not _normalize_space(title):
        raise MemorizerError("capture input requires a non-empty title")
    memory_key = safe_payload.get("memory_key")
    if not isinstance(memory_key, str) or not _normalize_space(memory_key):
        raise MemorizerError("capture input requires a non-empty string memory_key")
    entities = safe_payload.get("entities", [])
    if not isinstance(entities, list):
        raise MemorizerError("entities must be a list")
    cleaned_entities: list[dict[str, str]] = []
    for entity in entities:
        if not isinstance(entity, dict) or not isinstance(entity.get("name"), str):
            raise MemorizerError("each entity requires a name")
        entity_name = _normalize_space(entity["name"])
        if not entity_name:
            raise MemorizerError("each entity requires a non-empty name")
        entity_type = entity.get("type", "concept")
        if not isinstance(entity_type, str) or entity_type not in ENTITY_TYPES:
            raise MemorizerError(f"unknown entity type {entity_type!r}")
        cleaned_entities.append({"name": entity_name, "type": entity_type})
    relations = safe_payload.get("relations", [])
    if not isinstance(relations, list):
        raise MemorizerError("relations must be a list")
    cleaned_relations: list[dict[str, str]] = []
    for relation in relations:
        if not isinstance(relation, dict):
            raise MemorizerError("each relation must be an object")
        relation_type = relation.get("type")
        target = relation.get("target")
        if not isinstance(relation_type, str) or not _normalize_space(relation_type):
            raise MemorizerError("each relation requires a non-empty type")
        if not isinstance(target, str) or not _normalize_space(target):
            raise MemorizerError("each relation requires a non-empty target")
        target_kind = relation.get("target_kind", "note")
        if not isinstance(target_kind, str) or target_kind not in {"note", "entity"}:
            raise MemorizerError("relation target_kind must be note or entity")
        cleaned_relations.append(
            {
                "type": slugify(relation_type, "related-to"),
                "target": _normalize_space(target),
                "target_kind": target_kind,
            }
        )
    confidence = safe_payload.get("confidence", 1.0)
    importance = safe_payload.get("importance", 0.7)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise MemorizerError("confidence must be between 0 and 1")
    if isinstance(importance, bool) or not isinstance(importance, (int, float)) or not 0 <= importance <= 1:
        raise MemorizerError("importance must be between 0 and 1")
    privacy = safe_payload.get("privacy", "private")
    if not isinstance(privacy, str) or privacy not in PRIVACY_LEVELS:
        raise MemorizerError(f"privacy must be one of {', '.join(sorted(PRIVACY_LEVELS))}")
    if redacted or kind == "secret":
        privacy = "sensitive"
    supersedes = _clean_string_list(safe_payload.get("supersedes", []), "supersedes")
    if kind == "correction" and not supersedes:
        raise MemorizerError("a correction must name at least one superseded memory id")
    if kind != "correction" and supersedes:
        raise MemorizerError("supersedes is only valid for correction events")
    pinned = safe_payload.get("pinned", False)
    if not isinstance(pinned, bool):
        raise MemorizerError("pinned must be a boolean")
    captured_at = safe_payload["captured_at"] if "captured_at" in safe_payload else utc_now()
    parse_time(captured_at)
    result = {
        "id": event_id,
        "captured_at": captured_at,
        "kind": kind,
        "text": _normalize_space(text),
        "title": _normalize_space(title)[:160] if title else _normalize_space(text)[:96],
        "tags": _clean_string_list(safe_payload.get("tags", []), "tags"),
        "entities": cleaned_entities,
        "relations": cleaned_relations,
        "confidence": float(confidence),
        "importance": float(importance),
        "privacy": privacy,
        "pinned": pinned,
        "memory_key": _normalize_space(memory_key),
        "supersedes": supersedes,
        "source": safe_payload.get("source", "conversation"),
        "redacted": redacted,
    }
    result["fingerprint"] = _event_fingerprint(result)
    return result


def _event_fingerprint(event: dict[str, Any]) -> str:
    fingerprint_payload = {
        key: value
        for key, value in event.items()
        if key not in {"captured_at", "redacted", "fingerprint", "_daily_path"}
    }
    return hashlib.sha256(
        json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _encode_event(event: dict[str, Any]) -> str:
    raw = json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_event(encoded: str, source: Path) -> dict[str, Any]:
    try:
        raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        event = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MemorizerError(f"invalid event metadata in {source}: {exc}") from exc
    if not isinstance(event, dict):
        raise MemorizerError(f"event metadata in {source} is not an object")
    try:
        canonical = validate_event_payload(event)
    except MemorizerError as exc:
        raise MemorizerError(f"invalid event schema in {source}: {exc}") from exc
    if set(event) != set(canonical):
        raise MemorizerError(f"invalid event schema in {source}: unexpected or missing fields")
    for key, value in canonical.items():
        if key == "redacted":
            if not isinstance(event.get(key), bool):
                raise MemorizerError(f"invalid event schema in {source}: redacted must be a boolean")
            continue
        if event.get(key) != value:
            raise MemorizerError(f"invalid event schema or fingerprint in {source}: field {key!r} drifted")
    return event


def _visible_event_text(event: dict[str, Any]) -> str:
    visible_text = event["text"].replace(EVENT_MARKER_PREFIX, "&lt;!-- memorizer:event")
    if DAILY_EVENT_HEADING_RE.fullmatch(visible_text):
        visible_text = "&#35;&#35;" + visible_text[2:]
    return visible_text


def iter_events(vault: Path) -> Iterator[dict[str, Any]]:
    seen_ids: dict[str, Path] = {}
    for path in sorted((vault / "daily").glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise MemorizerError(f"cannot read daily journal {path}: {exc}") from exc
        expected_header = f"# Daily memory · {path.stem}\n"
        try:
            dt.date.fromisoformat(path.stem)
        except ValueError as exc:
            raise MemorizerError(f"daily journal has an invalid date filename: {path}") from exc
        if not text.startswith(expected_header):
            raise MemorizerError(f"daily journal has an invalid header: {path}")
        matches = list(EVENT_MARKER_RE.finditer(text))
        headings = list(DAILY_EVENT_HEADING_RE.finditer(text))
        if len(headings) != len(matches):
            raise MemorizerError(
                f"truncated or malformed event framing in {path}; restore the daily journal before continuing"
            )
        for index, (heading, match) in enumerate(zip(headings, matches)):
            next_heading_start = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            if not heading.end() <= match.start() < next_heading_start:
                raise MemorizerError(f"event blocks are out of order or malformed in {path}")
            event = _decode_event(match.group(1), path)
            event_time = parse_time(event["captured_at"])
            if (
                event["id"] != heading.group("id")
                or event["kind"] != heading.group("kind")
                or event_time.strftime("%H:%M:%SZ") != heading.group("time")
                or event_time.date().isoformat() != path.stem
            ):
                raise MemorizerError(f"event heading and metadata disagree in {path}")
            expected_visible_block = f"\n\n{_visible_event_text(event)}\n\n"
            if text[heading.end() : match.start()] != expected_visible_block:
                raise MemorizerError(f"visible heartbeat and encoded event disagree in {path}")
            if event["id"] in seen_ids:
                raise MemorizerError(
                    f"duplicate event id {event['id']!r} in {path} and {seen_ids[event['id']]}"
                )
            seen_ids[event["id"]] = path
            event["_daily_path"] = str(path)
            yield event


def _event_markdown(event: dict[str, Any]) -> str:
    timestamp = parse_time(event["captured_at"]).strftime("%H:%M:%SZ")
    visible_text = _visible_event_text(event)
    return (
        f"\n## {timestamp} · {event['kind']} · {event['id']}\n\n"
        f"{visible_text}\n\n"
        f"<!-- memorizer:event {_encode_event(event)} -->\n"
    )


def capture(root: str | Path, payload: Any, defer: bool = False) -> dict[str, Any]:
    vault = vault_path(root)
    if not (vault / "config.json").exists():
        init_vault(root)
    event = validate_event_payload(payload)
    duplicate = False
    with vault_lock(vault):
        notes = load_notes(vault)
        known_entities = {
            entity_id(entity["type"], entity["name"]): (entity["name"], entity["type"])
            for note in notes.values()
            for entity in note.entities
        }
        for entity in event["entities"]:
            known_entities[entity_id(entity["type"], entity["name"])] = (entity["name"], entity["type"])
        for relation in event["relations"]:
            target = relation["target"]
            if relation["target_kind"] == "note":
                if target not in notes:
                    raise MemorizerError(f"relation targets missing memory {target!r}")
            else:
                if target not in known_entities:
                    matches = [
                        identifier
                        for identifier, (name, _) in known_entities.items()
                        if name.casefold() == target.casefold()
                    ]
                    if len(matches) != 1:
                        raise MemorizerError(f"relation targets missing or ambiguous entity {target!r}")
                    relation["target"] = matches[0]
        event["fingerprint"] = _event_fingerprint(event)
        existing = {item["id"]: item for item in iter_events(vault)}
        previous = existing.get(event["id"])
        if previous:
            if previous.get("fingerprint") != event["fingerprint"]:
                raise MemorizerError(f"event id {event['id']!r} already exists with different content")
            duplicate = True
        else:
            if event["supersedes"]:
                conflicting = sorted(
                    prior["id"]
                    for prior in existing.values()
                    if prior.get("id") != event["id"]
                    and set(prior.get("supersedes", [])) & set(event["supersedes"])
                    and not _event_is_complete(prior, notes)
                )
                if conflicting:
                    raise MemorizerError(
                        "another pending correction already targets this memory: " + ", ".join(conflicting)
                    )
                for target_id in event["supersedes"]:
                    target = notes.get(target_id)
                    if target is None:
                        raise MemorizerError(f"correction targets missing memory {target_id!r}")
                    if target.status != "active":
                        raise MemorizerError(f"correction targets non-active memory {target_id!r}")
            day = parse_time(event["captured_at"]).date().isoformat()
            daily_path = vault / "daily" / f"{day}.md"
            if not daily_path.exists():
                _atomic_write(daily_path, f"# Daily memory · {day}\n")
            existing_daily = daily_path.read_text(encoding="utf-8")
            _atomic_write(daily_path, existing_daily + _event_markdown(event))
    result: dict[str, Any] = {
        "event_id": event["id"],
        "duplicate": duplicate,
        "redacted": event["redacted"],
        "daily_path": str(vault / "daily" / f"{parse_time(event['captured_at']).date().isoformat()}.md"),
        "distilled": False,
    }
    if not defer:
        distilled = distill(root)
        result["distilled"] = True
        result["distillation"] = distilled
        result["memory_ids"] = distilled.get("event_memory_ids", {}).get(event["id"], [])
    return result


FRONTMATTER_ORDER = [
    "id",
    "title",
    "type",
    "created_at",
    "updated_at",
    "memory_key",
    "status",
    "privacy",
    "pinned",
    "revisit_count",
    "confidence",
    "importance",
    "tags",
    "entities",
    "relations",
    "source_event_ids",
    "supersedes",
    "superseded_by",
]


def _frontmatter_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def note_to_markdown(note: Note) -> str:
    values: dict[str, Any] = {
        "id": note.id,
        "title": note.title,
        "type": note.kind,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
        "memory_key": note.memory_key,
        "status": note.status,
        "privacy": note.privacy,
        "pinned": note.pinned,
        "revisit_count": note.revisit_count,
        "confidence": note.confidence,
        "importance": note.importance,
        "tags": note.tags,
        "entities": note.entities,
        "relations": note.relations,
        "source_event_ids": note.source_event_ids,
        "supersedes": note.supersedes,
        "superseded_by": note.superseded_by,
    }
    values.update(note.extra)
    _ensure_json_compatible({"frontmatter": values, "body": note.body}, f"memory {note.id!r}")
    keys = FRONTMATTER_ORDER + sorted(key for key in values if key not in FRONTMATTER_ORDER)
    lines = ["---"] + [f"{key}: {_frontmatter_value(values[key])}" for key in keys] + ["---", "", f"# {note.title}", "", note.body.rstrip(), ""]
    return "\n".join(lines)


def parse_note(path: Path) -> Note:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise MemorizerError(f"cannot read note {path}: {exc}") from exc
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise MemorizerError(f"note {path} is missing JSON-valued YAML frontmatter")
    frontmatter_text, body_section = text[4:].split("\n---\n", 1)
    values: dict[str, Any] = {}
    for line_number, line in enumerate(frontmatter_text.splitlines(), start=2):
        if ": " not in line:
            raise MemorizerError(f"note {path}:{line_number} has invalid frontmatter")
        key, raw = line.split(": ", 1)
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", key):
            raise MemorizerError(f"note {path}:{line_number} has invalid field name {key!r}")
        if key in values:
            raise MemorizerError(f"note {path}:{line_number} repeats field {key!r}")
        try:
            values[key] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise MemorizerError(f"note {path}:{line_number} has invalid JSON value") from exc
    _ensure_json_compatible(values, f"note {path}")
    required = {"id", "title", "type", "created_at", "updated_at", "memory_key"}
    missing = sorted(required - values.keys())
    if missing:
        raise MemorizerError(f"note {path} is missing fields: {', '.join(missing)}")
    for field_name in required | {"status", "privacy"}:
        if field_name in values and not isinstance(values[field_name], str):
            raise MemorizerError(f"note {path} field {field_name!r} must be a string")
    for field_name in required:
        if not _normalize_space(values[field_name]):
            raise MemorizerError(f"note {path} field {field_name!r} must not be empty")
    if not SAFE_ID_RE.fullmatch(values["id"]):
        raise MemorizerError(f"note {path} has invalid memory id {values['id']!r}")
    if values["type"] not in SIGNAL_KINDS:
        raise MemorizerError(f"note {path} has invalid type {values['type']!r}")
    if values.get("status", "active") not in {"active", "superseded", "rejected"}:
        raise MemorizerError(f"note {path} has invalid status {values.get('status')!r}")
    if values.get("privacy", "private") not in PRIVACY_LEVELS:
        raise MemorizerError(f"note {path} has invalid privacy {values.get('privacy')!r}")
    parse_time(values["created_at"])
    parse_time(values["updated_at"])
    for field_name in {"tags", "entities", "relations", "source_event_ids", "supersedes"}:
        if field_name in values and not isinstance(values[field_name], list):
            raise MemorizerError(f"note {path} field {field_name!r} must be a list")
    if "pinned" in values and not isinstance(values["pinned"], bool):
        raise MemorizerError(f"note {path} field 'pinned' must be a boolean")
    revisit_count = values.get("revisit_count", 0)
    if isinstance(revisit_count, bool) or not isinstance(revisit_count, int) or revisit_count < 0:
        raise MemorizerError(f"note {path} revisit_count must be a non-negative integer")
    for field_name, default in (("confidence", 1.0), ("importance", 0.7)):
        numeric = values.get(field_name, default)
        if (
            isinstance(numeric, bool)
            or not isinstance(numeric, (int, float))
            or not math.isfinite(numeric)
            or not 0 <= numeric <= 1
        ):
            raise MemorizerError(f"note {path} {field_name} must be between 0 and 1")
    if values.get("superseded_by") is not None and not isinstance(values.get("superseded_by"), str):
        raise MemorizerError(f"note {path} field 'superseded_by' must be a string or null")
    for field_name in {"tags", "source_event_ids", "supersedes"}:
        if any(not isinstance(item, str) or not _normalize_space(item) for item in values.get(field_name, [])):
            raise MemorizerError(f"note {path} field {field_name!r} must contain non-empty strings")
    for entity in values.get("entities", []):
        if (
            not isinstance(entity, dict)
            or not isinstance(entity.get("name"), str)
            or not _normalize_space(entity["name"])
            or not isinstance(entity.get("type"), str)
            or entity.get("type") not in ENTITY_TYPES
        ):
            raise MemorizerError(f"note {path} contains invalid entity metadata")
    for relation in values.get("relations", []):
        target_kind = relation.get("target_kind", "note") if isinstance(relation, dict) else None
        if (
            not isinstance(relation, dict)
            or not isinstance(relation.get("type"), str)
            or not _normalize_space(relation["type"])
            or not isinstance(relation.get("target"), str)
            or not _normalize_space(relation["target"])
            or not isinstance(target_kind, str)
            or target_kind not in {"note", "entity"}
        ):
            raise MemorizerError(f"note {path} contains invalid relation metadata")
    body = body_section.lstrip("\n")
    heading = f"# {values['title']}\n"
    if body.startswith(heading):
        body = body[len(heading) :].lstrip("\n")
    extra = {key: value for key, value in values.items() if key not in set(FRONTMATTER_ORDER)}
    try:
        note = Note(
            id=values["id"],
            title=values["title"],
            kind=values["type"],
            body=body.rstrip(),
            created_at=values["created_at"],
            updated_at=values["updated_at"],
            memory_key=values["memory_key"],
            status=values.get("status", "active"),
            privacy=values.get("privacy", "private"),
            pinned=bool(values.get("pinned", False)),
            revisit_count=revisit_count,
            confidence=float(values.get("confidence", 1.0)),
            importance=float(values.get("importance", 0.7)),
            tags=list(values.get("tags", [])),
            entities=list(values.get("entities", [])),
            relations=list(values.get("relations", [])),
            source_event_ids=list(values.get("source_event_ids", [])),
            supersedes=list(values.get("supersedes", [])),
            superseded_by=values.get("superseded_by"),
            extra=extra,
            path=path,
        )
    except (TypeError, ValueError) as exc:
        raise MemorizerError(f"note {path} contains an invalid typed value: {exc}") from exc
    return note


def load_notes(vault: Path) -> dict[str, Note]:
    notes: dict[str, Note] = {}
    for path in sorted((vault / "notes").glob("*.md")):
        note = parse_note(path)
        if note.id in notes:
            raise MemorizerError(f"duplicate note id {note.id!r} in {path} and {notes[note.id].path}")
        notes[note.id] = note
    return notes


def _event_memory_ids(event_id_value: str, notes: dict[str, Note]) -> list[str]:
    return sorted(note.id for note in notes.values() if event_id_value in note.source_event_ids)


def _event_is_complete(event: dict[str, Any], notes: dict[str, Note]) -> bool:
    memory_ids = _event_memory_ids(event["id"], notes)
    if not memory_ids:
        return False
    if not event.get("supersedes"):
        return True
    if len(memory_ids) != 1:
        return False
    correction = notes[memory_ids[0]]
    if correction.status == "rejected":
        return True
    if sorted(correction.supersedes) != sorted(event["supersedes"]):
        return False
    return all(
        target_id in notes
        and notes[target_id].status == "superseded"
        and notes[target_id].superseded_by == correction.id
        for target_id in event["supersedes"]
    )


def _index_is_current(vault: Path, notes: dict[str, Note]) -> bool:
    index_path = vault / "index.sqlite3"
    if not index_path.exists():
        return False
    try:
        with _connect(index_path) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                return False
            indexed_notes = {
                row[0]: tuple(row[1:])
                for row in connection.execute(
                    """SELECT id,path,title,kind,body,status,privacy,pinned,revisit_count,
                              confidence,importance,tags_json,entities_json,relations_json,
                              source_event_ids_json,supersedes_json,superseded_by,created_at,
                              updated_at,memory_key,content_hash FROM notes"""
                )
            }
            indexed_fts = [
                tuple(row)
                for row in connection.execute(
                    "SELECT id,title,body,tags,entities FROM notes_fts ORDER BY id,title,body,tags,entities"
                )
            ]
            indexed_links = {
                tuple(row)
                for row in connection.execute("SELECT source_id,target_id,relation_type FROM links")
            }
            indexed_entities = {
                row[0]: (row[1], row[2])
                for row in connection.execute("SELECT id,name,type FROM entities")
            }
    except sqlite3.Error:
        return False
    expected_notes = {
        note.id: (
            str(note.path.relative_to(vault)) if note.path else "",
            note.title,
            note.kind,
            note.body,
            note.status,
            note.privacy,
            int(note.pinned),
            note.revisit_count,
            note.confidence,
            note.importance,
            json.dumps(note.tags, ensure_ascii=False),
            json.dumps(note.entities, ensure_ascii=False),
            json.dumps(note.relations, ensure_ascii=False),
            json.dumps(note.source_event_ids, ensure_ascii=False),
            json.dumps(note.supersedes, ensure_ascii=False),
            note.superseded_by,
            note.created_at,
            note.updated_at,
            note.memory_key,
            note.content_hash,
        )
        for note in notes.values()
    }
    expected_fts = sorted(
        (
            note.id,
            note.title,
            note.body,
            " ".join(note.tags),
            " ".join(entity["name"] for entity in note.entities),
        )
        for note in notes.values()
    )
    expected_links, expected_entity_rows = _collect_links(notes)
    return (
        indexed_notes == expected_notes
        and indexed_fts == expected_fts
        and indexed_links == set(expected_links)
        and indexed_entities == expected_entity_rows
    )


def _raise_if_derived_stale(vault: Path) -> None:
    events = list(iter_events(vault))
    notes = load_notes(vault)
    _assert_notes_safe_for_derivation(notes.values())
    pending_events = any(not _event_is_complete(event, notes) for event in events)
    if pending_events or not _index_is_current(vault, notes) or not _generated_views_are_current(vault, notes):
        raise _DerivedStateStale(pending_events)


def _note_path(vault: Path, note: Note) -> Path:
    suffix = note.id.removeprefix("mem_")[:16]
    return vault / "notes" / f"{slugify(note.title)}--{suffix}.md"


def write_note(vault: Path, note: Note) -> None:
    destination = note.path or _note_path(vault, note)
    destination = destination.resolve()
    notes_root = (vault / "notes").resolve()
    if destination.parent != notes_root:
        raise MemorizerError("note path escaped the vault")
    _atomic_write(destination, note_to_markdown(note))
    note.path = destination


def _assert_notes_safe_for_derivation(notes: Iterable[Note]) -> list[Note]:
    note_list = list(notes)
    for note in note_list:
        if note.path is None:
            raw = note_to_markdown(note)
            source = f"memory {note.id!r}"
        else:
            try:
                raw = note.path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise MemorizerError(f"cannot scan {note.path} for credentials: {exc}") from exc
            source = str(note.path)
        safe_raw, _ = redact_text(raw)
        if safe_raw != raw:
            raise MemorizerError(
                f"{source} contains an unredacted credential pattern; redact the source note before regenerating derived artifacts"
            )
    return note_list


def entity_id(entity_type: str, name: str) -> str:
    digest = hashlib.sha256(f"{entity_type}:{normalized_text(name)}".encode("utf-8")).hexdigest()[:16]
    return f"ent_{digest}"


def _derived_memory_key(event: dict[str, Any]) -> str:
    if event.get("memory_key"):
        return slugify(event["memory_key"], event["kind"])
    return f"{event['kind']}:{slugify(event['title'], event['kind'])}"


def _new_note_id(seed: str) -> str:
    return "mem_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _event_to_note(event: dict[str, Any], note_id: str, memory_key: str) -> Note:
    return Note(
        id=note_id,
        title=event["title"],
        kind=event["kind"],
        body=event["text"],
        created_at=event["captured_at"],
        updated_at=event["captured_at"],
        memory_key=memory_key,
        privacy=event["privacy"],
        pinned=event["pinned"],
        confidence=event["confidence"],
        importance=event["importance"],
        tags=event["tags"],
        entities=event["entities"],
        relations=event["relations"],
        source_event_ids=[event["id"]],
        supersedes=event["supersedes"],
    )


def _render_memory(vault: Path, notes: Iterable[Note]) -> str:
    config = load_config(vault)
    active = [note for note in notes if note.status == "active"]
    active.sort(key=lambda note: (not note.pinned, -note.importance, note.title.casefold(), note.id))
    limit = max(1, int(config.get("memory_limit", 60)))
    lines = ["# Memory", "", "Distilled, high-value memories for the current workspace.", ""]
    for note in active[:limit]:
        pin = " 📌" if note.pinned else ""
        summary = _normalize_space(note.body)[:320]
        lines.append(f"- **{note.title}**{pin} — {summary} `[[{note.id}]]`")
    if not active:
        lines.append("_No distilled memories yet._")
    return "\n".join(lines).rstrip() + "\n"


def _regenerate_memory(vault: Path, notes: Iterable[Note]) -> None:
    safe_notes = _assert_notes_safe_for_derivation(notes)
    _atomic_write(vault / "MEMORY.md", _render_memory(vault, safe_notes))


def _render_entity_views(vault: Path, notes: Iterable[Note]) -> dict[Path, str]:
    grouped: dict[str, dict[str, Any]] = {}
    for note in notes:
        if note.status != "active":
            continue
        for entity in note.entities:
            identifier = entity_id(entity["type"], entity["name"])
            group = grouped.setdefault(
                identifier,
                {"type": entity["type"], "names": set(), "notes": {}},
            )
            group["names"].add(entity["name"])
            group["notes"][note.id] = note
    expected: dict[Path, str] = {}
    for identifier, group in sorted(grouped.items()):
        entity_type = group["type"]
        name = sorted(group["names"], key=lambda value: (value.casefold(), value))[0]
        related_notes = list(group["notes"].values())
        path = vault / "entities" / entity_type / f"{slugify(name, 'entity')}--{identifier[4:]}.md"
        lines = ["---", f"id: {_frontmatter_value(identifier)}", f"name: {_frontmatter_value(name)}", f"type: {_frontmatter_value(entity_type)}", "---", "", f"# {name}", ""]
        for note in sorted(related_notes, key=lambda candidate: (candidate.title.casefold(), candidate.id)):
            lines.append(f"- [[{note.id}|{note.title}]]")
        expected[path.resolve()] = "\n".join(lines).rstrip() + "\n"
    return expected


def _regenerate_entities(vault: Path, notes: Iterable[Note]) -> None:
    safe_notes = _assert_notes_safe_for_derivation(notes)
    expected = _render_entity_views(vault, safe_notes)
    for path, content in expected.items():
        _atomic_write(path, content)
    for old_path in sorted((vault / "entities").glob("*/*.md")):
        if old_path.resolve() not in expected:
            old_path.unlink(missing_ok=True)


def _generated_views_are_current(vault: Path, notes: dict[str, Note]) -> bool:
    try:
        memory_path = vault / "MEMORY.md"
        if not memory_path.exists() or memory_path.read_text(encoding="utf-8") != _render_memory(
            vault, notes.values()
        ):
            return False
        expected_entities = _render_entity_views(vault, notes.values())
        actual_paths = {path.resolve() for path in (vault / "entities").glob("*/*.md")}
        if actual_paths != set(expected_entities):
            return False
        return all(path.read_text(encoding="utf-8") == content for path, content in expected_entities.items())
    except (OSError, UnicodeDecodeError, MemorizerError):
        return False


def _rejected_event_note(event: dict[str, Any], reason: str) -> Note:
    note = _event_to_note(
        event,
        _new_note_id(f"rejected:{event['id']}"),
        _derived_memory_key(event),
    )
    note.status = "rejected"
    note.extra["rejection_reason"] = reason
    return note


def distill(root: str | Path) -> dict[str, Any]:
    vault = vault_path(root)
    if not (vault / "config.json").exists():
        init_vault(root)
    with vault_lock(vault):
        events = list(iter_events(vault))
        notes = load_notes(vault)
        _assert_notes_safe_for_derivation(notes.values())
        source_to_note: dict[str, list[str]] = {}
        for note in notes.values():
            for event_id_value in note.source_event_ids:
                source_to_note.setdefault(event_id_value, []).append(note.id)
        event_memory_ids: dict[str, list[str]] = {event_id_value: list(ids) for event_id_value, ids in source_to_note.items()}
        processed = 0
        merged = 0
        superseded = 0
        repaired = 0
        conflicts = 0
        for event in events:
            existing_memory_ids = source_to_note.get(event["id"], [])
            if existing_memory_ids:
                if event["supersedes"]:
                    if len(existing_memory_ids) != 1:
                        raise MemorizerError(f"correction event {event['id']} has ambiguous distilled memories")
                    correction_id = existing_memory_ids[0]
                    correction = notes[correction_id]
                    if correction.status == "rejected":
                        continue
                    conflict_reason: str | None = None
                    for target_id in event["supersedes"]:
                        target = notes.get(target_id)
                        if target is None:
                            conflict_reason = f"missing correction target {target_id}"
                            break
                        if target.status == "active":
                            target.status = "superseded"
                            target.superseded_by = correction_id
                            target.updated_at = event["captured_at"]
                            write_note(vault, target)
                            repaired += 1
                        elif target.superseded_by != correction_id:
                            conflict_reason = f"correction target {target_id} was superseded by another memory"
                            break
                    if conflict_reason:
                        for target_id in event["supersedes"]:
                            target = notes.get(target_id)
                            if target and target.superseded_by == correction_id:
                                target.status = "active"
                                target.superseded_by = None
                                write_note(vault, target)
                        correction.status = "rejected"
                        correction.extra["rejection_reason"] = conflict_reason
                        write_note(vault, correction)
                        conflicts += 1
                continue
            memory_key = _derived_memory_key(event)
            equivalent = next(
                (
                    note
                    for note in notes.values()
                    if note.status == "active"
                    and note.kind == event["kind"]
                    and normalized_text(note.body) == normalized_text(event["text"])
                ),
                None,
            )
            if event["supersedes"]:
                targets: list[Note] = []
                note_id = _new_note_id(f"correction:{event['id']}")
                conflict_reason: str | None = None
                for target_id in event["supersedes"]:
                    target = notes.get(target_id)
                    if target is None:
                        conflict_reason = f"missing correction target {target_id}"
                        break
                    if target.status != "active" and target.superseded_by != note_id:
                        conflict_reason = f"correction target {target_id} is no longer active"
                        break
                    targets.append(target)
                if note_id in event["supersedes"]:
                    conflict_reason = "a correction cannot supersede itself"
                if conflict_reason:
                    note = _rejected_event_note(event, conflict_reason)
                    write_note(vault, note)
                    notes[note.id] = note
                    event_memory_ids[event["id"]] = [note.id]
                    source_to_note[event["id"]] = [note.id]
                    processed += 1
                    conflicts += 1
                    continue
                note = _event_to_note(event, note_id, memory_key or targets[0].memory_key)
                write_note(vault, note)
                notes[note.id] = note
                for target in targets:
                    target.status = "superseded"
                    target.superseded_by = note.id
                    target.updated_at = event["captured_at"]
                    write_note(vault, target)
                    superseded += 1
                event_memory_ids[event["id"]] = [note.id]
            elif equivalent is not None:
                equivalent.source_event_ids.append(event["id"])
                equivalent.source_event_ids = sorted(set(equivalent.source_event_ids))
                equivalent.updated_at = max(equivalent.updated_at, event["captured_at"])
                equivalent.pinned = equivalent.pinned or event["pinned"]
                equivalent.importance = max(equivalent.importance, event["importance"])
                equivalent.confidence = max(equivalent.confidence, event["confidence"])
                if event["privacy"] == "sensitive":
                    equivalent.privacy = "sensitive"
                equivalent.tags = sorted(set(equivalent.tags) | set(event["tags"]), key=str.casefold)
                entities_by_id = {
                    entity_id(entity["type"], entity["name"]): entity for entity in equivalent.entities
                }
                for entity in event["entities"]:
                    entities_by_id.setdefault(entity_id(entity["type"], entity["name"]), entity)
                equivalent.entities = sorted(
                    entities_by_id.values(), key=lambda entity: (entity["type"], entity["name"].casefold())
                )
                relations_by_key = {
                    (relation["type"], relation["target"], relation.get("target_kind", "note")): relation
                    for relation in equivalent.relations
                }
                for relation in event["relations"]:
                    relations_by_key.setdefault(
                        (relation["type"], relation["target"], relation.get("target_kind", "note")), relation
                    )
                equivalent.relations = [relations_by_key[key] for key in sorted(relations_by_key)]
                write_note(vault, equivalent)
                event_memory_ids[event["id"]] = [equivalent.id]
                merged += 1
            else:
                preferred_id = _new_note_id(f"key:{memory_key}")
                if preferred_id in notes and normalized_text(notes[preferred_id].body) != normalized_text(event["text"]):
                    preferred_id = _new_note_id(f"event:{event['id']}")
                note = _event_to_note(event, preferred_id, memory_key)
                write_note(vault, note)
                notes[note.id] = note
                event_memory_ids[event["id"]] = [note.id]
            processed += 1
        _regenerate_entities(vault, notes.values())
        _regenerate_memory(vault, notes.values())
        rebuild_index_unlocked(vault)
        return {
            "processed": processed,
            "merged": merged,
            "superseded": superseded,
            "repaired": repaired,
            "conflicts": conflicts,
            "pending": sum(1 for event in events if not _event_is_complete(event, notes)),
            "event_memory_ids": event_memory_ids,
        }


@contextlib.contextmanager
def _connect(path: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE notes (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            title TEXT NOT NULL,
            kind TEXT NOT NULL,
            body TEXT NOT NULL,
            status TEXT NOT NULL,
            privacy TEXT NOT NULL,
            pinned INTEGER NOT NULL,
            revisit_count INTEGER NOT NULL,
            confidence REAL NOT NULL,
            importance REAL NOT NULL,
            tags_json TEXT NOT NULL,
            entities_json TEXT NOT NULL,
            relations_json TEXT NOT NULL,
            source_event_ids_json TEXT NOT NULL,
            supersedes_json TEXT NOT NULL,
            superseded_by TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            memory_key TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            embedding_json TEXT,
            embedding_model TEXT,
            embedding_dim INTEGER,
            embedding_hash TEXT
        );
        CREATE TABLE links (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            PRIMARY KEY(source_id, target_id, relation_type)
        );
        CREATE TABLE entities (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE notes_fts USING fts5(id UNINDEXED, title, body, tags, entities, tokenize='unicode61');
        """
    )


def _resolve_wikilink(target: str, notes: dict[str, Note]) -> str | None:
    if target in notes:
        return target
    matches = [note.id for note in notes.values() if note.title.casefold() == target.casefold()]
    return matches[0] if len(matches) == 1 else None


def _collect_links(notes: dict[str, Note]) -> tuple[list[tuple[str, str, str]], dict[str, tuple[str, str]]]:
    links: set[tuple[str, str, str]] = set()
    entities: dict[str, tuple[str, str]] = {}
    for note in notes.values():
        for entity in note.entities:
            target = entity_id(entity["type"], entity["name"])
            candidate = (entity["name"], entity["type"])
            current = entities.get(target)
            if current is None or (candidate[0].casefold(), candidate[0]) < (current[0].casefold(), current[0]):
                entities[target] = candidate
    for note in notes.values():
        for entity in note.entities:
            target = entity_id(entity["type"], entity["name"])
            if target != note.id:
                links.add((note.id, target, "mentions"))
        for relation in note.relations:
            target = relation["target"]
            if relation.get("target_kind") == "entity" and not target.startswith("ent_"):
                matching = [identifier for identifier, (name, _) in entities.items() if name.casefold() == target.casefold()]
                if matching:
                    target = matching[0]
            if target != note.id:
                links.add((note.id, target, relation["type"]))
        for raw_target in WIKILINK_RE.findall(note.body):
            target = _resolve_wikilink(raw_target.strip(), notes)
            if target and target != note.id:
                links.add((note.id, target, "wikilink"))
    return sorted(links), entities


def rebuild_index_unlocked(vault: Path) -> dict[str, Any]:
    notes = load_notes(vault)
    _assert_notes_safe_for_derivation(notes.values())
    index_path = vault / "index.sqlite3"
    old_embeddings: dict[str, tuple[Any, ...]] = {}
    if index_path.exists():
        try:
            with _connect(index_path) as old:
                for row in old.execute(
                    "SELECT id,embedding_json,embedding_model,embedding_dim,embedding_hash,content_hash FROM notes WHERE embedding_json IS NOT NULL"
                ):
                    old_embeddings[row["id"]] = tuple(row)
        except sqlite3.Error:
            old_embeddings = {}
    fd, temp_name = tempfile.mkstemp(prefix=".index.", suffix=".sqlite3", dir=vault)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with _connect(temp_path) as connection:
            _create_schema(connection)
            for note in sorted(notes.values(), key=lambda candidate: candidate.id):
                embedding = old_embeddings.get(note.id)
                embedding_values: tuple[Any, Any, Any, Any] = (None, None, None, None)
                if embedding and embedding[4] == note.embedding_content_hash:
                    embedding_values = (embedding[1], embedding[2], embedding[3], embedding[4])
                connection.execute(
                    """INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        note.id,
                        str(note.path.relative_to(vault)) if note.path else "",
                        note.title,
                        note.kind,
                        note.body,
                        note.status,
                        note.privacy,
                        int(note.pinned),
                        note.revisit_count,
                        note.confidence,
                        note.importance,
                        json.dumps(note.tags, ensure_ascii=False),
                        json.dumps(note.entities, ensure_ascii=False),
                        json.dumps(note.relations, ensure_ascii=False),
                        json.dumps(note.source_event_ids, ensure_ascii=False),
                        json.dumps(note.supersedes, ensure_ascii=False),
                        note.superseded_by,
                        note.created_at,
                        note.updated_at,
                        note.memory_key,
                        note.content_hash,
                        *embedding_values,
                    ),
                )
                connection.execute(
                    "INSERT INTO notes_fts(id,title,body,tags,entities) VALUES(?,?,?,?,?)",
                    (
                        note.id,
                        note.title,
                        note.body,
                        " ".join(note.tags),
                        " ".join(entity["name"] for entity in note.entities),
                    ),
                )
            links, entities = _collect_links(notes)
            connection.executemany("INSERT OR IGNORE INTO links VALUES(?,?,?)", links)
            connection.executemany(
                "INSERT OR IGNORE INTO entities(id,name,type) VALUES(?,?,?)",
                [(identifier, name, entity_type) for identifier, (name, entity_type) in sorted(entities.items())],
            )
            connection.commit()
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise MemorizerError(f"rebuilt index failed integrity check: {integrity}")
        try:
            replace_file(temp_path, index_path)
        except OSError as exc:
            raise MemorizerError(f"cannot replace the derived search index: {exc}") from exc
    finally:
        temp_path.unlink(missing_ok=True)
    return {"notes": len(notes), "index": str(index_path)}


def rebuild_index(root: str | Path) -> dict[str, Any]:
    vault = vault_path(root)
    if not (vault / "config.json").exists():
        init_vault(root)
    with vault_lock(vault):
        notes = load_notes(vault)
        _assert_notes_safe_for_derivation(notes.values())
        _regenerate_entities(vault, notes.values())
        _regenerate_memory(vault, notes.values())
        return rebuild_index_unlocked(vault)


def _query_tokens(query: str) -> list[str]:
    return [token.casefold() for token in TOKEN_RE.findall(unicodedata.normalize("NFKC", query)) if token]


def _fts_query(tokens: list[str]) -> str:
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def _cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return max(-1.0, min(1.0, numerator / (left_norm * right_norm)))


def _embedding_settings(config: dict[str, Any]) -> tuple[str, str, float]:
    embedding = config.get("embedding", {})
    url = os.environ.get("MEMORIZER_EMBEDDING_URL", embedding.get("url", "")).strip()
    model = os.environ.get("MEMORIZER_EMBEDDING_MODEL", embedding.get("model", "")).strip()
    timeout = float(embedding.get("timeout_seconds", 4))
    return url, model, timeout


def _embed(texts: list[str], config: dict[str, Any]) -> tuple[list[list[float]], str | None]:
    url, model, timeout = _embedding_settings(config)
    if not url or not model or not texts:
        return [], None
    try:
        endpoint = canonicalize_lm_studio_url(url)
    except ValueError:
        return [], "semantic search disabled: embedding endpoint is not loopback-only"
    if not endpoint.endswith("/v1/embeddings"):
        endpoint += "/v1/embeddings"
    api_key = os.environ.get("MEMORIZER_EMBEDDING_API_KEY")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with httpx.Client(
            timeout=timeout,
            headers=headers,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.post(
                endpoint,
                json={"model": model, "input": texts},
            )
            response.raise_for_status()
            payload = response.json()
        raw_rows = payload["data"]
        if not isinstance(raw_rows, list) or len(raw_rows) != len(texts):
            raise ValueError("embedding response row count mismatch")
        indexes = [row.get("index") if isinstance(row, dict) else None for row in raw_rows]
        if (
            any(isinstance(index, bool) or not isinstance(index, int) for index in indexes)
            or sorted(indexes) != list(range(len(texts)))
        ):
            raise ValueError("embedding response indexes are missing, duplicated, or out of range")
        rows = sorted(raw_rows, key=lambda item: item["index"])
        vectors = [[float(value) for value in row["embedding"]] for row in rows]
        dimension = len(vectors[0]) if vectors else 0
        if len(vectors) != len(texts) or not dimension or any(len(vector) != dimension for vector in vectors):
            raise ValueError("embedding response shape mismatch")
        if any(not math.isfinite(value) for vector in vectors for value in vector):
            raise ValueError("embedding response contains non-finite values")
        return vectors, None
    except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return [], f"semantic search unavailable: {type(exc).__name__}"


def _search_snapshot(
    root: str | Path, query: str, include_superseded: bool
) -> tuple[list[dict[str, Any]], dict[str, float], set[str], dict[str, Any]]:
    vault = vault_path(root)
    tokens = _query_tokens(query)
    with vault_lock(vault):
        _raise_if_derived_stale(vault)
        config = load_config(vault)
        with _connect(vault / "index.sqlite3") as connection:
            status_predicate = (
                "n.status IN ('active','superseded')" if include_superseded else "n.status='active'"
            )
            if tokens:
                sql = f"""
                    SELECT n.*, bm25(notes_fts) AS fts_rank
                    FROM notes_fts JOIN notes n ON n.id=notes_fts.id
                    WHERE {status_predicate} AND notes_fts MATCH ?
                    ORDER BY fts_rank, n.id LIMIT 200
                """
                rows = [dict(row) for row in connection.execute(sql, (_fts_query(tokens),))]
            else:
                rows = []
            fts_rank_by_id = {row["id"]: float(row["fts_rank"]) for row in rows}
            ranked_values = list(fts_rank_by_id.values())
            best_rank = min(ranked_values) if ranked_values else 0.0
            worst_rank = max(ranked_values) if ranked_values else 0.0
            bm25_by_id = {
                identifier: (
                    1.0
                    if best_rank == worst_rank
                    else max(0.0, min(1.0, (worst_rank - rank) / (worst_rank - best_rank)))
                )
                for identifier, rank in fts_rank_by_id.items()
            }
            seed_ids = set(list(fts_rank_by_id)[:10])
            matched_entity_ids = {
                row["id"]
                for row in connection.execute("SELECT id,name FROM entities ORDER BY id")
                if set(tokens) & set(_query_tokens(row["name"]))
            }
            graph_note_ids: set[str] = set()
            graph_seeds = seed_ids | matched_entity_ids
            for link_row in connection.execute("SELECT source_id,target_id FROM links"):
                if link_row["source_id"] in graph_seeds:
                    graph_note_ids.add(link_row["target_id"])
                if link_row["target_id"] in graph_seeds:
                    graph_note_ids.add(link_row["source_id"])
            by_id = {row["id"]: row for row in rows}
            if graph_note_ids:
                placeholders = ",".join("?" for _ in graph_note_ids)
                for row in connection.execute(
                    f"SELECT n.*, 0.0 AS fts_rank FROM notes n WHERE {status_predicate} AND n.id IN ({placeholders}) ORDER BY n.id",
                    tuple(sorted(graph_note_ids)),
                ):
                    by_id.setdefault(row["id"], dict(row))
            url, model, _ = _embedding_settings(config)
            if url and model:
                for row in connection.execute(
                    f"SELECT n.*, 0.0 AS fts_rank FROM notes n WHERE {status_predicate} ORDER BY n.id"
                ):
                    by_id.setdefault(row["id"], dict(row))
            return list(by_id.values()), bm25_by_id, graph_note_ids, config


def _row_embedding_content_hash(row: dict[str, Any]) -> str:
    try:
        tags = json.loads(row["tags_json"])
        entities = json.loads(row["entities_json"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise sqlite3.DatabaseError("invalid derived embedding data") from exc
    return _embedding_content_hash(row["title"], row["body"], tags, entities)


def _cache_embeddings(
    root: str | Path, model: str, updates: list[tuple[str, list[float], str, str]]
) -> str | None:
    if not updates:
        return None
    vault = vault_path(root)
    try:
        with vault_lock(vault):
            with _connect(vault / "index.sqlite3") as connection:
                for note_id, vector, embedding_hash, content_hash in updates:
                    connection.execute(
                        """UPDATE notes SET embedding_json=?,embedding_model=?,embedding_dim=?,embedding_hash=?
                           WHERE id=? AND content_hash=?""",
                        (
                            json.dumps(vector, separators=(",", ":")),
                            model,
                            len(vector),
                            embedding_hash,
                            note_id,
                            content_hash,
                        ),
                    )
    except (MemorizerError, sqlite3.Error):
        return "semantic results succeeded, but the embedding cache could not be updated"
    return None


def _search_unlocked(root: str | Path, query: str, limit: int, include_superseded: bool) -> dict[str, Any]:
    if not _normalize_space(query):
        raise MemorizerError("search query cannot be empty")
    if not 1 <= limit <= 100:
        raise MemorizerError("search limit must be between 1 and 100")
    vault = vault_path(root)
    tokens = _query_tokens(query)
    rows, bm25_by_id, graph_note_ids, config = _search_snapshot(root, query, include_superseded)
    url, model, _ = _embedding_settings(config)
    semantic_warning: str | None = None
    query_vector: list[float] | None = None
    if url and model:
        vectors, semantic_warning = _embed([query], config)
        query_vector = vectors[0] if vectors else None
    embedding_by_id: dict[str, list[float]] = {}
    cache_updates: list[tuple[str, list[float], str, str]] = []
    if query_vector is not None:
        missing: list[dict[str, Any]] = []
        for row in rows:
            if (
                row["embedding_json"]
                and row["embedding_model"] == model
                and row["embedding_dim"] == len(query_vector)
                and row["embedding_hash"] == _row_embedding_content_hash(row)
            ):
                try:
                    vector = [float(value) for value in json.loads(row["embedding_json"])]
                    if len(vector) == len(query_vector) and all(math.isfinite(value) for value in vector):
                        embedding_by_id[row["id"]] = vector
                        continue
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            missing.append(row)
        for offset in range(0, len(missing), 64):
            batch = missing[offset : offset + 64]
            vectors, warning = _embed([f"{row['title']}\n{row['body']}" for row in batch], config)
            if warning or any(len(vector) != len(query_vector) for vector in vectors):
                semantic_warning = warning or "semantic search unavailable: embedding dimension mismatch"
                query_vector = None
                embedding_by_id.clear()
                cache_updates.clear()
                break
            for row, vector in zip(batch, vectors):
                embedding_by_id[row["id"]] = vector
                cache_updates.append(
                    (row["id"], vector, _row_embedding_content_hash(row), row["content_hash"])
                )
    cache_warning = _cache_embeddings(root, model, cache_updates) if query_vector is not None else None
    semantic_warning = semantic_warning or cache_warning
    results: list[dict[str, Any]] = []
    now = dt.datetime.now(dt.timezone.utc)
    for row in rows:
        haystack_text = " ".join([row["title"], row["body"], row["tags_json"], row["entities_json"]])
        haystack_tokens = _query_tokens(haystack_text)
        haystack_token_set = set(haystack_tokens)
        overlap = sum(1 for token in tokens if token in haystack_token_set) / max(1, len(tokens))
        phrase = (
            1.0
            if tokens
            and any(
                haystack_tokens[offset : offset + len(tokens)] == tokens
                for offset in range(len(haystack_tokens) - len(tokens) + 1)
            )
            else 0.0
        )
        bm25 = bm25_by_id.get(row["id"], 0.0)
        lexical = min(1.0, overlap * 0.55 + phrase * 0.20 + bm25 * 0.25)
        semantic = 0.0
        if query_vector is not None and row["id"] in embedding_by_id:
            semantic = max(0.0, _cosine(query_vector, embedding_by_id[row["id"]]))
        age_days = max(0.0, (now - parse_time(row["updated_at"])).total_seconds() / 86400)
        recency = math.exp(-age_days / 90)
        revisit = min(1.0, math.log1p(row["revisit_count"]) / math.log(11))
        pin_factor = 1.0 if row["pinned"] else 0.0
        try:
            related_entities = json.loads(row["entities_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise sqlite3.DatabaseError("invalid derived entity data") from exc
        graph_factor = 1.0 if row["id"] in graph_note_ids else 0.0
        weights = dict(config["ranking"])
        if query_vector is None:
            weights["lexical"] += weights.get("semantic", 0.0)
            weights["semantic"] = 0.0
        factors = {
            "lexical": lexical,
            "semantic": semantic,
            "recency": recency,
            "revisit": revisit,
            "pin": pin_factor,
            "graph": graph_factor,
            "bm25": bm25,
        }
        score = sum(float(weights.get(name, 0.0)) * value for name, value in factors.items())
        if lexical <= 0 and semantic < 0.20 and graph_factor <= 0:
            continue
        results.append(
            {
                "id": row["id"],
                "path": str(vault / row["path"]),
                "title": row["title"],
                "kind": row["kind"],
                "status": row["status"],
                "privacy": row["privacy"],
                "excerpt": row["body"][:400],
                "related_entities": related_entities,
                "score": round(score, 6),
                "factors": {name: round(value, 6) for name, value in factors.items()},
            }
        )
    results.sort(key=lambda item: (-item["score"], item["id"]))
    return {"query": query, "results": results[:limit], "semantic_warning": semantic_warning}


def search(root: str | Path, query: str, limit: int = 10, include_superseded: bool = False) -> dict[str, Any]:
    vault = vault_path(root)
    if not (vault / "config.json").exists():
        init_vault(root)
    for attempt in range(3):
        try:
            return _search_unlocked(root, query, limit, include_superseded)
        except _DerivedStateStale as exc:
            if attempt < 2:
                if exc.pending_events:
                    distill(root)
                else:
                    rebuild_index(root)
                continue
            raise MemorizerError("search could not make the derived memory state current") from exc
        except sqlite3.Error as exc:
            if attempt < 2:
                rebuild_index(root)
                continue
            raise MemorizerError(f"search index could not be recovered: {exc}") from exc
    raise MemorizerError("search index could not be recovered")


def _update_note(root: str | Path, note_id: str, operation: str, value: Any = None) -> Note:
    vault = vault_path(root)
    with vault_lock(vault):
        notes = load_notes(vault)
        _assert_notes_safe_for_derivation(notes.values())
        note = notes.get(note_id)
        if note is None:
            raise MemorizerError(f"memory {note_id!r} was not found")
        if operation == "touch":
            note.revisit_count += 1
        elif operation == "pin":
            note.pinned = bool(value)
        else:
            raise MemorizerError(f"unsupported note update {operation}")
        note.updated_at = utc_now()
        write_note(vault, note)
        _regenerate_memory(vault, notes.values())
        rebuild_index_unlocked(vault)
        return note


def show(root: str | Path, note_id: str, touch: bool = True) -> dict[str, Any]:
    vault = vault_path(root)
    if touch:
        return note_as_dict(_update_note(root, note_id, "touch"))
    with vault_lock(vault):
        notes = load_notes(vault)
        _assert_notes_safe_for_derivation(notes.values())
        note = notes.get(note_id)
        if note is None:
            raise MemorizerError(f"memory {note_id!r} was not found")
        return note_as_dict(note)


def pin(root: str | Path, note_id: str, pinned: bool = True) -> dict[str, Any]:
    return note_as_dict(_update_note(root, note_id, "pin", pinned))


def touch(root: str | Path, note_id: str) -> dict[str, Any]:
    return note_as_dict(_update_note(root, note_id, "touch"))


def link(root: str | Path, source_id: str, target_id: str, relation_type: str) -> dict[str, Any]:
    if not isinstance(source_id, str) or not _normalize_space(source_id):
        raise MemorizerError("source memory id must be a non-empty string")
    if not isinstance(target_id, str) or not _normalize_space(target_id):
        raise MemorizerError("target id must be a non-empty string")
    if not isinstance(relation_type, str) or not _normalize_space(relation_type):
        raise MemorizerError("relation type must be a non-empty string")
    if source_id == target_id:
        raise MemorizerError("self-links are not allowed")
    vault = vault_path(root)
    with vault_lock(vault):
        notes = load_notes(vault)
        source = notes.get(source_id)
        if source is None:
            raise MemorizerError(f"source memory {source_id!r} was not found")
        known_entities = {entity_id(entity["type"], entity["name"]) for note in notes.values() for entity in note.entities}
        if target_id not in notes and target_id not in known_entities:
            raise MemorizerError(f"target {target_id!r} was not found")
        relation = {"type": slugify(relation_type, "related-to"), "target": target_id, "target_kind": "entity" if target_id.startswith("ent_") else "note"}
        if relation not in source.relations:
            source.relations.append(relation)
            source.relations.sort(key=lambda item: (item["target"], item["type"]))
            source.updated_at = utc_now()
            write_note(vault, source)
            rebuild_index_unlocked(vault)
        return {"source": source_id, "target": target_id, "type": relation["type"]}


def _backlinks_unlocked(root: str | Path, target_id: str) -> dict[str, Any]:
    vault = vault_path(root)
    with _connect(vault / "index.sqlite3") as connection:
        rows = list(
            connection.execute(
                """SELECT DISTINCT l.source_id,n.title,l.relation_type
                   FROM links l LEFT JOIN notes n ON n.id=l.source_id
                   WHERE l.target_id=? ORDER BY l.source_id,l.relation_type""",
                (target_id,),
            )
        )
    return {"target": target_id, "backlinks": [dict(row) for row in rows]}


def _graph_unlocked(root: str | Path, output_format: str = "json") -> str | dict[str, Any]:
    vault = vault_path(root)
    with _connect(vault / "index.sqlite3") as connection:
        note_rows = list(connection.execute("SELECT id,title,status FROM notes ORDER BY id"))
        entity_rows = list(connection.execute("SELECT id,name,type FROM entities ORDER BY id"))
        link_rows = list(connection.execute("SELECT source_id,target_id,relation_type FROM links ORDER BY source_id,target_id,relation_type"))
    nodes = [
        {"id": row["id"], "label": row["title"], "kind": "note", "status": row["status"]} for row in note_rows
    ] + [{"id": row["id"], "label": row["name"], "kind": row["type"], "status": "active"} for row in entity_rows]
    edges = [{"source": row["source_id"], "target": row["target_id"], "type": row["relation_type"]} for row in link_rows]
    payload = {"nodes": nodes, "edges": edges}
    if output_format == "json":
        return payload
    if output_format != "mermaid":
        raise MemorizerError("graph format must be json or mermaid")
    identifiers = {node["id"]: f"n{index}" for index, node in enumerate(nodes)}

    def safe_label(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', "'").replace("\n", " ").replace("[", "(").replace("]", ")")

    lines = ["flowchart LR"]
    for node in nodes:
        lines.append(f'  {identifiers[node["id"]]}["{safe_label(node["label"])}"]')
    for edge in edges:
        if edge["source"] in identifiers and edge["target"] in identifiers:
            lines.append(
                f'  {identifiers[edge["source"]]} -->|"{safe_label(edge["type"])}"| {identifiers[edge["target"]]}'
            )
    return "\n".join(lines) + "\n"


def backlinks(root: str | Path, target_id: str) -> dict[str, Any]:
    vault = vault_path(root)
    if not (vault / "config.json").exists():
        init_vault(root)
    for attempt in range(3):
        try:
            with vault_lock(vault):
                _raise_if_derived_stale(vault)
                return _backlinks_unlocked(root, target_id)
        except _DerivedStateStale as exc:
            if attempt < 2:
                if exc.pending_events:
                    distill(root)
                else:
                    rebuild_index(root)
                continue
            raise MemorizerError("backlink reader could not make derived memory state current") from exc
        except sqlite3.Error as exc:
            if attempt < 2:
                rebuild_index(root)
                continue
            raise MemorizerError(f"backlink index could not be recovered: {exc}") from exc
    raise MemorizerError("backlink index could not be recovered")


def graph(root: str | Path, output_format: str = "json") -> str | dict[str, Any]:
    vault = vault_path(root)
    if not (vault / "config.json").exists():
        init_vault(root)
    for attempt in range(3):
        try:
            with vault_lock(vault):
                _raise_if_derived_stale(vault)
                return _graph_unlocked(root, output_format)
        except _DerivedStateStale as exc:
            if attempt < 2:
                if exc.pending_events:
                    distill(root)
                else:
                    rebuild_index(root)
                continue
            raise MemorizerError("graph reader could not make derived memory state current") from exc
        except sqlite3.Error as exc:
            if attempt < 2:
                rebuild_index(root)
                continue
            raise MemorizerError(f"graph index could not be recovered: {exc}") from exc
    raise MemorizerError("graph index could not be recovered")


def note_as_dict(note: Note) -> dict[str, Any]:
    return {
        "id": note.id,
        "title": note.title,
        "kind": note.kind,
        "body": note.body,
        "status": note.status,
        "privacy": note.privacy,
        "pinned": note.pinned,
        "revisit_count": note.revisit_count,
        "confidence": note.confidence,
        "importance": note.importance,
        "tags": note.tags,
        "entities": note.entities,
        "relations": note.relations,
        "source_event_ids": note.source_event_ids,
        "supersedes": note.supersedes,
        "superseded_by": note.superseded_by,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
        "path": str(note.path) if note.path else None,
    }


def _validate_vault_unlocked(root: str | Path) -> dict[str, Any]:
    vault = vault_path(root)
    errors: list[str] = []
    if not vault.exists():
        return {"valid": False, "errors": [f"vault does not exist: {vault}"]}
    config_path = vault / "config.json"
    if not config_path.is_file():
        errors.append(f"required vault file is missing: {config_path}")
    else:
        try:
            load_config(vault)
        except MemorizerError as exc:
            errors.append(str(exc))
    for directory_name in ("daily", "notes", "entities"):
        directory = vault / directory_name
        if not directory.is_dir():
            errors.append(f"required vault directory is missing: {directory}")
    try:
        events = list(iter_events(vault))
    except MemorizerError as exc:
        events = []
        errors.append(str(exc))
    event_ids: set[str] = set()
    for event in events:
        identifier = event.get("id")
        if identifier in event_ids:
            errors.append(f"duplicate event id {identifier!r}")
        event_ids.add(identifier)
        try:
            parse_time(event.get("captured_at", ""))
        except MemorizerError as exc:
            errors.append(f"event {identifier}: {exc}")
    try:
        notes = load_notes(vault)
    except MemorizerError as exc:
        notes = {}
        errors.append(str(exc))
    known_entities = {entity_id(entity["type"], entity["name"]) for note in notes.values() for entity in note.entities}
    for note in notes.values():
        if not SAFE_ID_RE.fullmatch(note.id):
            errors.append(f"{note.path}: invalid memory id {note.id!r}")
        if note.kind not in SIGNAL_KINDS:
            errors.append(f"{note.path}: invalid type {note.kind!r}")
        if note.status not in {"active", "superseded", "rejected"}:
            errors.append(f"{note.path}: invalid status {note.status!r}")
        if note.privacy not in PRIVACY_LEVELS:
            errors.append(f"{note.path}: invalid privacy {note.privacy!r}")
        if not 0 <= note.confidence <= 1:
            errors.append(f"{note.path}: confidence must be between 0 and 1")
        if not 0 <= note.importance <= 1:
            errors.append(f"{note.path}: importance must be between 0 and 1")
        for entity in note.entities:
            if not isinstance(entity, dict) or entity.get("type") not in ENTITY_TYPES or not entity.get("name"):
                errors.append(f"{note.path}: invalid entity {entity!r}")
        for timestamp in (note.created_at, note.updated_at):
            try:
                parse_time(timestamp)
            except MemorizerError as exc:
                errors.append(f"{note.path}: {exc}")
        for source_id in note.source_event_ids:
            if source_id not in event_ids:
                errors.append(f"{note.path}: missing source event {source_id!r}")
        if note.status == "superseded":
            successor = notes.get(note.superseded_by or "")
            if successor is None:
                errors.append(f"{note.path}: missing superseding memory {note.superseded_by!r}")
            elif note.id not in successor.supersedes:
                errors.append(f"{note.path}: superseding memory {successor.id!r} lacks reciprocal lineage")
        elif note.superseded_by:
            errors.append(f"{note.path}: non-superseded memory cannot set superseded_by")
        if note.status != "rejected":
            for target_id in note.supersedes:
                target = notes.get(target_id)
                if target is None:
                    errors.append(f"{note.path}: missing superseded memory {target_id!r}")
                elif target.status != "superseded" or target.superseded_by != note.id:
                    errors.append(f"{note.path}: supersession of {target_id!r} is not reciprocal")
        for relation in note.relations:
            target = relation.get("target")
            if target == note.id:
                errors.append(f"{note.path}: self relation {relation.get('type')!r}")
            elif target not in notes and target not in known_entities:
                errors.append(f"{note.path}: missing relation target {target!r}")
        for raw_target in WIKILINK_RE.findall(note.body):
            if _resolve_wikilink(raw_target.strip(), notes) is None:
                errors.append(f"{note.path}: unresolved wikilink {raw_target!r}")
    for starting_id in notes:
        seen: set[str] = set()
        current = starting_id
        while current in notes and notes[current].superseded_by:
            if current in seen:
                errors.append(f"supersession cycle includes memory {current!r}")
                break
            seen.add(current)
            current = notes[current].superseded_by or ""
    for event in events:
        if not _event_is_complete(event, notes):
            errors.append(f"event {event.get('id')!r} is pending or incompletely distilled")
    for path in sorted(vault.rglob("*")):
        if path.is_file() and path.suffix.casefold() in {".md", ".json"}:
            try:
                raw = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"cannot scan {path} for secrets: {exc}")
                continue
            safe_raw, _ = redact_text(raw)
            if safe_raw != raw:
                errors.append(f"{path}: contains an unredacted credential pattern")
    index_path = vault / "index.sqlite3"
    if index_path.exists():
        try:
            with _connect(index_path) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    errors.append(f"index integrity check failed: {integrity}")
        except sqlite3.Error as exc:
            errors.append(f"cannot validate index: {exc}")
        if not _index_is_current(vault, notes):
            errors.append("Markdown notes and derived index tables have drifted; run rebuild")
    else:
        errors.append("index.sqlite3 is missing; run rebuild")
    if not _generated_views_are_current(vault, notes):
        errors.append("generated MEMORY.md or entity views have drifted; run rebuild")
    return {"valid": not errors, "errors": errors, "events": len(events), "notes": len(notes)}


def validate_vault(root: str | Path) -> dict[str, Any]:
    vault = vault_path(root)
    if not vault.exists():
        return {"valid": False, "errors": [f"vault does not exist: {vault}"]}
    with vault_lock(vault):
        return _validate_vault_unlocked(root)


def status(root: str | Path) -> dict[str, Any]:
    vault = vault_path(root)
    if not vault.exists():
        return {
            "vault": str(vault),
            "events": 0,
            "memories": 0,
            "active": 0,
            "superseded": 0,
            "rejected": 0,
            "pending_events": 0,
            "derived_stale": False,
            "pending": 0,
        }
    with vault_lock(vault):
        events = list(iter_events(vault))
        notes = load_notes(vault) if (vault / "notes").exists() else {}
        pending_events = sum(1 for event in events if not _event_is_complete(event, notes))
        derived_stale = not _index_is_current(vault, notes) or not _generated_views_are_current(vault, notes)
        return {
            "vault": str(vault),
            "events": len(events),
            "memories": len(notes),
            "active": sum(1 for note in notes.values() if note.status == "active"),
            "superseded": sum(1 for note in notes.values() if note.status == "superseded"),
            "rejected": sum(1 for note in notes.values() if note.status == "rejected"),
            "pending_events": pending_events,
            "derived_stale": derived_stale,
            "pending": pending_events + int(derived_stale),
        }
