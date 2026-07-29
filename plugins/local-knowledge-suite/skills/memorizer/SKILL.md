---
name: memorizer
description: Recall, capture, correct, organize, validate, export, and restore durable Memory isolated to one Windows project through Local Knowledge Suite. Use when Codex is asked to remember a preference, correction, habit, decision, commitment, entity fact, or project convention; needs earlier project context; must inspect links or repair a `.memorizer` vault; or must safely move reviewed Memory to the same project on another machine without copying derived state.
---

# Memorizer

Use the plugin-owned runtime with the absolute project root. Require schema 2
and a Memory-enabled profile (`memory-only` or `combined`). Never use a company
repository or another project's vault.

Read [references/memory-policy.md](references/memory-policy.md) before capture,
correction, or export. Read
[references/vault-format.md](references/vault-format.md) before repair,
migration, snapshot inspection, or integration work.

## Prefer MCP

Use `recall_context` with only Memory enabled for normal search and
`capture_memory` for one durable signal. Follow capture with
`knowledge_status`; require zero pending events.

Use the pinned CLI for recovery:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool memorizer -Root $ProjectRoot `
  -ToolArguments @("status")
```

The launcher never imports code from the target project.

## Recall

1. Check status after an interrupted capture.
2. Distill pending events. Rebuild only when derived state is stale.
3. Search with a focused query and small limit.
4. Use supporting excerpts and surface contradictions.
5. Distinguish remembered project context from verified company facts.
6. Use `show MEMORY_ID --no-touch` for inspection; count a revisit only when
   the Memory informs the work.

## Capture or correct

1. Search for equivalent and conflicting active Memory.
2. Capture one user-grounded durable signal with `kind`, `title`, `text`, and a
   stable `memory_key`.
3. Remove every credential value. A `secret` event may record only a safe
   indicator, never the secret.
4. For correction, use exact active IDs in `supersedes`; never guess.
5. Use a stable event ID for retries.
6. Require `distilled: true`, an accepted or matched ID, and zero pending
   events before reporting success.

Supported kinds: `correction`, `preference`, `habit`, `decision`,
`commitment`, `entity-fact`, `project-knowledge`, and safe-indicator `secret`.

## Maintain

- Preserve history by superseding rather than erasing.
- Use `pin`, `link`, `backlinks`, and `graph` for intentional curation.
- After supported Markdown repair, run `rebuild` and `validate`.
- Preserve unknown frontmatter and user-authored bodies.
- Never edit SQLite or delete `.write.lock` as a repair shortcut.

## Transfer

Use `local-knowledge memory export/import`, not a copied whole vault. Snapshots
are plain text and belong only to the same project ID. Sensitive Memory is
excluded by default; including it requires explicit acknowledgement. Public
Git export requires a separate public acknowledgement. Import normally
requires an empty vault; `--replace` creates a backup. V1 never merges
snapshots.

Report rejection, conflict, pending distillation, checksum failure, wrong
project ID, disabled profile, or validation error without weakening a gate.
