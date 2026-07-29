# Project memory vault

Markdown is authoritative. SQLite and generated views are rebuildable derived state.

```text
PROJECT_ROOT\
└── .memorizer\
    ├── config.json
    ├── .write.lock
    ├── MEMORY.md
    ├── daily\YYYY-MM-DD.md
    ├── notes\<slug>--<stable-id>.md
    ├── entities\<type>\<slug>--<stable-id>.md
    └── index.sqlite3
```

The path is owned by `.local-knowledge/project.toml` and must remain inside the project root. Do not place company repositories or shared cross-project memory inside it.

## Capture object

Required shape:

```json
{
  "kind": "preference",
  "title": "Concise status updates",
  "text": "The user prefers concise status updates.",
  "memory_key": "communication:status-update-detail"
}
```

Optional fields are `id`, `captured_at`, `tags`, `entities`, `relations`, `confidence`, `importance`, `privacy`, `pinned`, `supersedes`, and `source`. Entity objects contain `name` and a supported `type`. Relations contain `type`, stable `target`, and `target_kind` (`note` or `entity`).

Daily files are append-only logical audit logs written atomically. Curated notes use JSON-valued YAML frontmatter so Unicode and arbitrary titles cannot inject fields. Unknown frontmatter survives supported metadata updates.

`MEMORY.md` and entity hubs are generated views. Edit a source note only for supported repair, then run `rebuild` and `validate`. Do not manually edit `index.sqlite3` or delete `.write.lock`.

FTS5 is always available. Optional local embeddings use `MEMORIZER_EMBEDDING_URL`, `MEMORIZER_EMBEDDING_MODEL`, and an API key supplied only through `MEMORIZER_EMBEDDING_API_KEY`. Endpoint failure must fall back to lexical search without changing authoritative notes.

## Portable snapshot

Snapshot export is a deterministic, plain-text projection rather than a vault
copy:

```text
memory-snapshot\
├── snapshot.json
└── memory\
    ├── config.json
    └── notes\
        └── <selected-note>.md
```

`snapshot.json` records schema, project identity, metadata, and SHA-256 for each
payload file. Export excludes daily heartbeats, `index.sqlite3`, `.write.lock`,
`MEMORY.md`, entity hubs, caches, and every other generated view.

Import verifies the manifest, exact file set, hashes, and matching project ID
before writing. An ordinary import requires an empty vault. `--replace` creates
a local backup before replacement. Rebuild derived state after import; never
treat snapshot metadata as Memory content.
