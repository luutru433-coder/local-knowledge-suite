# Local Knowledge Suite

[Tiếng Việt](README.vi.md) · [Documentation](https://luutru433-coder.github.io/local-knowledge-suite/en/) · [Security](SECURITY.md) · [Support](SUPPORT.md)

Local Knowledge Suite is a free, open-source Codex plugin for Windows. It gives
each project a private memory vault and can optionally connect many projects to
one citation-backed company knowledge base.

## What it does

- **Skills** tell Codex how to handle memory and company knowledge safely.
- **MCP tools** let Codex initialize a workspace, check its health, recall
  context, and save durable project memory without repeated copy and paste.
- **Project memory** keeps preferences and decisions inside one project.
- **Company knowledge** lets several projects reuse verified facts with source
  excerpts and citations.

The plugin runs locally. It includes no telemetry or analytics. Windows is the
supported release platform for v1.

## Five-minute start: memory only

Requirements: Windows 10/11, PowerShell 5.1+, Git, Codex, and
[`uv`](https://docs.astral.sh/uv/).

Install the tagged marketplace directly from GitHub:

```powershell
codex plugin marketplace add luutru433-coder/local-knowledge-suite --ref v1.0.0
codex plugin add local-knowledge-suite@john-idk
```

Restart Codex and open a new task. In your project, ask:

```text
Use $manage-local-knowledge to initialize this project as memory-only,
then check its Local Knowledge status.
```

No company repository is needed. The v1 default profile is `memory-only`.

Normal users can keep asking Codex and do not need a plugin path. To run the
CLI yourself, resolve and verify the installed path once:

```powershell
$Plugin = (codex plugin list --json | ConvertFrom-Json).installed |
  Where-Object { $_.pluginId -eq "local-knowledge-suite@john-idk" } |
  Select-Object -First 1

if (-not $Plugin) { throw "Local Knowledge Suite is not installed." }
$PluginRoot = [IO.Path]::GetFullPath([string]$Plugin.source.path)
$Launcher = Join-Path $PluginRoot "scripts\Invoke-LocalKnowledge.ps1"
if (-not (Test-Path -LiteralPath $Launcher)) {
  throw "Installed Local Knowledge Suite launcher was not found."
}

$ProjectRoot = (Resolve-Path ".").Path

& $Launcher `
  -Tool local-knowledge `
  -ToolArguments @(
    "project", "init", "--root", $ProjectRoot,
    "--profile", "memory-only", "--install-mode", "global"
  )
```

Always use an absolute project path. Run `project doctor` after setup and open a
new Codex task so the installed skills and MCP server are reloaded.

In the user's application repository (not this product source repository),
review and commit the stable project identity plus managed ignore rules:

```powershell
git add .local-knowledge/project.toml .gitignore
git diff --cached -- .local-knowledge/project.toml .gitignore
git commit -m "chore: initialize local knowledge workspace"
```

Without the committed project manifest, a clone gets a different project ID
and cannot import the original project's Memory snapshot.

## Add company knowledge

Create a separate repository for a fictional example company:

```powershell
$CompanyRoot = "D:\Knowledge\Northstar-Bicycle-Labs"
$AdminUser = "admin"

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "init", "--root", $CompanyRoot,
    "--name", "Northstar Bicycle Labs", "--admin", $AdminUser
  )
```

The command returns a stable `company_id`. Initialize a project with profile
`combined` to use both its own memory and the shared company evidence. V1 does
not rebind an existing Memory-only project; choose `combined` at its first
bootstrap. Put
approved originals under the ignored `COMPANY_ROOT\.local-sources\` directory;
commit only the company manifest and canonical `knowledge/`.

## Four MCP tools

| Tool | Simple meaning |
| --- | --- |
| `bootstrap_workspace` | Prepare one project safely and repeatedly. |
| `knowledge_status` | Check compatibility, stores, warnings, and pending work. |
| `recall_context` | Search skills, project memory, and verified company evidence separately. |
| `capture_memory` | Save one durable project-specific fact after redaction and distillation. |

`knowledge_status` and `recall_context` are non-destructive and idempotent, but
they are not declared read-only. Status may acquire transient local locks;
recall may distill already-captured pending Memory events and rebuild or cache
derived indexes.

Company answers must have `evidence_sufficient: true` and verified citations.
Memory and skill text never replace company evidence.

Memory snapshots are opt-in plain text for a user's own project repository.
This product repository ignores `.local-knowledge/memory-snapshot/` and never
ships real user Memory.

## Documentation

- [English user guide](https://luutru433-coder.github.io/local-knowledge-suite/en/)
- [Vietnamese user guide](https://luutru433-coder.github.io/local-knowledge-suite/)
- [Windows migration checklist](docs/MIGRATION_CHECKLIST.en.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Platform roadmap](docs/ROADMAP.md)
- [Distribution and commercial use](https://luutru433-coder.github.io/local-knowledge-suite/en/guide/distribution)
- [Release checklist](docs/RELEASE_CHECKLIST.md)

The guides cover global and vendored installation, company ingestion,
multi-project reuse, Memory export/import, privacy, security, troubleshooting,
uninstalling, MCP/CLI reference, and development with pnpm.

## Development

Node.js is not required to use a released plugin. Maintainers use Node 22 and
the repository-pinned pnpm 11.9.0 to build the portal and VitePress docs:

```powershell
pnpm install --frozen-lockfile
pnpm --filter @local-knowledge-suite/docs build
pnpm --filter @local-knowledge-suite/portal build

uv sync --project .\plugins\local-knowledge-suite\runtime `
  --frozen --extra build --extra dev --python 3.12
uv run --project .\plugins\local-knowledge-suite\runtime `
  --frozen --extra build --extra dev --python 3.12 python -m pytest tests
```

pnpm is used because one lockfile can reproduce both JavaScript workspaces,
its content-addressed store avoids duplicate downloads, and frozen installs
fail when a manifest and lockfile disagree.

## License

Copyright © 2026 John-IDK. Released under the [MIT License](LICENSE).
Third-party components keep their own licenses; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
