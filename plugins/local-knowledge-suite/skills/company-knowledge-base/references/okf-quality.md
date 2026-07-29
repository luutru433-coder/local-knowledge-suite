# OKF and publication quality

## Concept contract

Store canonical concepts as UTF-8 Markdown with parseable YAML frontmatter. Require a non-empty `type`; preserve optional `title`, `description`, `resource`, `tags`, `timestamp`, and unknown producer fields. Use standard Markdown links.

Reserve `index.md` for progressive-disclosure listings and `log.md` for newest-first ISO-date history. Do not use those names for concepts.

List external evidence under the final `# Citations` heading. A citation may target an external URL, a bundle-relative concept, or a mirrored reference concept. Preserve exact excerpts and locators; accent folding belongs only in search indexes.

## Automatic publication gate

Publish automatically only when all conditions hold:

- at least one factual claim exists;
- cited-claim coverage is at least 0.90;
- every published claim has a source locator and exact supporting excerpt;
- minimum claim confidence is at least 0.85;
- average claim confidence is at least 0.90;
- the concept and whole bundle validate;
- protected-branch and role checks pass; and
- Git synchronization and commit complete without conflict.

Route everything else to review. Human approval may resolve model uncertainty but must never turn an unsupported claim into canonical knowledge.
