# New Windows PC migration checklist

## Before moving

- [ ] Application projects have committed and pushed
      `.local-knowledge/project.toml` and the managed `.gitignore` additions.
- [ ] Every vendored project has also committed `tools/local-knowledge-suite/`,
      `.local-knowledge/vendor-lock.json`, `.codex/config.toml`, and all three
      managed `.agents/skills/` directories.
- [ ] Company manifest and `knowledge/` are pushed to a private remote.
- [ ] Git contains no `.ckb/`, `.memorizer/`, `.local-sources/`, or secret.
- [ ] Any needed Memory snapshot was exported, reviewed file by file, and
      checksum-verified.
- [ ] Every project profile is recorded; `memory-only` will skip all company
      steps.
- [ ] Authorized company sources have a separate approved backup.
- [ ] A private source inventory records `kind`, `path`, `title`,
      `allow-domain`, and `branch`; file/folder paths are relative to
      `.local-sources/`.
- [ ] An access inventory records username, global role, and branch-role
      membership without passwords or tokens.
- [ ] The required plugin release tag is recorded, for example `v1.0.0`.

## On the new PC

- [ ] Install Windows updates, Git, Codex, `uv`, and Python 3.12.
- [ ] Add `luutru433-coder/local-knowledge-suite` at the exact release tag.
- [ ] Install `local-knowledge-suite@john-idk`.
- [ ] Restart Codex.
- [ ] Assign `$ProjectRoot` and clone each project.
- [ ] Read the project profile before restoring it.
- [ ] For `memory-only`, run `project restore`, import the Memory snapshot if
      one exists, and run `-Action Verify` for vendored mode.
- [ ] Vendored verification confirms all three real `.agents/skills/` copies;
      no managed skill is missing, modified, extra, or a symlink.
- [ ] A `memory-only` project skips every remaining company item.
- [ ] For `combined`/`company-only`, **do not run `project restore` yet**:
      assign `$CompanyRoot` and `$CompanyId`, clone the private company
      repository, and run `company register` first.
- [ ] Create a new local password; do not copy Credential Manager.
- [ ] Only after `company register` succeeds, run `project restore`, import the
      Memory snapshot if one exists, and run `-Action Verify` for vendored mode.
- [ ] Replace `.ckb/config.json` placeholders with the correct URL and exact
      chat/embedding model IDs.
- [ ] Re-enter any LM Studio bearer token and private-Git credential through
      portal Settings.
- [ ] Run company `health` before source-add/ingest.
- [ ] Restore relative source paths and run a new source-add/ingest/job for
      every inventory entry; re-crawl websites under their allowlists.
- [ ] Recreate users/global roles and branch-role memberships from the access
      inventory.
- [ ] Run company `health` again.
- [ ] Run `project doctor`.
- [ ] Trust the project and open a new Codex task.

## Acceptance

- [ ] `knowledge_status` reports compatible runtime 1.0.0 and schema 2.
- [ ] Memory has zero pending events.
- [ ] Snapshot status is valid and has the expected item count.
- [ ] A Memory-only project does not require a company.
- [ ] Combined/company-only projects resolve the correct company ID.
- [ ] Company database/chat model are ready; embedding/OCR match source needs.
- [ ] Users and branch roles match the access inventory.
- [ ] A test Memory recall stays in the correct project.
- [ ] A test company answer has verified citations and exact excerpts.
- [ ] `git status` exposes no unintended machine-local or real data.
