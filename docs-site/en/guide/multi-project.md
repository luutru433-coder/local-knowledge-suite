# One company, many projects

```text
Store project    ─┐
Support project  ─┼─ company_id: northstar-bicycle-labs
Internal project ─┘             │
                                └─ shared Company Knowledge

Each project ───────────────────── separate .memorizer
```

The Windows registry maps one stable company ID to its current local
repository path. The company may live on another drive while several projects
resolve it safely. It also records a separate machine-local authorization for
each exact project ID and canonical path; knowing a company ID alone grants no
access.

The commands below use `$PluginRoot` resolved as shown in
[Quick installation](/en/guide/getting-started).

## Add another project

1. Run `company list` and copy the correct ID.
2. Resolve the absolute project path.
3. Choose `combined` or `company-only`.
4. Run `project doctor`.
5. Trust the project and open a new Codex task.

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "project", "init",
    "--root", "D:\Projects\northstar-store",
    "--company", "northstar-bicycle-labs",
    "--profile", "combined",
    "--install-mode", "global"
  )
```

Repeat with the same company ID. Project IDs and Memory remain distinct.
`project init` enrolls that exact project path. After a move or clone, use
`project restore` to re-enroll it deliberately on the new machine.

Projects with the same company ID share canonical `knowledge/`, reviewed
claims, citations, Git history, and verified company search through the company
boundary. `.ckb/`, its database and jobs, and `.local-sources/` are also
**company-scoped**, not project-scoped. Projects for that company may use them
indirectly through the registered ID, but must never copy or expose those
directories inside a project repository.

Each project's `.memorizer/`, project ID, and manifest remain separate.
Credentials and registry mappings stay machine/company-scoped. No source,
state, credential, or result crosses between different company IDs.

Example: the support project asks for the return policy and must cite Company
Knowledge. The store project remembers that its button component is named
`PrimaryButton`; that Memory does not appear in support.

To share a convention across all projects, add it to an authorized company
source, ingest, review, and cite it. Do not copy Memory vaults.
