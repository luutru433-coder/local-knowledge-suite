# Contributing

Thank you for improving Local Knowledge Suite.

## Before starting

- Discuss large changes in a GitHub issue.
- Keep Windows as the supported v1 platform.
- Use fictional data in tests, docs, screenshots, and bug reports.
- Preserve the separation between skill instructions, project Memory, and
  citation-backed company knowledge.
- Never weaken secret, citation, source-boundary, migration, or Git gates.

## Development setup

Use Git, `uv`, Python 3.12, Node 22, and the repository-pinned pnpm 11.9.0:

```powershell
pnpm install --frozen-lockfile
pnpm --filter @local-knowledge-suite/docs build
pnpm --filter @local-knowledge-suite/portal build

uv sync --project .\plugins\local-knowledge-suite\runtime `
  --frozen --extra build --extra dev --python 3.12
uv run --project .\plugins\local-knowledge-suite\runtime `
  --frozen --extra build --extra dev --python 3.12 python -m pytest tests
```

Run the repository validation commands described in
[docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).

## Pull requests

- Keep each pull request focused.
- Add or update tests for changed behavior.
- Update both Vietnamese and English docs when public behavior changes.
- Use Conventional Commits for commit messages.
- Confirm no real company or personal data appears in the diff.
- Confirm third-party license notices remain complete.

By contributing, you agree that your contribution is licensed under the MIT
License.
