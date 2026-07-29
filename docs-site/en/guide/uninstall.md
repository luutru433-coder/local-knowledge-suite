# Uninstall

Removing the plugin, unregistering a company, and deleting data are three
separate operations. None automatically deletes a company repository.

The commands below use `$PluginRoot` resolved as shown in
[Quick installation](/en/guide/getting-started).

## 1. Back up deliberately

- Push application code.
- Export a reviewed Memory snapshot only if needed.
- Push the company manifest and `knowledge\` to a private remote.
- Back up authorized originals separately.

Do not commit whole `.memorizer\`, `.ckb\`, or `.local-sources\` directories.

## 2. Unregister a company before removing the plugin

Do this when removing a company mapping from the current Windows account.
`$CompanyRoot` must be an absolute, existing path with the correct manifest:

```powershell
$CompanyRoot = (Resolve-Path "D:\Knowledge\Northstar-Bicycle-Labs").Path

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "unregister",
    "--root", $CompanyRoot
  )
```

The runtime verifies the root and `company_id` before removing that exact
mapping. Repeating the command is safe when the mapping is already absent. It
always preserves the repository, `.ckb\`, `.local-sources\`, `knowledge\`,
manifest, and credential key.

Only when the data owner explicitly requires deletion of this company's
encryption key:

```powershell
$CompanyId = "northstar-bicycle-labs"

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "unregister",
    "--root", $CompanyRoot,
    "--purge-credential-key",
    "--confirm-company", $CompanyId
  )
```

Both flags are required and the ID must exactly match the manifest. Removing
the master key can make encrypted credentials in `.ckb\` unreadable. Never
hand-edit `registry.json` or Windows Credential Manager.

## 3. Delete local data only when intended

After confirming backups, resolve and inspect every target. File Explorer can
remove these exact directories deliberately:

- `$ProjectRoot\.memorizer\`: one project's Memory;
- `$CompanyRoot\.ckb\`: one company's index, users, jobs, and portal state;
- `$CompanyRoot\.local-sources\`: one company's local sources.

Never recursively delete a home directory, workspace root, broad glob, or
unresolved variable. Canonical `knowledge\` and Git history are not cache.
Delete the entire company repository only with explicit authorization from its
data owner.

## 4. Remove the plugin

Open Codex Plugins, select `Local Knowledge Suite` from `john-idk`, and choose
Uninstall. Restart Codex and open a new task.

For a vendored project:

1. commit/stash work in progress and confirm the staged diff has no unrelated
   files;
2. run `-Action Verify` to check `vendor-lock.json`, the runtime, and all three
   managed skill copies before removal;
3. remove only the marked Local Knowledge block from `.codex\config.toml`;
4. remove exactly `tools\local-knowledge-suite\`,
   `.local-knowledge\vendor-lock.json`,
   `.agents\skills\manage-local-knowledge\`, `.agents\skills\memorizer\`, and
   `.agents\skills\company-knowledge-base\`;
5. review the staged diff to confirm nothing outside that list was removed,
   then commit the complete uninstall together; and
6. keep the project manifest if you intend to reinstall and restore later.

Do not remove unrelated Codex configuration.
