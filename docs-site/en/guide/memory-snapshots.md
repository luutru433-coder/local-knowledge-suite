# Move Memory with a snapshot

The Memory vault is local and ignored by Git. A snapshot moves selected
authoritative notes through an explicit, reviewable workflow.

The commands below use `$PluginRoot` resolved as shown in
[Quick installation](/en/guide/getting-started).

On the old PC, assign and resolve both paths first:

```powershell
$ProjectRoot = (Resolve-Path "D:\Projects\northstar-support").Path
$SnapshotPath = Join-Path $ProjectRoot ".local-knowledge\memory-snapshot"
```

::: danger Snapshots are plain text
Snapshots are **not encrypted**. Anyone who can read the files or Git history
can read their contents. Review every file before committing or sharing.
:::

## Export for a private repository

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "memory", "export",
    "--root", $ProjectRoot,
    "--output", $SnapshotPath,
    "--git-visibility", "private"
  )
```

The deterministic snapshot contains `snapshot.json`, `memory/config.json`, and
`memory/notes/*.md`, with SHA-256 checksums. It excludes the daily journal,
SQLite/index, cache, lock, `MEMORY.md`, and generated entity views.

The manifest fingerprint covers the schema, format, project ID, metadata, and
canonical file entries. This is an unkeyed integrity check, not cryptographic
proof of origin or authenticity: anyone who can edit the snapshot can
recompute it. Use trusted transfer or reviewed Git history as well.

## Transfer through the user's project Git repository

Open and review every snapshot file. Confirm there is no credential, company
data, or unintended personal information, then inspect the exact diff:

```powershell
git -C $ProjectRoot status --short
git -C $ProjectRoot add .local-knowledge/memory-snapshot
git -C $ProjectRoot diff --cached -- .local-knowledge/memory-snapshot
```

If review finds content that must not be committed, unstage it and repair or
export again:

```powershell
git -C $ProjectRoot restore --staged .local-knowledge/memory-snapshot
```

Only after the staged diff is approved:

```powershell
git -C $ProjectRoot commit -m "chore(memory): add reviewed project snapshot"
git -C $ProjectRoot push
```

After review, PowerShell 7 users may join `git commit ... && git push`;
Windows PowerShell 5.1 must run them as separate lines. Do this only in the
user's project repository. The Local Knowledge Suite product repository ignores
`.local-knowledge/memory-snapshot/`, so real Memory is never included in the
product release.

## Sensitive Memory

Sensitive notes are excluded by default. Including them requires both flags:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "memory", "export",
    "--root", $ProjectRoot,
    "--output", $SnapshotPath,
    "--git-visibility", "private",
    "--include-sensitive",
    "--acknowledge-sensitive"
  )
```

Passwords, tokens, private keys, and recovery phrases must never be stored in
Memory at all.

## Public repositories

An export intended for a public repository is blocked without an additional
acknowledgement:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "memory", "export",
    "--root", $ProjectRoot,
    "--output", $SnapshotPath,
    "--git-visibility", "public",
    "--allow-public"
  )
```

`--allow-public` does not sanitize the data. It only records that the operator
accepted the risk.

## Import

On the new device, clone or pull the same project so its `project_id` is
preserved:

```powershell
$ProjectRepositoryUrl = "https://github.com/your-org/northstar-support.git"
$ProjectRoot = "D:\Projects\northstar-support"
git clone $ProjectRepositoryUrl $ProjectRoot
# If the clone already exists, use: git -C $ProjectRoot pull
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
$SnapshotPath = Join-Path $ProjectRoot ".local-knowledge\memory-snapshot"
```

Then import:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "memory", "import",
    "--root", $ProjectRoot,
    "--input", $SnapshotPath
  )
```

By default, import requires an empty vault, a matching project ID, and valid
checksums. `--replace` creates a local backup first. V1 does not merge two
snapshots.

Run `project doctor` and `knowledge_status`. Check snapshot `present`, `valid`,
`freshness`, `item_count`, and `includes_sensitive`.
