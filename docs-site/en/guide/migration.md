# Move to a new Windows PC

Move each data class through its intended channel:

1. a project repository carries code and `.local-knowledge\project.toml`;
2. Memory moves only through a reviewed snapshot;
3. a private company remote carries its manifest and `knowledge\`;
4. original sources use a separate approved backup; and
5. models, credentials, users, and permissions are configured again.

Commands use `$PluginRoot` resolved through
[Quick installation](/en/guide/getting-started).

## On the old PC

### Every project

Commit and push the project, including `.local-knowledge\project.toml` and the
managed `.gitignore` lines. Create and review a
[Memory snapshot](/en/guide/memory-snapshots) only if it is needed.

Record each project profile. A `memory-only` project **skips every company
step** on both PCs.

### Only when a project uses company knowledge

Push `.local-knowledge\company.toml` and `knowledge\` to a private remote. Do
not commit `.ckb\` or `.local-sources\`.

Back up authorized originals separately and create a private, credential-free
source inventory. For a file or folder, `path` is relative to
`.local-sources\`; for a website, it is the seed URL. Record all five fields:
`kind`, `path`, `title`, `allow-domain`, and `branch`.

```json
[
  {
    "kind": "file",
    "path": "policies\\support-policy.md",
    "title": "Support policy",
    "allow-domain": [],
    "branch": "main"
  },
  {
    "kind": "website",
    "path": "https://docs.example.invalid/start",
    "title": "Public product documentation",
    "allow-domain": ["docs.example.invalid"],
    "branch": "main"
  }
]
```

For example, keep the inventories on approved encrypted backup media:

```powershell
$MigrationRoot = "E:\LocalKnowledgeMigration\northstar"
$SourceInventoryPath = Join-Path $MigrationRoot "source-inventory.json"
$AccessInventoryPath = Join-Path $MigrationRoot "access-inventory.json"
```

From the old portal, also record username, global role, and each branch/branch
role membership. Record no password, token, or master key. Do not copy Windows
Credential Manager or
`%LOCALAPPDATA%\LocalKnowledgeSuite\registry.json`.

## On the new PC

### 1. Install the recorded release

Install Git, Codex, `uv`, and Python 3.12, then install the exact tag:

```powershell
codex plugin marketplace add luutru433-coder/local-knowledge-suite --ref v1.0.0
codex plugin add local-knowledge-suite@john-idk
```

Restart Codex, open a new task, and resolve `$PluginRoot` again.

Attach the approved backup media and assign its inventory paths again:

```powershell
$MigrationRoot = "E:\LocalKnowledgeMigration\northstar"
$SourceInventoryPath = Join-Path $MigrationRoot "source-inventory.json"
$AccessInventoryPath = Join-Path $MigrationRoot "access-inventory.json"
```

### 2. Clone the project and choose the correct restore path

Assign every path before using it:

```powershell
$ProjectRepositoryUrl = "https://github.com/your-org/northstar-support.git"
$ProjectRoot = "D:\Projects\northstar-support"
git clone $ProjectRepositoryUrl $ProjectRoot
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
```

Read the profile recorded in the project. The next steps depend on that
profile:

- For `memory-only`, restore the project now:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "restore", "--root", $ProjectRoot)
```

  Then import the reviewed snapshot if one exists, run `-Action Verify` for
  vendored mode, run `project doctor`, trust the project, and stop here. Do not
  clone/register a company, configure models, restore sources, or create
  company users.
- For `combined` or `company-only`, **do not run `project restore` yet**.
  Project restore must resolve the company through the new machine's registry,
  so complete step 3 first.

### 3. Register the company for `combined` or `company-only`

```powershell
$CompanyRoot = "D:\Knowledge\Northstar-Bicycle-Labs"
$CompanyId = "northstar-bicycle-labs"
$AdminUser = "admin"
$CompanyRepositoryUrl = "https://github.com/your-org/northstar-company-knowledge.git"

git clone $CompanyRepositoryUrl $CompanyRoot
$CompanyRoot = (Resolve-Path $CompanyRoot).Path

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "register",
    "--root", $CompanyRoot,
    "--admin", $AdminUser
  )
```

