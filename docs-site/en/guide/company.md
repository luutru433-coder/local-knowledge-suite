# Company knowledge

Use Company Knowledge for information that needs sources: policies, products,
procedures, or internal documents. This guide uses only the fictional company
`Northstar Bicycle Labs`.

The commands below assume `$PluginRoot` was resolved as shown in
[Quick installation](/en/guide/getting-started). Normal users may ask Codex to
use `$company-knowledge-base` without resolving a path themselves.

## 1. Create a separate repository

```powershell
$CompanyRoot = "D:\Knowledge\Northstar-Bicycle-Labs"
$AdminUser = "admin"

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "init",
    "--root", $CompanyRoot,
    "--name", "Northstar Bicycle Labs",
    "--admin", $AdminUser
  )
```

Enter the password only in the hidden terminal `getpass` prompt. Never place
the **password** in `ToolArguments`, an environment variable, chat prompt,
file, log, or Git. Record the returned `company_id`.

```text
.local-knowledge\company.toml   commit
knowledge\                      commit
.local-sources\                 do not commit
.ckb\                           do not commit
```

Use a **private** remote for a company repository.

## 2. Configure models and credentials

`company init` creates `.ckb\config.json` with the sample names
`local-chat-model` and `local-embedding-model`. They are placeholders, not
working model IDs.

```powershell
$CompanyId = "northstar-bicycle-labs" # company_id returned by init
```

Start the Local Server in LM Studio and load one chat model and one embedding
model. When the server does not require a bearer token, list its exact IDs:

```powershell
$LmStudioUrl = "http://127.0.0.1:1234/v1"
(Invoke-RestMethod -Method Get -Uri "$LmStudioUrl/models").data |
  Select-Object -ExpandProperty id
```

If bearer authentication is enabled, read the IDs in the LM Studio interface.
Write that URL and the two exact IDs to the non-secret config:

```powershell
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

These required fields then have this shape:

```json
{
  "lm_studio_url": "http://127.0.0.1:1234/v1",
  "chat_model": "EXACT_CHAT_MODEL_ID",
  "embedding_model": "EXACT_EMBEDDING_MODEL_ID"
}
```

Do not put tokens or Git passwords in that file. Start the portal, sign in as
the administrator, and open **Settings → Credentials**. Store the LM Studio
bearer token there only when the server requires one. Configure a Git
username/PAT there only when syncing or pushing to a private remote:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "serve", "--company", $CompanyId,
    "--host", "127.0.0.1", "--port", "8000"
  )
```

The portal encrypts credentials; its master key stays in Windows Credential
Manager. Run health before adding a source:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("company", "health", "--company", $CompanyId)
```

Read the returned JSON, not only the exit code: `status` must be `ok`,
`database` must be `true`, the chat endpoint must be ready, the secret backend
must have no error, and `okf` must have no failures. The embedding model must
be ready for semantic search; otherwise search is lexical only. OCR is required
only for scanned PDFs.

## 3. Attach a project

```powershell
$ProjectRoot = "D:\Projects\northstar-support"
$CompanyId = "northstar-bicycle-labs"

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "project", "init",
    "--root", $ProjectRoot,
    "--company", $CompanyId,
    "--profile", "combined",
    "--install-mode", "global"
  )
```

`combined` keeps separate project Memory and uses shared company evidence.
`company-only` omits Memory. Both require a registered company.

## 4. Add a source

Copy an approved source under `.local-sources\`:

```powershell
$SourcePath = Join-Path $CompanyRoot ".local-sources\support-policy.md"

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "source-add", "--company", $CompanyId,
    "file", $SourcePath, "--title", "Support policy"
  )
```

Use the returned source ID to queue ingestion, then the returned job ID:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("company", "ingest", "--company", $CompanyId, "1")

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("company", "run-job", "--company", $CompanyId, "1")
```

Replace `1` with actual IDs. Website sources require explicit public HTTP(S)
seeds and `--allow-domain` for every permitted domain. Private hosts and
off-allowlist navigation fail closed.

## 5. Review and answer

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "serve", "--company", $CompanyId,
    "--host", "127.0.0.1", "--port", "8000"
  )
```

Open `http://127.0.0.1:8000`. Review each claim, exact excerpt, locator, and
confidence. A factual answer requires `evidence_sufficient: true` and citations
with `verified: true`, `source_uri`, `locator`, and an exact supporting excerpt.

If evidence is insufficient, say so. Never fill the gap with Memory or Skill
text.
