# Privacy and security

## Local-first

Local Knowledge Suite has no telemetry, analytics, advertising, or hosted
John-IDK service. The runtime does not import code from a target project.

Data leaves the machine only when the user explicitly configures or invokes a
Git remote, public website crawl, export, copy, or publication. Model inference
is restricted to LM Studio on the local loopback interface. Remote, LAN,
credential-bearing, query-bearing, and fragment-bearing model URLs are
rejected, and model calls ignore proxy settings.

## Secrets

Never store passwords, tokens, private keys, recovery codes, or
credential-bearing connection strings in Memory, Company Knowledge, prompts,
configuration, or Git. Company credentials are encrypted; the master key is
kept in Windows Credential Manager under the company ID.

## Local project authorization

A company-enabled project manifest is an identity declaration, not permission
by itself. The machine-local registry must also contain the exact project ID,
canonical project path, and company ID created by an explicit `project init`
or `project restore`. Copying or editing `project.toml` cannot grant company
access. Moving or cloning a project fails closed until it is explicitly
restored on that machine. Unregistering a company revokes its project
authorizations.

## Git boundaries

The product repository may be public. Company repositories should normally be
private. Never commit `.memorizer/`, `.ckb/`, `.local-sources/`, registry data,
`web/dist/`, or credentials.

The runtime checks NUL-delimited Git paths case-insensitively on Windows. A
project that tracks `.memorizer/`, or a company repository that tracks the
private state/source paths above, is rejected before status, recall, or
registration can use that content. Remove the path from the Git index/history
and restore local state through the migration flow; `.gitignore` alone cannot
protect a file that is already tracked.

A Memory snapshot is an explicit plain-text exception. Sensitive notes are
excluded by default and a public export requires an extra acknowledgement.
Review every exported file.

## Evidence gate

A company claim is factual only when its result has sufficient evidence and
each used citation has `verified: true`, `source_uri`, `locator`, and an exact
supporting excerpt. A moved, missing, or changed source fails the gate. Git
cannot independently verify a current source.

## Reporting

- Normal bugs: [GitHub Issues](https://github.com/luutru433-coder/local-knowledge-suite/issues)
- Vulnerabilities: [private vulnerability reporting](https://github.com/luutru433-coder/local-knowledge-suite/security/advisories/new)

Never disclose private company data or an exploit in a public issue.
