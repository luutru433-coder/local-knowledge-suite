# Third-party notices

Local Knowledge Suite is licensed under MIT. It uses third-party components
that remain under their own licenses. This notice is informational; the
license files distributed with packages and release artifacts are
authoritative.

## Runtime and build dependencies

| Component | License |
| --- | --- |
| argon2-cffi | MIT |
| Beautiful Soup | MIT |
| certifi | MPL-2.0 |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| editables (editable-build dependency) | MIT |
| FastAPI | MIT |
| Hatchling (Python build backend) | MIT |
| HTTP Core | BSD-3-Clause |
| HTTPX | BSD-3-Clause |
| keyring | MIT |
| lightningcss (build dependency) | MPL-2.0 |
| MCP Python SDK | MIT |
| NumPy | BSD-3-Clause |
| openpyxl | MIT |
| packaging (build dependency) | Apache-2.0 OR BSD-2-Clause |
| pathspec (Hatchling build dependency) | MPL-2.0 |
| pluggy (build and test dependency) | MIT |
| Pydantic | MIT |
| pypdfium2 | BSD-3-Clause / Apache-2.0; bundled PDFium notices also apply |
| python-docx | MIT |
| python-multipart | Apache-2.0 |
| python-pptx | MIT |
| PyYAML | MIT |
| Uvicorn | BSD-3-Clause |
| React and React DOM | MIT |
| TypeScript | Apache-2.0 |
| Vite and `@vitejs/plugin-react` | MIT |
| VitePress and Vue | MIT |
| Tesseract OCR (optional external tool) | Apache-2.0 |
| trove-classifiers (Hatchling build dependency) | Apache-2.0 |

Transitive dependencies are recorded in `uv.lock` and `pnpm-lock.yaml`.
Every release generates normalized license inventories for the synchronized
Python runtime/build/test environment and the complete active Windows pnpm
graph derived from the pinned installed lock and pnpm's skipped-platform state.
It also generates an SBOM from the exact staged product. Every identity in the
exact Python inventory and active Windows Node inventory must appear under the
correct package ecosystem and version in that SBOM. Direct runtime
dependencies are additionally cross-checked against their manifests and
lockfiles.

## Explicit release allowlist

The release gate parses every dependency license expression and allows only
these reviewed identifiers: `0BSD`, `Apache-2.0`, `BlueOak-1.0.0`,
`BSD-2-Clause`, `BSD-3-Clause`, `CC0-1.0`, `ISC`, `MIT`, `MIT-0`, `MIT-CMU`,
`MPL-2.0`, `PSF-2.0`, and `Zlib`. `AND` and `OR` expressions are accepted only
when every identifier is on that list. Unknown identifiers, custom
`LicenseRef` values, SPDX exceptions, missing licenses, and malformed
expressions fail closed pending an explicit review.

MPL-2.0 is allowed after review because its file-level copyleft obligations do
not require the whole combined work to adopt MPL-2.0. The
current locked dependencies, `certifi` (runtime), `lightningcss` (web/docs
build), and `pathspec` (Python build), are consumed unchanged; this source
release records them in lockfiles rather than vendoring their package
contents. If a future release distributes
MPL-covered source files, those files must remain under MPL-2.0. If it
distributes executable forms of MPL-covered files, recipients must also be
informed how to obtain the corresponding Covered Source Code, and required
license notices must be retained.

The generated release SBOM records component identities. Reviewed license
identities and source links are provided by the separate Python and Node
license inventories. A copy of the exact PDFium and Chromium third-party
notices shipped by the selected `pypdfium2` wheel must be included in the
release archive. The archive must also include hash-verified upstream license
files and a deterministic manifest for React, React DOM, Scheduler, Vite, and
Rollup code embedded in the shipped portal bundle.
