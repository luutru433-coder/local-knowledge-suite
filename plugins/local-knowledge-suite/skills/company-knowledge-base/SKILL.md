---
name: company-knowledge-base
description: Create, register, ingest, search, review, publish, validate, serve, and synchronize a citation-backed Windows company knowledge repository shared safely across projects through Local Knowledge Suite. Use when Codex must answer company questions from PDF or scanned PDF, DOCX, XLSX, PPTX, EML, Markdown, text, folders, or allowlisted public websites; operate the local review portal; diagnose ingestion, OCR, model, citation, or Git problems; manage local roles; or restore a private company repository on another machine.
---

# Company Knowledge Base

Operate the plugin-owned runtime against an explicit registered company
repository. Never treat project Memory or Skill text as company evidence, and
never import knowledge code from a target project.

Resolve identity from `.local-knowledge/company.toml` and the Windows-user
registry. Several projects may reference one company ID; different company IDs
must never share source text, databases, credentials, or results.

Read [references/source-policy.md](references/source-policy.md) before
registration, crawl, or sensitive ingestion. Read
[references/okf-quality.md](references/okf-quality.md) before editing,
approving, or repairing concepts. Read
[references/operations.md](references/operations.md) for CLI, portal, models,
roles, Git, and diagnosis.

## Establish context

1. Resolve absolute project and company repository paths.
2. Require project profile `combined` or `company-only` and the exact registered
   company ID.
3. Call `knowledge_status(project_root)` and inspect compatibility, migration,
   registration, warnings, and stores.
4. Replace the placeholder chat and embedding names in `.ckb/config.json` with
   exact loaded LM Studio model IDs. Store any LM Studio bearer token and
   private-Git credentials through portal Settings, never in config.
5. Run company `health` before source registration or ingestion.
6. Stop mutations for schema incompatibility, registry mismatch, Git conflict,
   missing required local models, or a source-policy violation.

Do not create or register a company implicitly from a recall request. Never set
the Credential Manager namespace manually.

## Ingest

1. Put authorized local material inside the company's ignored
   `.local-sources/`.
2. Register a supported `file` or `folder`, or an explicit public HTTP(S)
   website with every permitted `--allow-domain`.
3. Queue `ingest SOURCE_ID`.
4. Run `run-job JOB_ID`, `worker --once`, or a continuous worker.
5. Preserve failed job history. Repair the source, parser, OCR, local model, or
   Git state and enqueue a new job.

Never ingest arbitrary machine paths, private hosts, off-allowlist pages, or
another company's material.

## Search and answer

Prefer `recall_context` with only Company recall enabled. Use CLI search for
diagnosis or advanced operation.

Answer only from evidence-sufficient claims. For every used citation require:

- `verified: true`;
- non-empty `source_uri` and `locator`; and
- an exact excerpt that supports the claim.

If evidence is absent, stale, or contradictory, report the gap. Do not
fabricate, infer beyond the excerpt, or substitute Memory.

## Review and publish

1. Inspect claim confidence, cited-claim coverage, exact excerpt, locator,
   branch, and concept validation.
2. Repair factual text only through the structured editor using immutable
   stored source text.
3. Approve through the portal/API so validation, indexes, audit state, and Git
   commit remain atomic.
4. Reject unsupported or obsolete drafts. Never edit SQLite or citation
   metadata to bypass a gate.
5. Preserve admin, reviewer, reader, and protected-branch boundaries.

Automatic publication requires every quality, citation, branch, role, and Git
gate. Human review cannot make an unsupported claim factual.

## Synchronize and restore

- Commit only the company manifest and canonical `knowledge/`; normally use a
  private remote.
- Keep `.ckb/`, `.local-sources/`, registry data, and credentials untracked.
- Use guarded `sync`; resolve conflicts explicitly; push only when requested.
- After clone, register the company, configure models and credentials again,
  run health, recreate local users and branch roles, restore authorized
  sources from an inventory, and register/ingest/crawl them again.

Git preserves canonical history but does not prove current source truth.
Rebuilt claims remain unverified until source verification succeeds locally.
