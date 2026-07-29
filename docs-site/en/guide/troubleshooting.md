# Troubleshooting

The commands below use `$PluginRoot` resolved as shown in
[Quick installation](/en/guide/getting-started).

## Start with two checks

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("project", "doctor", "--root", $ProjectRoot)
```

Then call MCP `knowledge_status` with the same absolute root. Read warnings
before editing a manifest or database.

## Skills or MCP tools are missing

- Confirm the plugin is installed.
- Restart Codex and open a new task.
- In vendored mode, trust the project and run `-Action Verify`.
- Confirm the marked Local Knowledge block remains in `.codex/config.toml`.
- If an update caused the issue, repeat the exact
  [tagged update/rollback flow](/en/guide/install-modes); do not mix files from
  two tags.

## Company is not registered

Register the cloned company on this Windows account:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @(
    "company", "register", "--root", $CompanyRoot, "--admin", "admin"
  )
```

Do not hand-edit the registry or company ID.

If an old root is mapped incorrectly, run
`company unregister --root ABSOLUTE_COMPANY_ROOT` as described under
[Uninstall](/en/guide/uninstall), then register the correct root. Never delete
a mapping directly from the registry file.

## Migration is required

Preview, then apply:

```powershell
& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("migrate", "--root", $ProjectRoot, "--dry-run")

& "$PluginRoot\scripts\Invoke-LocalKnowledge.ps1" `
  -Tool local-knowledge `
  -ToolArguments @("migrate", "--root", $ProjectRoot, "--apply")
```

Migration from schema 1/0.2 to schema 2 creates a backup. Never change
`schema_version` manually.

## Memory has pending events

Use `$memorizer` to run status, distill, and validate. A capture succeeds only
when pending is zero. If derived state is stale, rebuild it from Markdown; do
not edit SQLite.

## Company results are attested, not factual

After a clone, canonical claims exist but source proof does not. Restore the
file under `.local-sources\` or re-crawl the website, then ingest again. Git
history is not current source verification.

## A scanned PDF has no text

Run company `health`. Install Tesseract with `eng` and `vie` packs for bilingual
scans. pypdfium2 handles embedded text and renders low-text pages for OCR.
Malformed PDFs must fail instead of publishing empty content.

## LM Studio is unavailable

Confirm the local server is running and the configured chat/embedding model
names are loaded. Chat failure blocks ingestion. Embedding failure degrades
search to lexical matching.

The endpoint must use `http://127.0.0.1:PORT/...`, `http://localhost:PORT/...`,
or a numeric IPv6 loopback address. V1 rejects LAN/Internet hosts, credentials
inside the URL, query strings, and fragments; it also ignores proxy environment
variables. Replace an old remote URL in `.ckb/config.json` with the local LM
Studio URL rather than weakening this boundary.

For unresolved issues, follow
[SUPPORT.md](https://github.com/luutru433-coder/local-knowledge-suite/blob/main/SUPPORT.md)
and redact all private data.
