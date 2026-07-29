# Windows setup, migration, and snapshots

## Runtime launcher

Require native Windows, PowerShell, `uv`, and Python 3.12. If scripts are
blocked, allow them only for the current terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

For global mode, resolve `$PluginRoot` from the installed skill. For vendored
mode, use `$ProjectRoot\tools\local-knowledge-suite`.

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "doctor", "--root", $ProjectRoot)
```

For an exact tagged global update or rollback:

```powershell
codex plugin remove local-knowledge-suite@john-idk
codex plugin marketplace remove john-idk
codex plugin marketplace add luutru433-coder/local-knowledge-suite --ref v1.0.1
codex plugin add local-knowledge-suite@john-idk
```

Restart Codex, open a new task, resolve the installed `$PluginRoot` again, and
run `project doctor`. To roll back, repeat with the tested old tag. Marketplace
`upgrade john-idk` only refreshes the configured ref; it does not change an
immutable tag. Roll back only when release notes confirm schema compatibility.
Older runtimes fail closed on newer schemas; never hand-edit schema numbers.

## Initialize a Memory-only project

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "project", "init", "--root", $ProjectRoot,
    "--profile", "memory-only", "--install-mode", "global"
  )
```

This is the v1 default and does not need a company.

In the user's application repository, review and commit
`.local-knowledge/project.toml` plus the managed `.gitignore` additions. The
manifest preserves the stable project ID across clones. Do not perform this
commit in the Local Knowledge Suite product source repository.

For `combined` and `company-only`, explicit project initialization also writes
a private machine-local authorization for the exact project ID, canonical
project root, and company ID. The manifest alone never grants company access.
A moved or cloned root must use `project restore` to re-enroll on that machine.

## Create or register a company

Keep the company repository separate from application projects.

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "init", "--root", $CompanyRoot,
    "--name", $CompanyName, "--admin", $AdminUser
  )

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "register", "--root", $CompanyRoot, "--admin", $AdminUser
  )
```

Enter passwords interactively. Registration rebuilds ignored indexes, but
claims remain unverified until authorized sources are restored and ingested on
that machine.

Before source registration, replace the placeholder model names in
`.ckb/config.json` with exact loaded LM Studio chat/embedding IDs, configure
bearer and private-Git credentials through portal Settings, and run:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("company", "health", "--company", $CompanyId)
```

See the company skill's `references/operations.md` for the exact non-secret
config shape. Chat readiness is an ingestion gate; embedding readiness enables
semantic search.

Attach with `--profile combined` or `company-only` and the returned
`--company COMPANY_ID`.

## Vendored mode

Initialize with `--install-mode vendored`, then:

```powershell
& "$PluginRoot\scripts\Install-LocalKnowledgeVendor.ps1" `
  -Action Install -ProjectRoot $ProjectRoot
```

The installer keeps the runtime snapshot under
`tools/local-knowledge-suite/`, writes an MCP-only managed block to
`.codex/config.toml`, and materializes three real repository skills (not
symlinks) under:

- `.agents/skills/manage-local-knowledge/`;
- `.agents/skills/memorizer/`; and
- `.agents/skills/company-knowledge-base/`.

Review and commit all of those paths together with
`.local-knowledge/project.toml` and `.local-knowledge/vendor-lock.json`.
`Verify` checks the locked runtime plus every byte, missing file, and extra file
in the three managed skill copies. Never commit Memory, company operational
state, sources, registry data, or credentials.

After clone, use `-Action Verify`. Upgrade from a newer versioned source with
`-Action Upgrade`; never overwrite a modified snapshot. Install refuses to
claim a pre-existing skill with one of the three managed names. Upgrade backs
up the runtime and managed skills under
`%LOCALAPPDATA%\LocalKnowledgeSuite\vendor-backups\`, rolls all managed paths
back together on failure, and leaves unrelated repository skills untouched.

## Migrate schema

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("migrate", "--root", $ProjectRoot, "--dry-run")

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("migrate", "--root", $ProjectRoot, "--apply")
```

Schema 1/0.2 to schema 2 migration creates a backup. Never hand-edit the schema
or identity.

## Export and import Memory

Snapshots are plain text. Private is the default Git visibility:

```powershell
$ProjectRoot = (Resolve-Path "D:\Projects\northstar-support").Path
$SnapshotPath = Join-Path $ProjectRoot ".local-knowledge\memory-snapshot"

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "memory", "export",
    "--root", $ProjectRoot,
    "--output", $SnapshotPath,
    "--git-visibility", "private"
  )
```

Sensitive inclusion requires both `--include-sensitive` and
`--acknowledge-sensitive`. Public export always requires
`--git-visibility public --allow-public`. Review every exported file.

For an explicitly reviewed snapshot in the user's project repository, inspect
`git status`, stage the new files, and inspect the staged diff:

```powershell
git -C $ProjectRoot add .local-knowledge/memory-snapshot
git -C $ProjectRoot diff --cached -- .local-knowledge/memory-snapshot
```

If review fails, run:

```powershell
git -C $ProjectRoot restore --staged .local-knowledge/memory-snapshot
```

Then repair the export.
Only after review:

```powershell
git -C $ProjectRoot commit -m "chore(memory): add reviewed project snapshot"
git -C $ProjectRoot push
```

The Local Knowledge Suite product repository ignores this path and must never
ship a user's real Memory.

Import into an empty vault with the same project ID:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "memory", "import", "--root", $ProjectRoot,
    "--input", $SnapshotPath
  )
```

`--replace` creates a local backup first. V1 does not merge snapshots.

## New Windows machine

On the old PC, record each project profile. For company-enabled projects,
create a private source inventory with `kind`, relative `path` or seed URL,
`title`, every `allow-domain`, and `branch`. Also record usernames, global
roles, and branch-role memberships without passwords or tokens.

On the new PC:

1. Install the exact tagged plugin release.
2. Assign `$ProjectRoot`, clone the project, and read its recorded profile
   before running `project restore`.
3. For `memory-only`, run `project restore`, import its reviewed Memory
   snapshot if used, and verify vendored mode if applicable. Skip every
   remaining company step, run `project doctor`, trust the project, and open a
   new task.
4. For `combined` or `company-only`, do not restore the project yet. Assign
   `$CompanyRoot` and `$CompanyId`, clone/register the company, and create a new
   local administrator first. Only after registration succeeds, run `project
   restore`, import the reviewed Memory snapshot if used, and verify vendored
   mode if applicable.
5. Configure exact LM Studio model IDs, bearer token, and private-Git
   credentials again; run company `health` before source registration.
6. Restore local files at the inventory's relative paths. Run a new
   `source-add`, `ingest`, and `run-job` for every file/folder/website; re-crawl
   each website with its recorded allowlist. Never copy `.ckb/`.
7. Recreate users through `company user-add`; recreate branch memberships and
   roles in the portal.
8. Run company `health` and `project doctor`, then verify one cited company
   answer.

Never copy `.ckb/`, whole `.memorizer/` vaults, the machine registry, or
Windows Credential Manager between machines.

## Unregister from one Windows account

Use the supported command; never hand-edit the machine registry:

```powershell
$CompanyRoot = (Resolve-Path "D:\Knowledge\Northstar-Bicycle-Labs").Path

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("company", "unregister", "--root", $CompanyRoot)
```

This removes only the verified mapping and preserves the repository,
`knowledge/`, manifest, `.ckb/`, `.local-sources/`, and credential key. Purging
the exact company's key additionally requires both
`--purge-credential-key --confirm-company COMPANY_ID`. It can make encrypted
credentials unreadable and never deletes local directories.
