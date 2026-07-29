# SPDX-FileCopyrightText: 2026 John-IDK
# SPDX-License-Identifier: MIT

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Iterator

from ..winio import unlink_file


SCHEMA_VERSION = 2

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','reviewer','reader')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  csrf_token TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS branches (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  is_canonical INTEGER NOT NULL DEFAULT 0,
  protected INTEGER NOT NULL DEFAULT 1,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS branch_members (
  branch_id INTEGER NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('admin','reviewer','reader')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(branch_id,user_id)
);
CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('file','folder','website')),
  uri TEXT NOT NULL,
  title TEXT,
  allowed_domains TEXT NOT NULL DEFAULT '[]',
  branch_id INTEGER NOT NULL DEFAULT 1 REFERENCES branches(id),
  enabled INTEGER NOT NULL DEFAULT 1,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(kind, uri, branch_id)
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','succeeded','failed','cancelled')),
  attempts INTEGER NOT NULL DEFAULT 0,
  worker_id TEXT,
  lease_token TEXT,
  lease_until TEXT,
  heartbeat_at TEXT,
  cancel_requested_at TEXT,
  error TEXT,
  result_json TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  branch_id INTEGER NOT NULL DEFAULT 1 REFERENCES branches(id),
  source_uri TEXT NOT NULL,
  title TEXT NOT NULL,
  media_type TEXT NOT NULL,
  checksum TEXT NOT NULL,
  language TEXT NOT NULL,
  normalized_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(source_id, source_uri, checksum)
);
CREATE TABLE IF NOT EXISTS concepts (
  id TEXT PRIMARY KEY,
  document_id INTEGER REFERENCES documents(id),
  branch_id INTEGER NOT NULL DEFAULT 1 REFERENCES branches(id),
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  body TEXT NOT NULL,
  tags_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL CHECK(status IN ('review','published','rejected')),
  quality_json TEXT NOT NULL,
  path TEXT,
  maturity REAL NOT NULL DEFAULT 0.5,
  pagerank REAL NOT NULL DEFAULT 0.0,
  legacy INTEGER NOT NULL DEFAULT 0,
  canonical_commit TEXT,
  endorsements INTEGER NOT NULL DEFAULT 0,
  usage_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY,
  concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  confidence REAL NOT NULL,
  document_checksum TEXT,
  source_uri TEXT,
  locator TEXT,
  excerpt TEXT,
  citations_json TEXT NOT NULL,
  verified INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  concept_id TEXT REFERENCES concepts(id) ON DELETE CASCADE,
  locator TEXT NOT NULL,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  checksum TEXT NOT NULL,
  UNIQUE(document_id, locator, checksum)
);
CREATE TABLE IF NOT EXISTS embeddings (
  concept_id TEXT PRIMARY KEY REFERENCES concepts(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  vector_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chunk_embeddings (
  chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
  model TEXT NOT NULL,
  vector_json TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT,
  normalized_name TEXT NOT NULL UNIQUE,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  pagerank REAL NOT NULL DEFAULT 0.0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS concept_entities (
  concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
  entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  PRIMARY KEY(concept_id, entity_id)
);
CREATE TABLE IF NOT EXISTS concept_links (
  source_concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
  target_concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
  PRIMARY KEY(source_concept_id,target_concept_id)
);
CREATE TABLE IF NOT EXISTS publications (
  id TEXT PRIMARY KEY,
  concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
  branch_id INTEGER NOT NULL REFERENCES branches(id),
  candidate_branch TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('pending','committed','applied','pushed','abandoned')),
  idempotency_key TEXT NOT NULL UNIQUE,
  commit_hash TEXT,
  error TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS audits (
  id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  branch_id INTEGER REFERENCES branches(id),
  action TEXT NOT NULL,
  target_type TEXT,
  target_id TEXT,
  publication_id TEXT,
  commit_hash TEXT,
  outcome TEXT NOT NULL,
  details_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS endorsements (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(user_id,concept_id)
);
CREATE TABLE IF NOT EXISTS usage_events (
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  concept_id TEXT NOT NULL REFERENCES concepts(id) ON DELETE CASCADE,
  usage_day TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(user_id,concept_id,usage_day)
);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  query TEXT NOT NULL,
  details TEXT NOT NULL DEFAULT '',
  concept_id TEXT REFERENCES concepts(id),
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
  resolved_by INTEGER REFERENCES users(id),
  resolved_at TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS secret_records (
  id INTEGER PRIMARY KEY,
  owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  ciphertext BLOB NOT NULL,
  nonce BLOB NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(owner_user_id,name)
);
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
  concept_id UNINDEXED,
  title,
  body,
  folded,
  tokenize='unicode61 remove_diacritics 0'
);
"""


INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_lease ON jobs(status, lease_until);
CREATE INDEX IF NOT EXISTS idx_concepts_status ON concepts(branch_id,status,updated_at);
CREATE INDEX IF NOT EXISTS idx_chunks_concept ON chunks(concept_id);
CREATE INDEX IF NOT EXISTS idx_publications_state ON publications(state,updated_at);
"""


LEGACY_COLUMNS: dict[str, dict[str, str]] = {
    "sources": {"branch_id": "INTEGER NOT NULL DEFAULT 1"},
    "jobs": {
        "worker_id": "TEXT",
        "lease_token": "TEXT",
        "lease_until": "TEXT",
        "heartbeat_at": "TEXT",
        "cancel_requested_at": "TEXT",
    },
    "documents": {"branch_id": "INTEGER NOT NULL DEFAULT 1"},
    "concepts": {
        "branch_id": "INTEGER NOT NULL DEFAULT 1",
        "pagerank": "REAL NOT NULL DEFAULT 0.0",
        "legacy": "INTEGER NOT NULL DEFAULT 0",
        "canonical_commit": "TEXT",
    },
    "claims": {
        "document_checksum": "TEXT",
        "source_uri": "TEXT",
        "locator": "TEXT",
        "excerpt": "TEXT",
    },
    "entities": {
        "slug": "TEXT",
        "aliases_json": "TEXT NOT NULL DEFAULT '[]'",
        "pagerank": "REAL NOT NULL DEFAULT 0.0",
    },
    "feedback": {"resolved_by": "INTEGER", "resolved_at": "TEXT"},
}


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _open(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def assert_compatible(self) -> int:
        """Read the schema version without mutating the database and reject newer runtimes."""

        if not self.path.is_file():
            return 0
        uri = self.path.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=30)
        try:
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
            ).fetchone()
            if table is None:
                return 0
            row = connection.execute(
                "SELECT value FROM schema_meta WHERE key='version'"
            ).fetchone()
            if row is None:
                return 0
            try:
                version = int(row[0])
            except (TypeError, ValueError) as exc:
                raise RuntimeError("CKB database has an invalid schema version") from exc
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"CKB database schema {version} is newer than supported schema {SCHEMA_VERSION}; "
                    "upgrade the local knowledge runtime"
                )
            return version
        finally:
            connection.close()

    @contextlib.contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.assert_compatible()
        connection = self._open()
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            schema_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
            ).fetchone()
            current_version = 0
            if schema_table is not None:
                row = connection.execute("SELECT value FROM schema_meta WHERE key='version'").fetchone()
                if row is not None:
                    try:
                        current_version = int(row["value"])
                    except (TypeError, ValueError) as exc:
                        raise RuntimeError("CKB database has an invalid schema version") from exc
            if current_version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"CKB database schema {current_version} is newer than supported schema {SCHEMA_VERSION}; "
                    "upgrade the local knowledge runtime"
                )

            connection.execute("PRAGMA journal_mode=WAL")
            try:
                connection.execute("BEGIN IMMEDIATE")
                for raw_statement in SCHEMA.split(";"):
                    statement = raw_statement.strip()
                    if not statement or statement.upper().startswith("PRAGMA JOURNAL_MODE"):
                        continue
                    connection.execute(statement)
                for table, columns in LEGACY_COLUMNS.items():
                    existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
                    for name, declaration in columns.items():
                        if name not in existing:
                            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
                for raw_statement in INDEX_SCHEMA.split(";"):
                    statement = raw_statement.strip()
                    if statement:
                        connection.execute(statement)
                connection.execute(
                    "INSERT INTO branches(id,name,is_canonical,protected) VALUES(1,'main',1,1) ON CONFLICT(id) DO NOTHING"
                )
                connection.execute(
                    "INSERT INTO schema_meta(key,value) VALUES('version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (str(SCHEMA_VERSION),),
                )
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise

    def backup_to(self, target: str | Path) -> Path:
        """Create a consistent SQLite snapshot, including committed WAL pages."""

        if not self.path.is_file():
            raise FileNotFoundError(self.path)
        self.assert_compatible()
        destination = Path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            unlink_file(destination.with_name(destination.name + suffix))
        source = self._open()
        output = sqlite3.connect(destination)
        try:
            source.backup(output)
            integrity = output.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise sqlite3.DatabaseError(f"backup integrity check failed: {integrity}")
        finally:
            output.close()
            source.close()
        return destination

    def restore_from(self, backup: str | Path) -> None:
        """Restore a consistent snapshot after removing any stale live WAL sidecars."""

        source_path = Path(backup)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        Database(source_path).assert_compatible()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        uri = source_path.resolve().as_uri() + "?mode=ro"
        source = sqlite3.connect(uri, uri=True)
        output = sqlite3.connect(self.path, timeout=30)
        try:
            source.backup(output)
            integrity = output.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise sqlite3.DatabaseError(f"restored database integrity check failed: {integrity}")
        finally:
            output.close()
            source.close()
        maintenance = sqlite3.connect(self.path, timeout=30)
        try:
            maintenance.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            maintenance.execute("PRAGMA journal_mode=DELETE")
        finally:
            maintenance.close()
        for suffix in ("-wal", "-shm"):
            unlink_file(self.path.with_name(self.path.name + suffix))

    @contextlib.contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        self.assert_compatible()
        connection = self._open()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
