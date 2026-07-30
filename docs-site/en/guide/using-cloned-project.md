# Use a cloned GitHub project without a terminal

This guide is for someone who receives a project through GitHub and wants to
continue using Local Knowledge Suite without learning PowerShell or Git
commands.

The basic flow is:

1. clone the project with GitHub Desktop;
2. open the exact project folder in Codex Desktop;
3. paste the natural-language prompts below; and
4. select **Allow** only for an operation you requested and understand.

Never paste passwords, GitHub tokens, private keys, session cookies, or recovery
codes into Codex chat.

## What you need

Install these Windows applications:

- **GitHub Desktop**;
- **Codex Desktop**;
- **Python 3.12**; and
- **uv**.

Normal users do not need Node.js, npm, or pnpm. Those tools are only required
to develop the Local Knowledge Suite product itself.

If you are unsure what is installed, ask Codex:

```text
Check whether this Windows PC has GitHub Desktop, Python 3.12, and uv for
Local Knowledge Suite. Do not install anything yet. For anything missing,
use only official sources, explain the buttons I must select, and ask for
approval before installation. I do not want to type terminal commands.
```

A project using Company Knowledge may also need LM Studio, one local chat
model, one local embedding model, access to a separate company repository, and
an approved copy of the original source files.

## Understand the three data layers

- **Project repository:** the application you are working on.
- **Memory:** decisions and conventions private to that one project.
- **Company Knowledge:** shared company facts that require verified citations.

A project can use Memory without having a company.

## Clone the project with GitHub Desktop

1. Open the project repository in a browser.
2. Select the green **Code** button.
3. Select **Local**.
4. Select **Open with GitHub Desktop**.
5. In **Local path**, choose a simple folder such as `Documents\Projects`.
6. Select **Clone**.
7. Wait until GitHub Desktop shows **No local changes**.

Do not copy an old project folder with File Explorer as a replacement for a
real clone. A clone on a new path must be explicitly restored.

## Open the exact folder in Codex

1. Open Codex Desktop.
2. Select **Open folder**.
3. Select the repository you just cloned.
4. Do not select a parent folder containing several repositories.
5. Create a new task.

## Inspect first and make no changes

Paste:

```text
Inspect Local Knowledge for the open project. Do not modify, migrate, restore,
or create anything yet. Tell me whether the project is memory-only, combined,
or company-only; whether the plugin is installed; and what the next safe step is.
```

Codex should report one of these states:

| Result | Meaning |
| --- | --- |
| Plugin missing | Install the tagged plugin first. |
| Project not initialized | Choose a profile and bootstrap it. |
| Restore required | The manifest exists, but this is a new machine or path. |
| Migration required | Preview and apply a supported schema migration. |
| Healthy | Continue to normal recall and capture. |

Never edit `schema_version`, `project_id`, or `company_id` manually.

## Ask Codex to install the plugin

If the plugin is missing, paste:

```text
Install Local Knowledge Suite from the GitHub repository
luutru433-coder/local-knowledge-suite, pinned to release v1.0.0.
Check for an older installation or duplicate marketplace first.
Install only local-knowledge-suite@john-idk and verify that its MCP exposes
exactly four tools.
```

Read each approval dialog and verify:

- repository owner: `luutru433-coder`;
- release: `v1.0.0`; and
- plugin: `local-knowledge-suite@john-idk`.

After installation, close the task and open a new one. Then paste:

```text
Verify that Local Knowledge Suite version 1.0.0 is active and that its MCP
exposes bootstrap_workspace, knowledge_status, recall_context, and
capture_memory. Do not modify project data.
```

## Initialize a new Memory-only project

Use this only when the repository has no Local Knowledge manifest:

```text
Use manage-local-knowledge to initialize the open project as memory-only with
global installation. Check the result and tell me exactly which files should
be committed to the application repository.
```

In GitHub Desktop:

1. open **Changes**;
2. review the project manifest and managed `.gitignore` changes;
3. do not commit Memory databases, caches, or locks;
4. enter a commit summary such as `Initialize Local Knowledge`;
5. select **Commit to current branch**; and
6. select **Push origin**.

Do not choose `combined` unless the company repository and company ID are
already available.

