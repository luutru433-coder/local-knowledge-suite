# Windows portable runtime acceptance contract

These tests are the executable contract for the Windows-only portable Local
Knowledge Suite. They import the engine from
`plugins/local-knowledge-suite/runtime/src`; a target project must never
contain a copied `ckb` or `memorizer` engine.

The public Python package is `local_knowledge`. The functions may live in the
package root or in `local_knowledge.workspace`, `core`, `service`, `portable`,
`registry`, or `migration`, and the adapter accepts the following equivalent
names while the runtime is consolidated:

| Operation | Canonical name | Temporary accepted aliases |
| --- | --- | --- |
| Create company | `init_company` | `initialize_company_repository`, `company_init`, `create_company` |
| Register company | `register_company` | `company_register` |
| Create project | `init_project` | `bootstrap_workspace`, `project_init`, `create_project` |
| Bootstrap project | `bootstrap_workspace` | none |
| Diagnose project | `doctor_workspace` | `project_doctor`, `doctor` |
| Migrate project | `migrate_workspace` | `project_migrate`, `migrate` |
| Status | `knowledge_status` | none |
| Recall | `recall_context` | none |
| Capture memory | `capture_memory` | none |

Canonical inputs are:

```text
init_company(root, company_id, name, admin=None)
register_company(root)
init_project(root, company_id, install_mode="global", profile="combined")
bootstrap_workspace(root, company_id, profile="combined")
doctor_workspace(root)
migrate_workspace(root, dry_run=True|False)
knowledge_status(root)
recall_context(query, root, ...)
capture_memory(root, kind, title, text, memory_key, ...)
```

`company.toml` and `project.toml` must contain `schema_version` and stable IDs.
The project manifest also contains `company_id`, `profile`, `install_mode`, and
a relative memory path. Machine-local company paths live only in
`%LOCALAPPDATA%\LocalKnowledgeSuite\registry.json`.

Legacy process-wide `CKB_ROOT`, `CKB_DATA_DIR`, `CKB_DATABASE`, and
`CKB_BUNDLE_DIR` overrides are rejected for project-scoped operations. This is
intentional: accepting them could silently route one company's project to
another company's database.

The MCP server exposes exactly these four fast-path tools:
`bootstrap_workspace`, `knowledge_status`, `recall_context`, and
`capture_memory`. Company ingest/review/publish remains outside the MCP fast
path.
