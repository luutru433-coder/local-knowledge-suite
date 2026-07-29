# Global and vendored installation

Both modes use the same data model. They differ only in how a project finds the
plugin.

The commands below use `$PluginRoot` resolved as shown in
[Quick installation](/en/guide/getting-started).

```powershell
$ProjectRoot = (Resolve-Path ".").Path
```

## Global

Install once for one Windows account and use it across projects. Choose global
for simple centralized updates. It is the default for most users.

Review and commit `.local-knowledge/project.toml` and the managed `.gitignore`
additions so clones preserve the same project ID.

## Update or roll back global mode to an exact tag

Release tags are immutable. To move from `v1.0.0` to exactly `v1.0.1`, first
remove the plugin that references the marketplace, replace the marketplace ref,
and reinstall the plugin:

```powershell
codex plugin remove local-knowledge-suite@john-idk
codex plugin marketplace remove john-idk
codex plugin marketplace add luutru433-coder/local-knowledge-suite --ref v1.0.1
codex plugin add local-knowledge-suite@john-idk
```

Restart Codex, open a new task, resolve `$PluginRoot` again, and run:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "doctor", "--root", $ProjectRoot)
```

To roll back, repeat the same first four commands with the tested tag, such as
`--ref v1.0.0`. `codex plugin marketplace upgrade john-idk` only refreshes the
marketplace's currently configured ref; it does not switch an immutable tag to
another tag.

Roll back only when the release notes confirm manifest/schema compatibility.
An older runtime fails closed on a newer schema; never hand-edit
`schema_version`. If incompatible, restore the appropriate migration backup or
reinstall the newer release.

## Vendored

Commit a versioned snapshot under
`PROJECT_ROOT\tools\local-knowledge-suite\`, its hash lock, three materialized
repository skills under `PROJECT_ROOT\.agents\skills\`, and the plugin's
MCP-only marked Codex config block.

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "project", "init", "--root", $ProjectRoot,
    "--profile", "memory-only", "--install-mode", "vendored"
  )

& "$PluginRoot\scripts\Install-LocalKnowledgeVendor.ps1" `
  -Action Install -ProjectRoot $ProjectRoot
```

Verify after cloning:

```powershell
& "$ProjectRoot\tools\local-knowledge-suite\scripts\Install-LocalKnowledgeVendor.ps1" `
  -Action Verify `
  -ProjectRoot $ProjectRoot `
  -PluginRoot "$ProjectRoot\tools\local-knowledge-suite"
```

Choose vendored when CI, audits, or a team must run the exact tested snapshot.

Review and commit exactly these portable installation paths:

```powershell
git -C $ProjectRoot add `
  tools/local-knowledge-suite `
  .agents/skills/manage-local-knowledge `
  .agents/skills/memorizer `
  .agents/skills/company-knowledge-base `
  .local-knowledge/project.toml `
  .local-knowledge/vendor-lock.json `
  .codex/config.toml

git -C $ProjectRoot diff --cached
```

The three skill directories are real copies, not symlinks. Codex discovers
repository skills from `.agents/skills`; the managed `.codex/config.toml` block
only launches the vendored MCP server. Do not commit `.memorizer/`, `.ckb/`,
`.local-sources/`, credentials, or the machine registry.

Upgrade from a newer source:

```powershell
& "$PluginRoot\scripts\Install-LocalKnowledgeVendor.ps1" `
  -Action Upgrade -ProjectRoot $ProjectRoot
```

Install refuses to overwrite a pre-existing repository skill with one of the
three managed names. Upgrade refuses modified vendor files, backs up the vendor
snapshot and all managed skill copies under
`%LOCALAPPDATA%\LocalKnowledgeSuite\vendor-backups\`, restores them together on
failure, preserves unrelated skills, and changes only the suite's marked
configuration block.
