# Development and builds

Release users do not need Node.js. Maintainers use Windows, Python 3.12, `uv`,
Node 22, repository-pinned pnpm 11.9.0, and Git.

## Why pnpm instead of npm?

The repository contains a React portal and VitePress documentation. pnpm gives
the project:

1. one workspace lockfile for both packages;
2. a content-addressed store that avoids duplicate package copies;
3. strict dependency visibility;
4. frozen CI installs that fail on manifest/lock drift; and
5. filtered commands for one package.

npm remains a general JavaScript package manager, but it is not the supported
manager for this repository. Do not create `package-lock.json`.

## Commands

```powershell
pnpm install --frozen-lockfile
pnpm --filter @local-knowledge-suite/docs build
pnpm --filter @local-knowledge-suite/portal build

uv sync --project .\plugins\local-knowledge-suite\runtime `
  --frozen --extra build --extra dev --python 3.12
uv run --project .\plugins\local-knowledge-suite\runtime `
  --frozen --extra build --extra dev --python 3.12 python -m pytest tests
```

The release portal is built from source and copied into the runtime; CI checks
that the packaged artifact is current.

Use only fictional data in tests, docs, and screenshots. Keep dependencies
pinned. Update both languages for public behavior. Never weaken source,
secret, citation, or migration gates.

See [CONTRIBUTING.md](https://github.com/luutru433-coder/local-knowledge-suite/blob/main/CONTRIBUTING.md)
and the [release checklist](https://github.com/luutru433-coder/local-knowledge-suite/blob/main/docs/RELEASE_CHECKLIST.md).