## Restore an existing project

For a Memory-only project, paste:

```text
This project was cloned on a new PC. Restore its existing project identity,
preserve its profile and company binding, and run project doctor. Do not create
a new project ID.
```

If a reviewed Memory snapshot exists, ask Codex to inspect it before import.
Snapshots are readable plain text and are not encrypted.

For a `combined` or `company-only` project, register the company repository
before restoring the project.

## Handle a migration

First request a preview:

```text
Preview the supported Local Knowledge migration. Do not apply it. List the
current and target schema, every store that will change, the backup location,
and every affected repository.
```

After reviewing the plan, paste:

```text
Apply the supported migration with backups. Do not edit schema numbers
manually. Restore the project if required and run project doctor. Stop and
report the backup path if any step fails.
```

Review each affected repository in GitHub Desktop before committing its
manifest changes.

## Use Memory in everyday work

Recall project context before a change:

```text
Before changing the public API, recall relevant project Memory and skill
instructions. Keep remembered decisions separate from new inference.
```

Capture one durable convention:

```text
Remember for this project: every public API must include request and response
examples in its documentation. This is a durable project convention.
```

Do not store temporary screen state, unconfirmed guesses, facts copied from
company documents, or any credential value.

Correct an old memory through supersession:

```text
Find the active Memory about API naming and show it to me. Then supersede it
with this confirmed convention: public endpoint names use kebab-case.
Preserve the old item as history.
```

## Restore Company Knowledge

### Clone the company repository separately

Clone the private company repository with GitHub Desktop. Keep it outside the
application project, for example:

- project: `Documents\Projects\northstar-support`;
- company: `Documents\CompanyKnowledge\northstar`.

### Register the company

Paste:

```text
This project uses Company Knowledge. The company repository is at
[PASTE THE COMPANY REPOSITORY PATH].
Validate its manifest and Git state first. If its identity is valid, register
it on this Windows account. Do not ingest sources or restore the project yet.
```

Enter administrator passwords through the interactive prompt or local portal,
never through chat.

After registration:

```text
The company is registered. Restore the open project using its existing project
ID and company ID, preserve the profile and binding, and run project doctor.
```

### Prepare LM Studio

In LM Studio:

1. download a suitable local chat model;
2. download an embedding model;
3. load both models;
4. start the local server; and
5. confirm the server is running.

Ask Codex to list the exact active model IDs before changing configuration.
Store an optional LM Studio bearer token only in
**Company Portal → Settings → Credentials**.

### Restore approved source files

The company Git repository does not contain private source PDFs or operational
`.ckb` state. Obtain the approved source inventory and source files from the
administrator, then place the files under the company's `.local-sources`
folder.

Paste:

```text
Compare .local-sources with the approved source inventory. Show me every file,
website, allowed domain, and branch before registration or ingestion.
Reject anything outside the authorized boundary.
```

After review:

```text
Register the approved sources, enqueue new ingestion jobs, run them, and retain
failed job history. Do not use any source outside the reviewed inventory.
```

### Test a cited answer

```text
Use Company Knowledge to answer the warranty-period question. Answer only when
evidence_sufficient is true. For every used claim, include the verified source,
locator, and exact supporting excerpt. Report an evidence gap instead of guessing.
```

## Final readiness check

Paste:

```text
Run a final Local Knowledge check for this project. Present a table with plugin
version, project schema, profile, project ID, company registration, Memory
health, pending events, migration state, vendor verification, and warnings.
Do not modify anything.
```

The project is ready when:

- the expected plugin version is active;
- MCP exposes exactly four public tools;
- the project schema is current;
- no migration is pending;
- Memory has no pending events;
- the company is registered when required;
- `project doctor` succeeds; and
- a Company Knowledge test answer contains valid citations.

## Troubleshooting prompt

If MCP does not start:

```text
Diagnose Local Knowledge MCP without deleting data. Check plugin version,
Python 3.12, uv, the runtime environment, and cache paths. Separate runtime
problems from project-manifest problems, then propose the least destructive fix.
```

If company search returns nothing, check company registration, project restore,
LM Studio health, current source files, ingestion jobs, publication status,
citation verification, and branch access—in that order.
