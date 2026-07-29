# Local Knowledge Suite authority model

## Stores

| Layer | Authority | Scope | Portable form |
| --- | --- | --- | --- |
| Skills | plugin `skills/` | release | installed/vendored plugin |
| Project | project manifest, schema 2 | one project | Git |
| Memory | `.memorizer/` Markdown | one project | reviewed snapshot |
| Company | manifest + canonical `knowledge/` | one company | normally-private Git |
| Machine | registry + Credential Manager | one Windows account | rebuild, never copy |

SQLite, indexes, generated views, caches, locks, job state, and portal state are
derived or operational. Git retains canonical history but does not verify a
source after clone.

## Profiles

- `memory-only`: optional/absent company ID; v1 default.
- `combined`: Memory plus a required registered company.
- `company-only`: required registered company; Memory disabled.

Several projects may reference the same company ID while retaining different
project IDs and Memory. Different companies must never share databases, source
files, credentials, or results.

## Installation

Global mode resolves one installed plugin for many projects. Vendored mode
commits a versioned snapshot, hash lock, and marked project configuration.
Installation mode changes discovery, not ownership.

## Four-tool MCP contract

- `bootstrap_workspace`: idempotently create an absent schema-2 project; never
  create a company or reassign an existing project.
- `knowledge_status`: report runtime/schema compatibility, registration,
  stores, pending Memory, migration, warnings, and snapshot metadata.
- `recall_context`: return separate Skill, Memory, and Company sections.
- `capture_memory`: write only one current-project Memory signal.

## Snapshot contract

A deterministic snapshot contains:

- `snapshot.json` with per-file SHA-256;
- `memory/config.json`; and
- authoritative `memory/notes/*.md`.

It excludes daily journals, SQLite/index, caches, locks, `MEMORY.md`, and entity
views. Sensitive notes are excluded by default. Snapshots are plain text.
Import requires the same project ID and normally an empty vault.

## Shared gates

- Resolve an absolute project root for every operation.
- Search before capture.
- Never store credential values.
- Keep Skill, Memory, and Company results separate.
- Require verified source URI, locator, and excerpt for company facts.
- Stop on schema incompatibility, registry mismatch, source-policy failure,
  pending distillation, vendor hash mismatch, or corrupt snapshot.
