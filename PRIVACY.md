# Privacy

Local Knowledge Suite is designed to run on the user's Windows computer.

## Data handled

The plugin can process:

- project manifests and project-scoped Memory;
- documents and public website pages explicitly registered by the user;
- canonical company knowledge, citations, review history, and Git metadata;
- local account names and encrypted company-scoped credentials; and
- operational logs, indexes, and job state.

## Where data goes

Local Knowledge Suite does not include telemetry, analytics, advertising, or a
hosted John-IDK service. Data stays on the local machine unless the user
explicitly:

- configures and uses a Git remote;
- registers a public website for crawling;
- exports, copies, or publishes data.

Model inference is restricted to an LM Studio endpoint on the local loopback
interface. Remote, LAN, user-info-bearing, query-bearing, and fragment-bearing
model URLs are rejected, and proxy settings are ignored for model calls. The
runtime does not send source text to a remote model endpoint. Users remain
responsible for the Git hosts and public websites they explicitly use.

## Storage boundaries

- `.memorizer/` belongs to one project.
- `.local-sources/` and `.ckb/` belong to one company repository.
- Windows Credential Manager holds company-scoped secret keys.
- `%LOCALAPPDATA%\LocalKnowledgeSuite\registry.json` maps company IDs to local
  paths on one Windows account.

These stores are ignored by Git by default. Do not copy them across projects or
companies.

## Memory snapshots

Memory export is opt-in. A snapshot is readable plain text, not encrypted.
Sensitive Memory is excluded by default. Including it requires both
`--include-sensitive` and `--acknowledge-sensitive`; exporting for a public
repository additionally requires `--git-visibility public --allow-public`.
Review every exported file before committing or sharing it.

Snapshot SHA-256 values are unkeyed integrity checks, not cryptographic proof
of origin or authenticity. Anyone who can edit a snapshot can recompute them,
so use trusted transfer or reviewed Git history in addition to checksum
validation.

## User control

Users may inspect, export, correct, or remove their own local data. Uninstalling
the plugin does not delete project or company repositories. Follow the
documentation to back up what is needed, then remove local stores deliberately.

Privacy questions may be opened as a
[GitHub issue](https://github.com/luutru433-coder/local-knowledge-suite/issues).
Do not include private company data or credentials in an issue.
