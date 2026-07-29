# Public release checklist

Complete every item against the exact commit that will be tagged.

## Identity and legal

- [ ] Runtime, plugin, portal, docs package, and tag use the same SemVer.
- [ ] Author/copyright is `John-IDK`.
- [ ] Repository and Pages URLs use canonical lowercase `luutru433-coder`.
- [ ] MIT `LICENSE`, privacy, security, support, contribution, conduct, and
      changelog files are present.
- [ ] Locked dependency license inventory is reviewed.
- [ ] Normalized Python and complete active Windows pnpm-graph license
      inventories are reviewed; every reported Node identity is active and
      locked, with platform-skipped identities excluded deterministically.
- [ ] SBOM, exact PDFium/Chromium notices, and the hash-verified portal-runtime
      license manifest/files are included.
- [ ] Every parsed license identifier is on the explicit fail-closed allowlist;
      the reviewed MPL-2.0 uses (`certifi`, `lightningcss`, and `pathspec`)
      remain unchanged.

## Repository hygiene

- [ ] No user path, real company ID, private source, credential, registry,
      `.env`, `.codex/config.toml`, `.ckb/`, `.memorizer/`, `.local-sources/`,
      `.local-knowledge/company.toml`, top-level `knowledge/`, Local Knowledge
      backup/snapshot/vendor lock, or customer document is tracked.
- [ ] Examples and screenshots use only Northstar Bicycle Labs fictional data.
- [ ] `.local-knowledge/project.toml` from a maintainer machine is not tracked.
- [ ] Secret scanning and hardcoded-path checks pass.
- [ ] Release build/test/package runs with `contents: read` and no `GH_TOKEN`;
      only the final publish job receives `contents: write`.
- [ ] Pages build runs with `contents: read`; only the deploy job receives
      `pages: write` and `id-token: write`.
- [ ] Git working tree is clean.

## Build and test

- [ ] Python runtime lock is frozen and tests pass on Windows/Python 3.12.
- [ ] The PEP 517 build closure is exact in `[tool.uv]`
      `build-constraint-dependencies`, present in `uv.lock`, and present in the
      Python license inventory; a frozen offline sync succeeds after cache
      warm-up.
- [ ] Text PDF, scanned PDF OCR, and malformed PDF tests pass with pypdfium2.
- [ ] Portal typecheck/build succeeds and packaged assets match source output.
- [ ] VitePress VI/EN build and internal link checks pass.
- [ ] All three Skills pass `quick_validate.py`.
- [ ] Plugin and marketplace manifests validate.
- [ ] MCP initializes and exposes exactly four expected tools.
- [ ] Global, vendored install/verify, and schema migration smoke tests pass.
- [ ] Snapshot determinism, redaction, acknowledgement, checksum, empty-vault,
      wrong-project, and replace-backup tests pass.

## Clean-machine acceptance

- [ ] Install directly from the tag on a clean Windows account.
- [ ] A new Codex task sees three Skills and four MCP tools.
- [ ] Memory-only bootstrap works without a company.
- [ ] A cloned sample project restores and imports its snapshot.
- [ ] A private fictional company clone registers and re-ingests its sources.
- [ ] `project doctor` and `knowledge_status` pass.
- [ ] VI/EN Pages routes, including `/en/privacy/`, are reachable.

## Publish

- [ ] Before creating the first release tag, repository release immutability is
      enabled and a repository ruleset protects the exact `v*` tag namespace.
- [ ] The tested commit is on protected `main`.
- [ ] Repository is public only after every preceding gate passes.
- [ ] An annotated `v1.0.0` tag targets a commit that is on `origin/main`
      (lightweight tags are rejected).
- [ ] GitHub Release has a self-contained, buildable full-source ZIP plus
      SHA-256, SBOM, notices, and changelog; the extracted ZIP can install the
      plugin and contains no denied local/customer state.
- [ ] The publish job re-downloads the immutable workflow artifact and reruns
      checksum, archive, notice, SBOM, and annotated-tag provenance checks
      before creating the GitHub Release.
- [ ] Direct Python and portal runtime dependencies appear with the same exact
      identities in their manifests, lockfiles, normalized license reports,
      and the staged-product SBOM.
- [ ] Release notes accurately state that annotated-tag/main-head binding and SHA-256
      provide provenance/integrity checks against the trusted GitHub channel;
      they are not a cryptographic signature or independent attestation.
- [ ] GitHub Pages deploy targets the same commit.
- [ ] CodeQL, Dependabot, secret scanning, and private vulnerability reporting
      are enabled.
- [ ] The published GitHub Release UI reports `Immutable`; its tag and uploaded
      assets cannot be replaced.

## Release bundle contract

The main ZIP is not an install-only binary. It is the complete buildable source
product from all tracked public files: plugin/runtime, portal and docs source,
lockfiles, tests, CI, release tools, examples, legal files, and exact
third-party notices. After extraction, users can install the plugin from
`plugins/local-knowledge-suite`; maintainers can reproduce the portal, docs,
tests, license inventory, and release gates from the same archive.

For a manual tagged release, run the same order as CI: provenance and structural
gates, official plugin/Skill validators, runtime/MCP/vendor tests, pinned portal
and docs builds, the adversarial Node-inventory self-test, deterministic
Python/Node license reports, `New-Release.ps1`, CycloneDX over
`artifacts/staged-product-v<version>`, `Normalize-CycloneDxSbom.ps1`,
`Write-ReleaseChecksums.ps1`, then `Test-ReleaseArtifacts.ps1 -RequireSbom`.
Publish only the top-level files whose exact coverage appears in `SHA256SUMS`.
