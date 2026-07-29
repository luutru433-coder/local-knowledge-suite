# Windows company operations

## Storage and registration

```text
COMPANY_ROOT\
├── .local-knowledge\company.toml   # commit
├── knowledge\                      # commit
└── .ckb\                           # ignore
```

Create and register the repository through `local-knowledge company init` and `company register`. Initialization creates a standalone Git repository and baseline commit. Registration rebuilds ignored local indexes from `knowledge/`, but imported claims remain unverified until their sources are ingested again; use `company register --admin USERNAME` after cloning onto a new Windows profile. Keep approved local files under ignored `.local-sources/`. The machine-local registry is `%LOCALAPPDATA%\LocalKnowledgeSuite\registry.json`; do not commit or hand-edit it. Enter administrator passwords interactively.
If an existing manifest uses an older schema, init/register may add only its
verified machine-registry identity and then fail with a migration-required
error. Run the explicit migration from an already bound project before
retrying registration; no repository, database, index, Git, config, or user
state is changed on the stale path.

Run project-independent lifecycle commands with the launcher:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("company", "serve", "--company", $CompanyId, "--host", "127.0.0.1", "--port", "8000")
```

Run CKB operations with `-Tool ckb -Root $CompanyRoot` and an argument array such as `@("validate")`, `@("worker")`, or `@("search", $Question)`.
The direct `ckb` entry point never infers a root from the current directory or
`CKB_ROOT`. Its `-Root` must resolve to a current-schema company manifest whose
company ID maps to that exact root in the machine registry. Direct `ckb init`
only resets or completes operational state for such an already managed
company; create repositories with `local-knowledge company init` and register
clones with `local-knowledge company register`.

The plugin ships prebuilt portal assets; Node.js is not required to operate a
released plugin. For release development, use Node 22 and repository-pinned
pnpm 11.9.0, build `@local-knowledge-suite/portal`, and package its output into the
runtime before validation.

Use a private Git remote for company material unless the data owner explicitly
approves publication. The public Local Knowledge Suite product repository must
never receive a user's company manifest, canonical knowledge, sources, indexes,
or credentials.

## Configuration

Fresh initialization writes, and fresh registration defaults to, the
non-working placeholders `local-chat-model` and `local-embedding-model`.
Before any source registration or ingestion, load one chat model and one
embedding model in LM Studio and create or update `.ckb/config.json` with exact
model IDs. The non-secret file must include:

```json
{
  "lm_studio_url": "http://127.0.0.1:1234/v1",
  "chat_model": "EXACT_LOADED_CHAT_MODEL_ID",
  "embedding_model": "EXACT_LOADED_EMBEDDING_MODEL_ID"
}
```

When bearer authentication is off, list exact IDs with:

```powershell
$LmStudioUrl = "http://127.0.0.1:1234/v1"
(Invoke-RestMethod -Method Get -Uri "$LmStudioUrl/models").data |
  Select-Object -ExpandProperty id
```

Preserve any other existing config keys when updating these three. Other
non-secret settings may use `.ckb/config.json` or environment variables:

- `CKB_LM_STUDIO_URL`, normally `http://127.0.0.1:1234/v1`;
- `CKB_CHAT_MODEL` and `CKB_EMBEDDING_MODEL`;
- `CKB_CORS_ORIGINS` only as an explicit, process-local development opt-in for
  exact HTTP(S) loopback origins; it is empty by default, ignored when found in
  persisted config, and never written to `.ckb/config.json`;
- `CKB_CANONICAL_BRANCH`;
- `CKB_LEASE_SECONDS` and `CKB_HEARTBEAT_SECONDS`;
- `CKB_CLAIM_BATCH_CHARS` and `CKB_CLAIM_BATCH_SECTIONS`.

Storage paths and keyring namespace are derived from the registered company context. Do not override database, bundle, data, root, or keyring paths to point at another company.
V1 portal servers bind only to `localhost` or a numeric loopback address.
Wildcard, LAN, hostname, and remote binds are rejected before Uvicorn starts.
HTTP Host headers are independently restricted to `localhost` or numeric
loopback addresses to stop DNS rebinding. The packaged portal is same-origin,
so production needs no CORS. Do not enable development CORS while using an
untrusted local web process.

Configure LM Studio bearer tokens and per-user Git credentials in the portal. Ciphertext remains in SQLite; the AES-GCM master key stays in Windows Credential Manager under `local-knowledge-suite/<company_id>`.

Start the portal, sign in as the local administrator, and use
**Settings → Credentials**. Add an LM Studio bearer token only if the server
requires one. Add Git username/PAT only for private remote sync or push. Never
store either secret in `.ckb/config.json`, environment variables, chat, logs,
or Git.

Run the health gate before `source-add` or `ingest`:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("company", "health", "--company", $CompanyId)
```

Inspect JSON, not only the exit code. Require `status: "ok"`, database and chat
readiness, an available-or-unused secret backend, and no OKF failures. Embedding
readiness enables semantic search; without it, search is lexical. OCR readiness
is required for scanned PDFs.

## Diagnosis

- `health`: database, local models, OCR, secrets, and bundle status.
- `validate`: exact OKF failures.
- `git-status`: branch, head, changes, and remotes.
- `sync`: guarded pull/rebase after clean-worktree checks.
- Portal Jobs: attempts, errors, and result payloads.
- Portal Publications: candidate branches, commits, merge, and recovery state.
- Portal Branches: ACLs and canonical protection.
- Portal Entities: PageRank-ranked entity hubs and related canonical concepts.

Treat embedding failure as lexical-search degradation, chat-model failure as an ingestion blocker, and missing Tesseract as a scanned-PDF limitation.

`health` also distinguishes embedded PDF text extraction through pinned
`pypdfium2` from optional Tesseract OCR readiness.

Use reset only when explicitly intended:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool ckb -Root $CompanyRoot `
  -ToolArguments @("init", "--reset-state", "--admin", $AdminUser)
```

The runtime backs up SQLite and preserves `knowledge/` and Git history.