Enter a new local password in the hidden prompt. Do not copy old credentials.

Only after `company register` succeeds, restore the project:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "restore", "--root", $ProjectRoot)
```

Import the reviewed snapshot if one exists. Run `-Action Verify` for vendored
mode.

### 4. Configure models and credentials again

Load the chat and embedding models in LM Studio, obtain their exact IDs, and
create or update the non-secret config:

```powershell
$LmStudioUrl = "http://127.0.0.1:1234/v1"
$ChatModel = Read-Host "Exact chat model ID"
$EmbeddingModel = Read-Host "Exact embedding model ID"
$ConfigPath = Join-Path $CompanyRoot ".ckb\config.json"
$Config = if (Test-Path -LiteralPath $ConfigPath) {
  Get-Content -Raw -Encoding utf8 $ConfigPath | ConvertFrom-Json
} else {
  [pscustomobject]@{}
}
$Config | Add-Member NoteProperty lm_studio_url $LmStudioUrl -Force
$Config | Add-Member NoteProperty chat_model $ChatModel -Force
$Config | Add-Member NoteProperty embedding_model $EmbeddingModel -Force
$ConfigJson = $Config | ConvertTo-Json -Depth 20
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText(
  $ConfigPath,
  $ConfigJson + [Environment]::NewLine,
  $Utf8NoBom
)
```

Do not leave `local-chat-model` or `local-embedding-model` in the file.

Start the portal and re-enter the LM Studio bearer token if required. For a
private remote, re-enter the Git username/PAT under
**Settings → Credentials**. Put no secret in config, chat, Git, or an
inventory.

Before any source-add or ingestion:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("company", "health", "--company", $CompanyId)
```

Continue only when JSON reports `status: "ok"` and database, chat, secrets,
and OKF are ready. Repair embeddings for semantic search and OCR before
ingesting scanned PDFs.

### 5. Restore and ingest every source again

Copy source backups to the same relative paths below
`$CompanyRoot\.local-sources\`. Register them from the inventory and run each
new job:

```powershell
$SourceRoot = Join-Path $CompanyRoot ".local-sources"
$Inventory = Get-Content -Raw -Encoding utf8 $SourceInventoryPath |
  ConvertFrom-Json

foreach ($Source in $Inventory) {
  $Uri = if ($Source.kind -eq "website") {
    [string]$Source.path
  } else {
    Join-Path $SourceRoot ([string]$Source.path)
  }

  $SourceArgs = @(
    "company", "source-add", "--company", $CompanyId,
    [string]$Source.kind, $Uri,
    "--title", [string]$Source.title,
    "--branch", [string]$Source.branch
  )
  foreach ($Domain in @($Source.'allow-domain')) {
    $SourceArgs += @("--allow-domain", [string]$Domain)
  }

  $Added = (
    & "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
      -Tool local-knowledge -ToolArguments $SourceArgs |
      Out-String
  ) | ConvertFrom-Json
  $Queued = (
    & "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
      -Tool local-knowledge `
      -ToolArguments @(
        "company", "ingest", "--company", $CompanyId, [string]$Added.id
      ) |
      Out-String
  ) | ConvertFrom-Json

  & "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
    -Tool local-knowledge `
    -ToolArguments @(
      "company", "run-job", "--company", $CompanyId,
      [string]$Queued.job_id
    )
}
```

This is a new source registration and ingestion, not a `.ckb\` copy. Websites
are crawled again under their allowlists. Git-restored claims remain unverified
until their evidence is ingested again.

### 6. Recreate users and permissions

Create each user from the access inventory; passwords are entered only in the
hidden prompt:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "user-add", "--company", $CompanyId,
    "reviewer1", "--role", "reviewer"
  )
```

In portal **Branches**, recreate any local branches and assign every user to
the recorded branch role. Do not guess or elevate permissions.

### 7. Acceptance checks

Run company `health` again, then:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "doctor", "--root", $ProjectRoot)
```

Trust the project, open a new Codex task, call `knowledge_status`, and test one
Memory recall and one company answer with verified citations.

See the printable
[migration checklist](https://github.com/luutru433-coder/local-knowledge-suite/blob/main/docs/MIGRATION_CHECKLIST.en.md).
