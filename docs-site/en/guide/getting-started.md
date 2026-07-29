# Quick installation

## 1. Requirements

Install Windows 10/11, PowerShell 5.1+, Codex, Git, and
[`uv`](https://docs.astral.sh/uv/). Python 3.12 must be available to `uv` on
first run.

Node.js is not required to use the released plugin. LM Studio is needed only
for company-source ingestion. Tesseract is optional for scanned PDFs.

If scripts are blocked, allow them only in the current terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
```

## 2. Install a tagged release

```powershell
codex plugin marketplace add luutru433-coder/local-knowledge-suite --ref v1.0.0
codex plugin add local-knowledge-suite@john-idk
```

Restart Codex and open a new task. New tasks are the safe boundary at which
Codex reloads plugin skills and MCP definitions.

To change versions later, follow the exact
[tagged global update/rollback flow](/en/guide/install-modes). Do not overwrite
files from two releases.

## 3. Initialize a Memory-only project

Open the project in Codex and ask:

```text
Use $manage-local-knowledge to initialize the current project as memory-only,
then check its Local Knowledge status.
```

That is the simplest route and requires no plugin path. To run the CLI
yourself, resolve and verify the installed path:

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
    "project", "init",
    "--root", $ProjectRoot,
    "--profile", "memory-only",
    "--install-mode", "global"
  )

& $Launcher `
  -Tool local-knowledge `
  -ToolArguments @("project", "doctor", "--root", $ProjectRoot)
```

`memory-only` is the v1 default and does not need a `company_id`.

## 4. Commit project identity

In the user's application repository, not the Local Knowledge Suite source
repository:

```powershell
git add .local-knowledge/project.toml .gitignore
git diff --cached -- .local-knowledge/project.toml .gitignore
git commit -m "chore: initialize local knowledge workspace"
```

The manifest preserves `project_id` across clones. Without it, the original
project's Memory snapshot is rejected on the new device.

V1 does not rebind an initialized project. If company evidence is needed,
register the company first and select `combined` during initial bootstrap.

## 5. Try Memory

```text
Remember for this project: every public API needs a request and response
example.
```

The plugin searches for an equivalent or conflicting item, captures one small
signal, distills it immediately, and confirms no pending event remains.

Then ask:

```text
Which API conventions are remembered for this project?
```

## 6. Confirm success

`knowledge_status` or `project doctor` should report runtime `1.0.0`, schema
`2`, `memory-only`, a healthy Memory store, no pending event, no company
requirement, and no migration warning.

Next: [Skills, MCP, and the three data classes](/en/guide/concepts).
