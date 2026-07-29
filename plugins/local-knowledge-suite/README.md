# Local Knowledge Suite 1.0

Windows-first Codex plugin for isolated project Memory and optional shared,
citation-backed company knowledge.

## Included

- `skills/`: routing, Memory, and Company Knowledge workflows;
- `runtime/`: pinned Python 3.12 runtime and prebuilt local portal;
- `.mcp.json`: exactly four local stdio tools; and
- `scripts/`: pinned launcher and vendored installation helpers.

The plugin contains no company path or development-workspace dependency.

## Start with Memory only

After installing the plugin, restart Codex, open the project in a new task, and
ask:

```text
Use $manage-local-knowledge to initialize this project as memory-only,
then check its status.
```

`memory-only` is the v1 default and needs no company. Direct CLI equivalent:

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

In a user's application repository, review and commit
`.local-knowledge/project.toml` and the managed `.gitignore` additions. The
manifest preserves `project_id` across clones; without it, a Memory snapshot
cannot be imported on another device.

## Data boundaries

| Store | Purpose | Portability |
| --- | --- | --- |
| `.local-knowledge/project.toml` | Stable project identity and profile | Commit in an application project |
| `.memorizer/` | One project's Memory | Ignore; use reviewed snapshot export when needed |
| company `knowledge/` | Canonical reviewed knowledge | Commit to a normally-private company repo |
| company `.local-sources/` | Authorized original documents | Ignore and restore separately |
| company `.ckb/` | Index, jobs, portal state | Ignore and rebuild |
| Windows registry/credentials | Machine mapping and secrets | Never copy or commit |

Projects sharing one company ID share only company evidence. Their Memory stays
isolated.

## MCP tools

- `bootstrap_workspace(root, company_id=None, profile="memory-only", install_mode="global")`
- `knowledge_status(root)`
- `recall_context(...)`
- `capture_memory(...)`

Status and recall are non-destructive and idempotent, but they are not
read-only MCP operations. Status may acquire transient locks; recall may
distill already-captured pending Memory events and rebuild derived indexes.

Company claims are usable only when `evidence_sufficient` is true and every
relied-on citation is verified with a source URI, locator, and exact excerpt.

## More help

- [Vietnamese documentation](https://luutru433-coder.github.io/local-knowledge-suite/)
- [English documentation](https://luutru433-coder.github.io/local-knowledge-suite/en/)
- [Windows migration checklist](https://github.com/luutru433-coder/local-knowledge-suite/blob/main/docs/MIGRATION_CHECKLIST.en.md)
- [Distribution and commercial use](https://luutru433-coder.github.io/local-knowledge-suite/en/guide/distribution)
- [Privacy](https://luutru433-coder.github.io/local-knowledge-suite/en/privacy/)
- [Security](https://github.com/luutru433-coder/local-knowledge-suite/blob/main/SECURITY.md)

Copyright © 2026 John-IDK. MIT License.
