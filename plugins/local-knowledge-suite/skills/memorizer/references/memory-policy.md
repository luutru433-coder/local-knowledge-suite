# Memory policy

## Evidence and scope

- Treat explicit user statements as authoritative for preferences and project conventions.
- Capture an assistant statement only after the user confirms it.
- Keep each `.memorizer/` vault scoped to exactly one project manifest.
- Never search or copy another project's vault without a direct request and explicit source labeling.
- Never use memory as evidence for a company-document claim.
- Split several durable claims into atomic capture events.

## Durability test

Capture a signal only when it is likely to change a later answer or action and should remain true beyond the current task. Skip current-screen observations, intermediate hypotheses, one-off formatting instructions, assistant inference, speculation, and facts easily retrieved from an authoritative source.

## Corrections and retries

Search before correcting. Require stable active IDs in `supersedes`. A correction creates a new active memory and retains the old event and note as provenance. If the target is absent or ambiguous, ask or leave the correction uncaptured.

Use one stable event ID for a retry. Reusing an event ID with equivalent content is a no-op; reusing it with different content is rejected.

## Sensitive information

- Never store passwords, private keys, authentication codes, access tokens, recovery phrases, or credential-bearing connection strings.
- Record only a safe indicator that sensitive context exists or where it is managed when useful.
- Keep sensitive memory out of normal recall.
- Never send sensitive memory to a cloud embedding service. Optional embeddings must use the configured local endpoint.

## Snapshot transfer

- Treat every exported snapshot as readable plain text, not a backup archive or
  encrypted secret store.
- Exclude sensitive Memory by default. Include it only when the user explicitly
  requests both `--include-sensitive` and `--acknowledge-sensitive`.
- Require `--git-visibility public --allow-public` when the intended Git
  destination is public. This acknowledgement does not sanitize content.
- Review every file. Stage new snapshot files, inspect
  `git diff --cached -- .local-knowledge/memory-snapshot`, and unstage them with
  `git restore --staged` when review fails.
- Import only to the same stable project ID. Require an empty vault unless the
  user explicitly chooses `--replace`; retain the created local backup.
- Do not merge snapshots in v1, copy a whole vault, or place a snapshot in the
  public Local Knowledge Suite product repository.

## Retrieval and completion

Use the smallest relevant result set and exclude superseded items by default. Surface contradictions instead of choosing silently. A capture is complete only after same-turn distillation, accepted or matched IDs, zero pending events, and no unresolved conflict or rejection.
