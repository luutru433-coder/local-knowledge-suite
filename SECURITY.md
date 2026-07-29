# Security policy

## Supported version

Security fixes are provided for the latest stable `1.x` release. Preview and
older releases may require upgrading before a fix is applied.

## Report a vulnerability privately

Use
[GitHub private vulnerability reporting](https://github.com/luutru433-coder/local-knowledge-suite/security/advisories/new).
Do not open a public issue for a vulnerability, credential, private document,
or exploit.

Include the affected version, Windows version, reproduction steps, impact, and
the smallest safe proof of concept. Remove passwords, tokens, company source
text, and personal data.

## Expected safeguards

- Use only tagged releases obtained from the official repository and verify
  release checksums. A checksum detects changes relative to the published
  value; it is not a cryptographic signature or independent attestation.
- Keep company repositories private unless their canonical knowledge is safe
  to publish.
- Never commit `.ckb/`, `.memorizer/`, `.local-sources/`, credentials, exported
  sensitive Memory, company `web/dist/`, or the machine registry. Runtime
  rejects these tracked private paths case-insensitively before using them;
  `.gitignore` alone does not untrack an existing file.
- Keep source material inside the registered company boundary.
- Use explicit website allowlists and do not crawl private hosts.
- Keep the packaged portal same-origin. CORS is off by default and may be
  enabled only as a process-local development override for exact loopback
  origins. Portal requests also reject non-loopback Host headers.
- Treat Git history as history, not proof that a source is still valid.
- Keep Windows, Codex, `uv`, Git, LM Studio, Tesseract, and the plugin updated.

## Disclosure

The maintainer will acknowledge a valid private report, investigate it, and
coordinate a fix and release note before public disclosure. No response-time
SLA is offered for this free community project.
