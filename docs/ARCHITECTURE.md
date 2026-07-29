# Architecture

Local Knowledge Suite separates instructions, project context, and company
evidence so one convenient search cannot silently collapse their trust levels.

## Components

```text
Codex
  ├─ three Skills: procedural guidance
  └─ local-knowledge MCP (stdio)
       └─ pinned Python 3.12 runtime
            ├─ project workspace service
            ├─ Memorizer
            └─ Company Knowledge Base + local portal
```

The MCP surface has exactly four tools:

- `bootstrap_workspace`;
- `knowledge_status`;
- `recall_context`; and
- `capture_memory`.

The public tool surface is intentionally small. Advanced recovery, company
ingestion, review, and administration use the pinned CLI.

## Ownership

| Layer | Authoritative data | Scope |
| --- | --- | --- |
| Plugin | `skills/`, runtime, scripts | Installed or vendored release |
| Project | `.local-knowledge/project.toml` | Stable project identity |
| Memory | `.memorizer/` Markdown | One project |
| Company | company manifest and `knowledge/` | One company, many projects |
| Machine | company registry, project authorizations, Credential Manager | One Windows account |

SQLite, indexes, generated views, portal jobs, and caches are derived or
operational state. They are not portable authority.

## Workspace schema 2

The project manifest records a stable project ID, optional company ID, profile,
install mode, and Memory path.

- `memory-only` is the default and permits no company.
- `combined` and `company-only` require a registered company.
- schema 1/0.2 loads only for migration; apply creates a backup.

Project identity and company assignment must not be changed by hand.
For company-enabled profiles, the machine registry also authorizes the exact
`project_id + canonical project root + company_id` tuple. A copied or hand-made
manifest is not authority. `project init` enrolls a project explicitly;
`project restore` explicitly re-enrolls a moved or cloned root.

## Recall data flow

```text
query
  ├─ Skills: workflow matches
  ├─ Memory: project-local notes, sensitive excluded by default
  └─ Company: registered repository search
                └─ citation verification gate
```

The response preserves separate sections and warnings. A company answer may
rely only on `evidence_sufficient` results with verified URI, locator, and
exact excerpt. Memory and Skills never substitute for missing evidence.

## Company source integrity

Approved local sources live under ignored `.local-sources/`. Published local
citation identities use a company-relative `company-source://` URI. Recall
checks the current file SHA-256 and exact excerpt. A missing, changed, or
redirected source fails closed.

Canonical company Markdown and Git retain reviewable history. After clone,
claims remain unverified until authorized sources are restored and ingested on
that machine.

## Memory snapshots

Snapshot export serializes selected authoritative notes as deterministic plain
text with checksums. The manifest fingerprint integrity-binds its schema,
format, project ID, metadata, and canonical file entries. It excludes journals,
SQLite, caches, locks, and generated views. Sensitive notes and
public-repository export require separate explicit acknowledgements. Import
checks project identity, typed metadata, note privacy, and snapshot integrity;
v1 does not merge snapshots. Because SHA-256 is unkeyed here, it detects
unreviewed changes but is not cryptographic proof of snapshot origin.

## Installation

Global installation provides one plugin to many projects. Vendored
installation commits an exact plugin snapshot, its hash lock, real managed
copies of the three skills under `.agents/skills/`, and an MCP-only marked
project configuration block. The lock verifies both the runtime snapshot and
the byte-equivalent managed skill copies. Installation mode changes runtime
discovery, not data ownership.
