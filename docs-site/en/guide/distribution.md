# Distribution and commercial use

::: info Technical summary, not legal advice
Ask qualified counsel to review your product, dependencies, branding, customer
data, and the rules where you operate.
:::

## What MIT permits

The [OSI-published MIT License](https://opensource.org/license/mit) permits use,
copying, modification, merging, publication, distribution, sublicensing, and
sale. Its core condition is to include the copyright and MIT permission notice
in all copies or substantial portions of the software.

You may therefore use Local Knowledge Suite internally, sell installation or
customization services, create a paid product from a fork, and distribute
source or binaries.

MIT does not change dependency licenses. Preserve and distribute every required
dependency license/notice through `THIRD_PARTY_NOTICES.md`, the SBOM, and the
release archive.

The official release ZIP is a **self-contained, buildable full-source bundle**:
it includes the distributable plugin, runtime, web/portal, documentation,
release tooling, tests, CI, and lockfiles. The extracted bundle can install the
plugin; it is not an install-only archive. Still verify its SHA-256, SBOM, and
notices.

SHA-256 detects whether an asset differs from the checksum you obtained, and
the annotated-tag gate checks that the tagged commit is the exact protected
`main` head selected for the release. Neither check is a cryptographic
signature or an independent attestation. Obtain the tag, assets, and checksum
from the trusted official GitHub repository.

## Pre-distribution checklist

1. Complete every gate in `docs/RELEASE_CHECKLIST.md`.
2. Pin versions, build the exact commit, and test a clean Windows machine.
3. Ship the ZIP, SHA-256, SBOM, and third-party notices.
4. Preserve the original `2026 John-IDK` copyright and MIT notice.
5. Identify your modifications and fork version.
6. Never package real company sources, Memory, credentials, registry data,
   `.ckb/`, `.local-sources/`, or machine-specific project manifests.
7. Use fictional data in screenshots, demos, and sales material.

## Forking and rebranding

For your own product:

- change the plugin/package name, marketplace ID, icons, repository, Pages URL,
  and maintainer details so users do not confuse it with upstream;
- retain original copyright/MIT and dependency notices;
- do not imply that John-IDK or upstream certifies, supports, or operates the
  fork;
- own updates, vulnerability handling, privacy documentation, and migrations;
  and
- revalidate URLs, checksums, SBOM, installation, and uninstall instructions.

## Support, SLA, and hosted services

Upstream v1 offers GitHub Issues only. It has no SLA, private support, hosted
service, billing, or license key. If you sell a service, clearly define your
provider identity, support channel, response targets, SLA, backups, data
location and transfers, privacy/security/retention process, incident response,
pricing, refunds, and termination terms.

Do not use upstream documentation to imply a commitment that the maintainer did
not make.

## Protect customer data

Give each customer/company separate repositories, source stores, credentials,
and access controls. Keep company Git private by default. Memory snapshots are
plain text and require review. Upstream v1 restricts model inference to local
loopback LM Studio. If a fork adds a remote model or cloud service, do not send
customer sources there unless the contract, privacy notice, access controls,
and an explicit customer choice permit it.
