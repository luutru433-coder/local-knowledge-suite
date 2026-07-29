---
name: manage-local-knowledge
description: Initialize, route, recall, and safely transfer reusable local knowledge across Windows projects using Local Knowledge Suite. Use when Codex must start a Memory-only project without a company, connect several projects to one registered company repository, choose global or vendored installation, check or migrate workspace health, recall project decisions and cited company facts without conflating them, capture durable Memory, or export/import a reviewed Memory snapshot.
---

# Manage Local Knowledge

Use the plugin-owned runtime with an absolute Windows project root. Never infer
a project or company path from the skill directory, import a target project's
knowledge code, or guess a missing identity.

Read [references/windows-setup.md](references/windows-setup.md) for setup,
cloning, migration, installation modes, and snapshots. Read
[references/collected-skill-summary.md](references/collected-skill-summary.md)
when interpreting storage ownership or tool results.

## Preserve trust boundaries

- Treat Skills as instructions, not remembered context or factual evidence.
- Treat Memory as preferences, decisions, corrections, commitments, entities,
  and conventions for exactly one project.
- Treat company facts as evidence only after the citation gate passes.
- Treat a company-enabled project manifest as identity, not authorization.
  Normal company access also requires the machine-local
  `project_id + canonical root + company_id` enrollment created by explicit
  bootstrap or restore.

Route advanced Memory maintenance to `$memorizer`. Route company ingestion,
review, portal, user, publication, and Git operations to
`$company-knowledge-base`.

## Bootstrap or restore

1. Resolve the intended project root to an absolute path.
2. Call `knowledge_status(root)` before mutation.
3. If no manifest exists, call
   `bootstrap_workspace(root, company_id=None, profile="memory-only",
   install_mode="global")` unless the user explicitly chooses another profile.
   Tell the user to review and commit the project manifest and managed
   `.gitignore` additions in their application repository.
4. Require a registered company ID for `combined` or `company-only`. Never
   create a company implicitly during bootstrap or recall.
5. If migration is required, stop normal writes. Preview and apply the
   supported migration; never edit schema numbers manually.
6. After clone, run `project restore`; register and re-ingest company sources
   when applicable; verify vendored files; then run `project doctor`.

Schema 2 permits no `company_id` only for `memory-only`. Do not reassign an
existing project by editing its manifest. A moved or copied manifest fails
closed until explicit restore re-enrolls that project path.

## Use the MCP fast path

```text
knowledge_status(root)
bootstrap_workspace(root, company_id=None,
                    profile="memory-only", install_mode="global")
recall_context(query, root, limit=8,
               include_skills=True,
               include_memory=True,
               include_company=True,
               include_sensitive_memory=False)
capture_memory(root, kind, title, text, memory_key,
               event_id=None, tags=None, importance=0.7,
               pinned=False, supersedes=None)
```

Inspect warnings. Disable irrelevant recall classes. Keep sensitive Memory
excluded unless the user explicitly requests it and disclosure is necessary.

## Recall and answer

1. Search before acting when a prior preference, decision, convention, or
   company fact could change the work.
2. Keep `skills`, `memory`, and `company` results separate.
3. Surface conflicts, degraded stores, migrations, and evidence gaps.
4. Use a company claim only when `evidence_sufficient` is true and every used
   citation has `verified: true`, `source_uri`, `locator`, and an exact excerpt.
5. Never fill missing company evidence with Memory, Skill text, or inference.

## Capture Memory

1. Capture only explicit user-grounded information durable enough to affect
   future work.
2. Exclude transient state, assistant inference, public facts, company-document
   facts, and every credential value.
3. Search for an equivalent or conflicting active item first.
4. Capture one atomic signal with a stable `memory_key` and a stable `event_id`
   for retries.
5. For corrections, use only exact active IDs in `supersedes`.
6. Require `distilled: true`, an accepted or matched ID, and zero pending events
   before reporting success.

## Transfer Memory

Use the CLI workflow in `windows-setup.md`. Snapshots are deterministic plain
text, not encrypted. Exclude sensitive Memory by default. Public export and
sensitive inclusion each require their own explicit acknowledgement. Import
only into the same project ID; v1 does not merge snapshots.
