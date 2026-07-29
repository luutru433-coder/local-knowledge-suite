# CLI and MCP reference

Normal users can ask Codex to call MCP without resolving a path. For direct CLI
use, resolve `$PluginRoot` as shown in
[Quick installation](/en/guide/getting-started).

## Pinned launcher

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "status", "--root", $ProjectRoot)
```

Use absolute Windows paths for project, company, and snapshot locations.

## Project

```text
project init --root ROOT
  [--company COMPANY_ID]
  [--profile memory-only|combined|company-only]
  [--install-mode global|vendored]

project status --root ROOT
project doctor --root ROOT
project restore --root ROOT
migrate --root ROOT [--dry-run|--apply]
```

V1 defaults to `memory-only`, no company, and `global`. `combined` and
`company-only` require a registered company. Current workspace schema: `2`.

## Memory snapshot

```text
memory export --root ROOT --output PATH
  [--git-visibility private|public]
  [--include-sensitive --acknowledge-sensitive]
  [--allow-public]

memory import --root ROOT --input PATH [--replace]
```

Private is the default visibility. Public always requires `--allow-public`.
Sensitive always requires acknowledgement. Import normally requires an empty
vault; `--replace` creates a backup.

## Company

```text
company init --root ROOT --name NAME [--id ID] [--admin USER]
company register --root ROOT [--admin USER]
company unregister --root ROOT
  [--purge-credential-key --confirm-company COMPANY_ID]
company list
company serve --company ID [--host 127.0.0.1] [--port 8000]

company source-add --company ID file|folder|website URI
  [--title TITLE] [--allow-domain DOMAIN] [--branch BRANCH]
company ingest --company ID SOURCE_ID
company run-job --company ID JOB_ID
company worker --company ID [--once]
company search --company ID QUERY [--limit N] [--branch BRANCH]
company health|validate|git-status|sync|push --company ID
```

Administrator passwords are entered interactively.
`unregister` removes only a verified mapping and preserves the repository and
local data. Both purge flags must be used together; see
[Uninstall](/en/guide/uninstall).

Both `company serve` and direct `ckb serve` are loopback-only in v1.
`localhost` is normalized to `127.0.0.1`; wildcard, LAN, hostname, and remote
binds are rejected. HTTP Host must independently be `localhost` or a numeric
loopback address to block DNS rebinding. The packaged portal is same-origin,
so CORS is disabled by default; `CKB_CORS_ORIGINS` is only a process-local
development opt-in for exact loopback origins and is never persisted. Direct
`ckb` also requires an explicit absolute company
root with a current manifest and an exact machine-registry match. It never
uses the current directory or `CKB_ROOT`, and its `init` command cannot create
an unmanaged repository.

## Four MCP tools

```text
bootstrap_workspace(
  root,
  company_id=None,
  profile="memory-only",
  install_mode="global"
)

knowledge_status(root)

recall_context(
  query,
  root,
  limit=8,
  include_skills=True,
  include_memory=True,
  include_company=True,
  include_sensitive_memory=False
)

capture_memory(
  root,
  kind,
  title,
  text,
  memory_key,
  event_id=None,
  tags=None,
  importance=0.7,
  pinned=False,
  supersedes=None
)
```

Bootstrap is idempotent and never creates a company implicitly. Status reports
compatibility, schema, registration, stores, pending events, migration, and
snapshot metadata. Recall keeps Skills, Memory, and Company sections separate.
Capture accepts one atomic signal; a correction must use exact active IDs in
`supersedes`. Completion requires `distilled: true` and zero pending events.

Status and recall are non-destructive and idempotent, but they are not declared
read-only MCP operations. Status may create and remove transient local locks.
Recall may distill already-captured pending Memory events and rebuild or cache
derived indexes.
